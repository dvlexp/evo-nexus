"""Kiwify post-sale webhook receiver.

Entry point para o orquestrador Kiwify Post-Sale (Fase 2 da feature
kiwify-post-sale-restructure). Recebe payload do n8n RXP_ROTEADOR_MARKETPLACE
(que continua sendo a fonte de verdade do webhook original do Kiwify) e
dispara os 4 sub-steps em background.

Backward compat: o n8n continua gravando a venda em Sheets e fazendo o que
ja fazia. So adicionamos um node HTTP POST extra apontando pra este endpoint.

Auth: HMAC SHA256 do body cru com KIWIFY_WEBHOOK_SECRET no header
X-Kiwify-Forward-Signature (formato hex). Fallback: shared secret via query
param ?secret= (timing-safe compare) pra simplicidade no node n8n se preferir.

A execucao do orquestrador roda em thread daemon pra responder rapido (n8n
nao precisa esperar) e o resultado fica no JSONL +
public.kiwify_post_sale_runs. Pra debug, GET /api/kiwify/webhook/last retorna
um snapshot do ultimo run.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets as _secrets
import threading
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("kiwify_webhook", __name__)


# Cache em memoria do ultimo run (debug/observabilidade rapida)
_LAST_RUN: dict = {"ts": None, "sale_id": None, "summary": None, "error": None}
_LAST_RUN_LOCK = threading.Lock()


def _get_secret() -> str:
    """Lazy read pra permitir hot-reload do .env."""
    return os.environ.get("KIWIFY_WEBHOOK_SECRET", "")


def _verify_signature(raw_body: bytes, signature_hex: str, secret: str) -> bool:
    if not signature_hex or not secret:
        return False
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return _secrets.compare_digest(digest, signature_hex.strip().lower())


def _run_orchestrator(payload: dict, dry_run: bool) -> None:
    """Executa o orquestrador (thread). Atualiza _LAST_RUN."""
    sale_id = None
    try:
        # Import tardio: evita custo no startup e permite testar a rota
        # sem todo o stack de scripts/. Adiciona o root do repo no sys.path
        # caso app.py tenha sido lancado de dashboard/backend/ (cwd) — assim
        # `scripts.routines.kiwify_post_sale` resolve independente do launcher.
        import sys as _sys
        _root = "/home/daniel/evo-nexus"
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        from scripts.routines.kiwify_post_sale import run as kiwify_run

        sale_id = kiwify_run.normalize_sale_id(payload)
        summary = kiwify_run.process(payload, dry_run=dry_run, send_telegram=True)
        with _LAST_RUN_LOCK:
            _LAST_RUN.update({
                "ts": datetime.now(timezone.utc).isoformat(),
                "sale_id": summary.get("sale_id") or sale_id,
                "dry_run": dry_run,
                "summary": summary,
                "error": None,
            })
        logger.info(
            "kiwify_webhook: processed sale_id=%s dry_run=%s errors=%s",
            summary.get("sale_id"), dry_run, list((summary.get("errors") or {}).keys()),
        )
    except Exception as exc:  # noqa: BLE001
        tb = traceback.format_exc()
        logger.exception("kiwify_webhook: orchestrator failed: %s", exc)
        with _LAST_RUN_LOCK:
            _LAST_RUN.update({
                "ts": datetime.now(timezone.utc).isoformat(),
                "sale_id": sale_id,
                "dry_run": dry_run,
                "summary": None,
                "error": f"{type(exc).__name__}: {exc}\n{tb[-800:]}",
            })


def _extract_dry_run_flag() -> bool:
    """dry_run via query param ?dry_run=1 OU env KIWIFY_POST_SALE_DRY_RUN."""
    q = (request.args.get("dry_run") or "").lower()
    if q in ("1", "true", "yes"):
        return True
    if q in ("0", "false", "no"):
        return False
    return os.environ.get("KIWIFY_POST_SALE_DRY_RUN", "").lower() in ("1", "true", "yes")


@bp.route("/api/kiwify/webhook", methods=["POST"])
def kiwify_webhook():
    """Recebe payload Kiwify (encaminhado pelo n8n) e dispara o orquestrador.

    Auth (qualquer um dos dois funciona):
      1) Header X-Kiwify-Forward-Signature = HMAC-SHA256(body, KIWIFY_WEBHOOK_SECRET) em hex
      2) Query ?secret=<KIWIFY_WEBHOOK_SECRET> (timing-safe compare)

    Sem secret configurado no env, a rota recusa todas as requisicoes.
    """
    secret = _get_secret()
    if not secret:
        logger.error("kiwify_webhook: KIWIFY_WEBHOOK_SECRET nao configurado")
        return jsonify({"error": "webhook nao configurado no servidor"}), 503

    raw_body = request.get_data(cache=True) or b""

    # 1) HMAC signature (preferido)
    sig = request.headers.get("X-Kiwify-Forward-Signature") or request.headers.get("X-Forward-Signature")
    sig_ok = _verify_signature(raw_body, sig or "", secret)

    # 2) Fallback: shared secret via query
    qp_secret = request.args.get("secret") or ""
    qp_ok = bool(qp_secret) and _secrets.compare_digest(qp_secret, secret)

    if not (sig_ok or qp_ok):
        logger.warning(
            "kiwify_webhook: unauthorized (sig_present=%s qp_present=%s)",
            bool(sig), bool(qp_secret),
        )
        return jsonify({"error": "unauthorized"}), 401

    # Parse JSON (Kiwify webhook e sempre application/json)
    try:
        payload: Any = json.loads(raw_body.decode("utf-8")) if raw_body else None
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"invalid json: {exc}"}), 400

    if not isinstance(payload, dict):
        return jsonify({"error": "payload deve ser objeto JSON"}), 400

    dry_run = _extract_dry_run_flag()

    # Quick sanity: tem algum identificador?
    sale_id_preview = (
        payload.get("kiwify_order_id")
        or payload.get("order_id")
        or payload.get("id")
        or payload.get("order_ref")
    )
    if not sale_id_preview:
        return jsonify({"error": "payload sem kiwify_order_id/order_id/id/order_ref"}), 422

    # Dispara em thread daemon pra responder rapido ao n8n (timeout curto)
    th = threading.Thread(
        target=_run_orchestrator,
        args=(payload, dry_run),
        name=f"kiwify-post-sale-{sale_id_preview}",
        daemon=True,
    )
    th.start()

    return jsonify({
        "ok": True,
        "accepted": True,
        "sale_id": str(sale_id_preview),
        "dry_run": dry_run,
        "message": "orquestrador disparado em background; ver /api/kiwify/webhook/last ou JSONL pro resultado",
    }), 202


@bp.route("/api/kiwify/webhook/last", methods=["GET"])
def kiwify_webhook_last():
    """Retorna o snapshot do ultimo run (em memoria). Util pra debug rapido.

    Acesso protegido pelo mesmo secret (header ou query) — evita expor
    dados de cliente pra qualquer um que acerte a URL.
    """
    secret = _get_secret()
    if not secret:
        return jsonify({"error": "webhook nao configurado"}), 503
    incoming = (
        request.args.get("secret")
        or request.headers.get("X-Kiwify-Forward-Signature")
        or ""
    )
    if not (incoming and _secrets.compare_digest(incoming, secret)):
        return jsonify({"error": "unauthorized"}), 401
    with _LAST_RUN_LOCK:
        return jsonify(dict(_LAST_RUN))


@bp.route("/api/kiwify/webhook/health", methods=["GET"])
def kiwify_webhook_health():
    """Healthcheck publico (sem segredo) — so confirma que a rota esta viva."""
    return jsonify({
        "ok": True,
        "configured": bool(_get_secret()),
        "last_run_ts": _LAST_RUN.get("ts"),
    })


@bp.route("/api/kiwify/webhook/replay/<sale_id>", methods=["POST"])
def kiwify_webhook_replay(sale_id: str):
    """Replay sincrono (ou async com ?async=1) de uma venda ja gravada.

    Carrega o raw_payload de public.kiwify_orders e re-dispara os 4 sub-steps.
    Respeita idempotencia (sub-steps com status ok/skipped nao re-executam).
    Util pra Daniel reprocessar Cleo/Daniel Amorim sem precisar do payload
    bruto em maos.
    """
    secret = _get_secret()
    if not secret:
        return jsonify({"error": "webhook nao configurado"}), 503
    incoming = request.args.get("secret") or request.headers.get("X-Kiwify-Forward-Signature") or ""
    if not (incoming and _secrets.compare_digest(incoming, secret)):
        return jsonify({"error": "unauthorized"}), 401

    try:
        from dashboard.backend.integrations.aurora_db import query
        rows = query("SELECT raw_payload FROM kiwify_orders WHERE kiwify_order_id=%s", (sale_id,))
    except Exception as exc:  # noqa: BLE001
        logger.exception("kiwify_webhook_replay: db error: %s", exc)
        return jsonify({"error": f"db error: {exc}"}), 500

    if not rows:
        return jsonify({"error": f"pedido {sale_id} nao encontrado em kiwify_orders"}), 404

    payload = rows[0]["raw_payload"]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"raw_payload nao e json valido: {exc}"}), 500

    dry_run = _extract_dry_run_flag()
    async_mode = (request.args.get("async") or "").lower() in ("1", "true", "yes")

    if async_mode:
        th = threading.Thread(
            target=_run_orchestrator, args=(payload, dry_run),
            name=f"kiwify-replay-{sale_id}", daemon=True,
        )
        th.start()
        return jsonify({"ok": True, "async": True, "sale_id": sale_id, "dry_run": dry_run}), 202

    # Sincrono: util pra Daniel testar do terminal
    try:
        import sys as _sys
        _root = "/home/daniel/evo-nexus"
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        from scripts.routines.kiwify_post_sale import run as kiwify_run
        summary = kiwify_run.process(payload, dry_run=dry_run, send_telegram=False)
    except Exception as exc:  # noqa: BLE001
        logger.exception("kiwify_webhook_replay: orchestrator failed: %s", exc)
        return jsonify({"error": str(exc), "traceback": traceback.format_exc()[-2000:]}), 500

    return jsonify({"ok": True, "sync": True, "sale_id": sale_id, "dry_run": dry_run, "summary": summary})
