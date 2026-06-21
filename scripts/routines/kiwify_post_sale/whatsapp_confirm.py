"""Sub-step WhatsApp Confirmacao.

Dispara template WABA via Meta Graph API (numero Aurora 5511940189416,
phone_number_id 1145106465351044). Template padrao
`rxp_confirmacao_compra` foi APROVADO em 2026-06-20 (UTILITY, pt_BR,
id Meta 1324418402449413). Mantemos o fallback skipped abaixo caso
algum dia a Meta marque o template como pausado ou expirado.

Decisao do Daniel (19/06/2026): padrao confirmado em outras features e
WABA Cloud API via skill custom-int-waba-rxp, disparado direto pela API
Meta Graph (NAO via Evolution API/Baileys).
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Optional

from .config import (
    Settings,
    WABA_TEMPLATE_CONFIRMACAO_NAME,
    WABA_TEMPLATE_CONFIRMACAO_LANG,
)

log = logging.getLogger(__name__)


class WABAError(Exception):
    pass


def _normalize_phone(phone: str) -> Optional[str]:
    """E.164 (digitos puros). Kiwify costuma mandar com +DDI."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return None
    # Se nao tiver DDI (Brasil), assume 55
    if len(digits) in (10, 11):  # DDD+numero
        digits = "55" + digits
    return digits


def send_template(
    settings: Settings,
    to: str,
    template_name: str,
    components: list,
    lang: str = "pt_BR",
) -> dict:
    url = f"https://graph.facebook.com/v20.0/{settings.waba_phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang},
            "components": components,
        },
    }
    headers = {
        "Authorization": f"Bearer {settings.waba_token}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise WABAError(f"HTTP {e.code} {url}: {body[:400]}") from None


def run(payload: dict, settings: Settings, *, dry_run: bool = False) -> dict:
    customer = payload.get("Customer") or payload.get("customer") or {}
    product = payload.get("Product") or payload.get("product") or {}

    phone = _normalize_phone(customer.get("mobile") or customer.get("phone"))
    nome = (customer.get("full_name") or customer.get("name") or "").split(" ")[0] or "cliente"
    product_name = product.get("product_name") or product.get("name") or "seu produto"

    if not phone:
        return {"status": "skipped", "reason": "Customer sem telefone"}

    components = [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": nome},
                {"type": "text", "text": product_name},
            ],
        }
    ]

    if dry_run:
        return {
            "dry_run": True,
            "would_send_to": phone,
            "template": WABA_TEMPLATE_CONFIRMACAO_NAME,
            "lang": WABA_TEMPLATE_CONFIRMACAO_LANG,
            "components": components,
        }

    try:
        resp = send_template(
            settings,
            to=phone,
            template_name=WABA_TEMPLATE_CONFIRMACAO_NAME,
            components=components,
            lang=WABA_TEMPLATE_CONFIRMACAO_LANG,
        )
    except WABAError as e:
        # Template PENDING ou outro erro Meta: marca skipped (nao failed)
        # para nao quebrar o resto do fluxo. Daniel revisa pelo Telegram.
        emsg = str(e)
        if "PENDING" in emsg or "not approved" in emsg.lower() or "(#132" in emsg:
            return {"status": "skipped", "reason": f"Template ainda nao aprovado: {emsg[:120]}"}
        raise

    msg_id = ((resp.get("messages") or [{}])[0]).get("id")
    return {"message_id": msg_id, "to": phone, "template": WABA_TEMPLATE_CONFIRMACAO_NAME}
