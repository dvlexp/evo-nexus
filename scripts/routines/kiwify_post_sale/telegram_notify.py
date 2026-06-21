"""Notificacao Telegram para Daniel: nova venda + status consolidado por sub-step.

Usa Bot API direto (sem MCP) pq isto roda server-side, dentro do orquestrador,
nao em uma sessao Claude Code com MCP carregado.
"""

from __future__ import annotations

import logging
from typing import Optional

import urllib.parse
import urllib.request
import json

from .config import Settings

log = logging.getLogger(__name__)

STATUS_EMOJI = {
    "ok": "OK",
    "skipped": "SKIP",
    "failed": "FAIL",
    "dry_run": "DRY",
    "pending": "...",
    "running": "RUN",
}


def _telegram_post(settings: Settings, method: str, payload: dict) -> dict:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:  # noqa: BLE001
        log.error("Telegram %s falhou: %s", method, e)
        return {"ok": False, "error": str(e)}


def format_message(
    order: dict,
    runs: dict[str, dict],
    *,
    dry_run: bool = False,
    warnings: Optional[list[str]] = None,
) -> str:
    customer = order.get("Customer") or order.get("customer") or {}
    product = order.get("Product") or order.get("product") or {}
    commissions = order.get("Commissions") or order.get("commissions") or {}

    sale_id = order.get("kiwify_order_id") or order.get("order_id") or order.get("id") or "?"
    name = customer.get("full_name") or customer.get("name") or "?"
    email = customer.get("email") or "?"
    phone = customer.get("mobile") or customer.get("phone") or "?"
    product_name = product.get("product_name") or product.get("name") or "?"

    raw_amount = commissions.get("charge_amount") or order.get("amount") or 0
    # Kiwify usa centavos em alguns campos
    if isinstance(raw_amount, int) and raw_amount > 9999:
        amount = raw_amount / 100.0
    else:
        amount = float(raw_amount or 0)

    sales_url = f"https://dashboard.kiwify.com.br/sales/{sale_id}"

    header = "*DRY-RUN: Nova venda RXP (replay)*" if dry_run else "*Nova venda RXP*"

    lines = [
        header,
        "",
        f"Produto: *{product_name}*",
        f"Valor:   R$ {amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        f"Cliente: {name}",
        f"Email:   `{email}`",
        f"Tel:     {phone}",
        "",
        "Status do fluxo:",
    ]

    step_label = {
        "evocrm_sync":        "EvoCRM Sync       ",
        "whatsapp_confirm":   "WhatsApp Confirma ",
        "mautic_tag":         "Mautic Tag        ",
        "directus_provision": "Directus Provision",
    }
    any_failed = False
    for step in ("evocrm_sync", "whatsapp_confirm", "mautic_tag", "directus_provision"):
        run = runs.get(step) or {}
        status = run.get("status") or "pending"
        emoji = STATUS_EMOJI.get(status, "?")
        suffix = ""
        if status == "failed":
            any_failed = True
            err = (run.get("error_message") or "")[:120]
            suffix = f"  err=`{err}`"
        elif status == "skipped":
            note = ((run.get("result") or {}).get("reason") or "")[:80]
            if note:
                suffix = f"  ({note})"
        lines.append(f"  [{emoji}] {step_label[step]}{suffix}")

    if warnings:
        lines.append("")
        lines.append("Atencao:")
        for w in warnings:
            lines.append(f"  - {w}")

    if any_failed and not dry_run:
        lines.append("")
        lines.append("Acao: revisar ticket criado para Helm.")

    lines.append("")
    lines.append(f"[Ver venda no Kiwify]({sales_url})")

    return "\n".join(lines)


def send(settings: Settings, text: str, *, parse_mode: str = "Markdown") -> dict:
    """Manda mensagem para o chat configurado (Daniel)."""
    return _telegram_post(settings, "sendMessage", {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    })
