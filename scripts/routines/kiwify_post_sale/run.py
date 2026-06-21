#!/usr/bin/env python3
"""Orquestrador Kiwify Post-Sale (Fase 2).

Recebe o payload de webhook Kiwify (formato `sale.completed`), roda os 4
sub-steps com isolamento de falhas, persiste estado em
public.kiwify_post_sale_runs, envia notificacao consolidada no Telegram
e (em producao) cria ticket EvoNexus se 1+ sub-step falhou.

Uso:
    # Producao (a partir do webhook receiver, payload no stdin):
    cat payload.json | python -m scripts.routines.kiwify_post_sale.run

    # Dry-run (nao escreve em EvoCRM/Mautic/Directus/WhatsApp,
    # nao manda Telegram real; so mostra o que faria):
    KIWIFY_POST_SALE_DRY_RUN=true python -m scripts.routines.kiwify_post_sale.run < payload.json

    # Replay de venda existente pelo id (carrega de kiwify_orders):
    python -m scripts.routines.kiwify_post_sale.run --replay <kiwify_order_id>
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Carregar .env do workspace root antes de importar configs que requerem env
def _load_dotenv():
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

# Imports tardios (depois do .env)
from scripts.routines.kiwify_post_sale import (
    config,
    db,
    evocrm_sync,
    whatsapp_confirm,
    mautic_tag,
    directus_provision,
    telegram_notify,
)


# ----------------------------------------------------------------------------
# Logging em JSONL
# ----------------------------------------------------------------------------

LOG_DIR = Path(__file__).resolve().parents[3] / "workspace" / "ADWs" / "logs" / "kiwify-post-sale"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _log_path() -> Path:
    return LOG_DIR / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"


def _log(event: dict) -> None:
    event["ts"] = datetime.now(timezone.utc).isoformat()
    with _log_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("kiwify_post_sale")


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

SUB_STEP_MODULES = [
    ("evocrm_sync", evocrm_sync),
    ("whatsapp_confirm", whatsapp_confirm),
    ("mautic_tag", mautic_tag),
    ("directus_provision", directus_provision),
]


def normalize_sale_id(payload: dict) -> str:
    sid = (
        payload.get("kiwify_order_id")
        or payload.get("order_id")
        or payload.get("id")
        or payload.get("order_ref")
    )
    if not sid:
        raise ValueError("Payload sem identificador de pedido (kiwify_order_id/order_id/id/order_ref)")
    return str(sid)


def run_sub_step(name: str, mod, payload: dict, settings: config.Settings, sale_id: str, dry_run: bool) -> tuple[str, dict, Optional[str]]:
    """Executa um sub-step com isolamento de falha. Retorna (status, result, error)."""
    if not dry_run and db.is_step_ok(sale_id, name):
        return (db.STATUS_SKIPPED, {"reason": "ja executado com sucesso (idempotencia)"}, None)

    locked = db.start_run(sale_id, name, dry_run=dry_run)
    if not locked and not dry_run:
        return (db.STATUS_SKIPPED, {"reason": "ja em ok/skipped"}, None)

    try:
        result = mod.run(payload, settings, dry_run=dry_run)
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        log.warning("[%s] %s falhou: %s", sale_id, name, err)
        _log({"event": "sub_step_failed", "sale_id": sale_id, "sub_step": name, "error": err, "traceback": traceback.format_exc()})
        if not dry_run:
            db.finish_run(sale_id, name, db.STATUS_FAILED, error=err)
        return (db.STATUS_FAILED, {}, err)

    # Detecta status declarado pelo sub-step (skipped por logica de negocio)
    if isinstance(result, dict) and result.get("status") == "skipped":
        if not dry_run:
            db.finish_run(sale_id, name, db.STATUS_SKIPPED, result=result)
        return (db.STATUS_SKIPPED, result, None)

    final_status = db.STATUS_DRY_RUN if dry_run else db.STATUS_OK
    if not dry_run:
        db.finish_run(sale_id, name, final_status, result=result)
    return (final_status, result if isinstance(result, dict) else {"raw": result}, None)


def maybe_create_ticket(sale_id: str, payload: dict, runs: dict[str, dict], settings: config.Settings) -> Optional[str]:
    """Cria ticket EvoNexus (assignee_agent=helm-conductor) se 1+ sub-step falhou apos retries."""
    failed = [s for s, r in runs.items() if r["status"] == db.STATUS_FAILED]
    if not failed:
        return None

    if not settings.dashboard_api_token:
        log.info("DASHBOARD_API_TOKEN ausente; pulando criacao de ticket")
        return None

    customer = payload.get("Customer") or payload.get("customer") or {}
    product = payload.get("Product") or payload.get("product") or {}
    title = f"[Kiwify] {customer.get('full_name') or customer.get('email') or 'venda'} | {product.get('product_name') or '?'} | falhou {','.join(failed)}"
    description_lines = [
        f"Pedido Kiwify: {sale_id}",
        f"Cliente: {customer.get('full_name') or '?'} <{customer.get('email') or '?'}>",
        f"Produto: {product.get('product_name') or '?'}",
        "",
        "Sub-steps falhados:",
    ]
    for s in failed:
        description_lines.append(f"  - {s}: {runs[s].get('error') or runs[s].get('error_message')}")

    body = {
        "title": title[:200],
        "description": "\n".join(description_lines),
        "priority": "high",
        "assignee_agent": "helm-conductor",
        "status": "open",
    }
    base_url = os.environ.get("EVONEXUS_API_URL", "http://localhost:8080").rstrip("/")
    import urllib.request
    try:
        req = urllib.request.Request(
            f"{base_url}/api/tickets",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.dashboard_api_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return (data.get("ticket") or {}).get("id") or data.get("id")
    except Exception as e:  # noqa: BLE001
        log.warning("Criacao de ticket EvoNexus falhou: %s", e)
        return None


# ----------------------------------------------------------------------------
# Entrypoint
# ----------------------------------------------------------------------------

def process(payload: dict, *, dry_run: bool = False, send_telegram: bool = True) -> dict:
    settings = config.load()
    if dry_run:
        settings = config.Settings(**{**settings.__dict__, "dry_run": True})

    sale_id = normalize_sale_id(payload)
    _log({"event": "process_start", "sale_id": sale_id, "dry_run": dry_run})

    # 1) Idempotencia primaria: insere kiwify_orders (no-op se ja existe)
    if not dry_run:
        new_order = db.upsert_order(payload)
        _log({"event": "order_upsert", "sale_id": sale_id, "new": new_order})

    # 2) Sub-steps (sequencialmente para simplicidade; podem virar paralelos depois)
    sub_results: dict[str, dict] = {}
    warnings_all: list[str] = []
    for name, mod in SUB_STEP_MODULES:
        status, result, error = run_sub_step(name, mod, payload, settings, sale_id, dry_run)
        sub_results[name] = {"status": status, "result": result, "error": error}
        _log({"event": "sub_step_done", "sale_id": sale_id, "sub_step": name, "status": status, "result": result, "error": error})
        # Coletar warnings (ex: directus comprador != cliente)
        if isinstance(result, dict):
            for w in result.get("warnings") or []:
                warnings_all.append(f"[{name}] {w}")

    # 3) Telegram consolidado
    runs_for_msg = {
        name: {
            "status": v["status"],
            "error_message": v["error"],
            "result": v["result"],
        }
        for name, v in sub_results.items()
    }
    msg = telegram_notify.format_message(payload, runs_for_msg, dry_run=dry_run, warnings=warnings_all)
    print("\n" + msg + "\n", file=sys.stderr)  # sempre visivel no log do orquestrador

    telegram_resp = None
    if send_telegram:
        try:
            telegram_resp = telegram_notify.send(settings, msg)
        except Exception as e:  # noqa: BLE001
            log.warning("Telegram send falhou: %s", e)
            telegram_resp = {"ok": False, "error": str(e)}

    # 4) Ticket Helm se houve falha real
    ticket_id = None
    if not dry_run:
        ticket_id = maybe_create_ticket(sale_id, payload, sub_results, settings)

    summary = {
        "sale_id": sale_id,
        "dry_run": dry_run,
        "sub_steps": {n: v["status"] for n, v in sub_results.items()},
        "errors": {n: v["error"] for n, v in sub_results.items() if v["error"]},
        "warnings": warnings_all,
        "telegram": (telegram_resp or {}).get("ok") if telegram_resp else None,
        "ticket_id": ticket_id,
    }
    _log({"event": "process_done", **summary})
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Orquestrador Kiwify Post-Sale")
    parser.add_argument("--replay", help="kiwify_order_id existente na tabela kiwify_orders (carrega payload de la)")
    parser.add_argument("--payload-file", help="Arquivo JSON com payload Kiwify (default: stdin)")
    parser.add_argument("--dry-run", action="store_true", help="Forca dry-run (alias para KIWIFY_POST_SALE_DRY_RUN=true)")
    parser.add_argument("--no-telegram", action="store_true", help="Nao envia mensagem Telegram (so loga)")
    args = parser.parse_args()

    if args.replay:
        from dashboard.backend.integrations.aurora_db import query
        rows = query("SELECT raw_payload FROM kiwify_orders WHERE kiwify_order_id=%s", (args.replay,))
        if not rows:
            print(f"ERRO: pedido {args.replay} nao encontrado em kiwify_orders", file=sys.stderr)
            return 2
        payload = rows[0]["raw_payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
    elif args.payload_file:
        payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
    else:
        raw = sys.stdin.read()
        if not raw.strip():
            print("ERRO: payload vazio (passe via stdin, --payload-file ou --replay)", file=sys.stderr)
            return 2
        payload = json.loads(raw)

    dry_run = args.dry_run or os.environ.get("KIWIFY_POST_SALE_DRY_RUN", "").lower() in ("1", "true", "yes")

    t0 = time.time()
    summary = process(payload, dry_run=dry_run, send_telegram=not args.no_telegram)
    summary["elapsed_seconds"] = round(time.time() - t0, 2)
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    # Exit code: 0 se nada falhou, 1 se houve falha (util pra CI/n8n)
    return 0 if not summary["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
