"""Sub-step EvoCRM Sync (substitui o n8n "Kommo Sync" / "KommoSync").

Decisao Daniel (19/06/2026): "Kommo Sync" agora e "EvoCRM Sync". EvoCRM e
o CRM oficial RXP. Cria contato + cria opportunity no pipeline
"Pós-venda RXP" no estagio "Pagamento Confirmado".

Endpoints (memory project_evocrm_api.md confirmado):
    POST /api/v1/contacts
    POST /api/v1/contacts/filter   (busca por email)
    POST /api/v1/contacts/{id}/notes
    POST /api/v1/pipelines/{pipeline_id}/pipeline_items
        body: {"type": "contact", "item_id": "<uuid>", "pipeline_stage_id": "<uuid>"}
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Optional

from .config import (
    Settings,
    EVO_CRM_POSTVENDA_PIPELINE_ID,
    EVO_CRM_POSTVENDA_STAGE_PAGAMENTO_CONFIRMADO,
)

log = logging.getLogger(__name__)


class EvoCRMError(Exception):
    pass


def _request(settings: Settings, method: str, path: str, body: Optional[dict] = None) -> dict:
    url = f"{settings.evo_crm_url}/api/v1/{path.lstrip('/')}"
    headers = {
        "api_access_token": settings.evo_crm_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise EvoCRMError(f"HTTP {e.code} {method} {url}: {body_text[:300]}") from None


def find_contact_by_email(settings: Settings, email: str) -> Optional[dict]:
    """Retorna o primeiro contato com este email (ou None)."""
    if not email:
        return None
    body = {
        "payload": [
            {
                "attribute_key": "email",
                "filter_operator": "equal_to",
                "values": [email.lower().strip()],
            }
        ]
    }
    resp = _request(settings, "POST", "contacts/filter", body=body)
    # EvoCRM (rc5/Chatwoot fork) retorna {success: bool, data: [contact, ...]}
    # mas algumas rotas legadas embrulham em {data: {payload: [...]}}.
    # Cobrimos os dois shapes pra nao quebrar quando upgradearem.
    data = resp.get("data")
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("payload") or []
    else:
        items = resp.get("payload") or []
    return items[0] if items else None


def create_contact(settings: Settings, name: str, email: str, phone: Optional[str] = None) -> dict:
    body = {"name": name or email, "email": email}
    if phone:
        body["phone_number"] = phone
    resp = _request(settings, "POST", "contacts", body=body)
    # EvoCRM (Chatwoot fork) retorna shape inconsistente: as vezes
    # {data: {id,...}}, as vezes {data: {contact: {id,...}}}. Cobrimos ambos.
    data = resp.get("data") or {}
    if isinstance(data, dict) and isinstance(data.get("contact"), dict):
        return data["contact"]
    if isinstance(data, dict):
        return data
    return resp


def add_contact_note(settings: Settings, contact_id: str, content: str) -> dict:
    return _request(settings, "POST", f"contacts/{contact_id}/notes", body={"content": content})


def create_pipeline_item(
    settings: Settings,
    contact_id: str,
    pipeline_id: str = EVO_CRM_POSTVENDA_PIPELINE_ID,
    stage_id: str = EVO_CRM_POSTVENDA_STAGE_PAGAMENTO_CONFIRMADO,
) -> dict:
    body = {
        "type": "contact",
        "item_id": contact_id,
        "pipeline_stage_id": stage_id,
    }
    return _request(
        settings, "POST", f"pipelines/{pipeline_id}/pipeline_items", body=body
    )


def run(payload: dict, settings: Settings, *, dry_run: bool = False) -> dict:
    """Executa o sub-step. Retorna dict com keys: contact_id, pipeline_item_id."""
    customer = payload.get("Customer") or payload.get("customer") or {}
    product = payload.get("Product") or payload.get("product") or {}
    commissions = payload.get("Commissions") or payload.get("commissions") or {}

    email = (customer.get("email") or "").lower().strip()
    name = customer.get("full_name") or customer.get("name") or email or "Cliente Kiwify"
    phone = customer.get("mobile") or customer.get("phone") or ""
    product_name = product.get("product_name") or product.get("name") or "?"
    raw_amount = commissions.get("charge_amount") or payload.get("amount") or 0
    amount = (raw_amount / 100.0) if isinstance(raw_amount, int) and raw_amount > 9999 else float(raw_amount or 0)

    if not email:
        raise EvoCRMError("Customer email ausente; nao da pra sincronizar EvoCRM")

    if dry_run:
        existing = find_contact_by_email(settings, email)
        return {
            "dry_run": True,
            "would_create_contact": existing is None,
            "existing_contact_id": (existing or {}).get("id"),
            "would_create_pipeline_item_in_stage": "Pagamento Confirmado",
            "pipeline": "Pós-venda RXP",
            "amount": amount,
            "note_preview": f"Venda Kiwify: {product_name} | R$ {amount:.2f}",
        }

    # 1) Lookup contato
    contact = find_contact_by_email(settings, email)
    created = False
    if not contact:
        contact = create_contact(settings, name=name, email=email, phone=phone)
        created = True

    contact_id = contact.get("id") or contact.get("contact", {}).get("id")
    if not contact_id:
        raise EvoCRMError(f"Contato sem id retornado pela API: {contact}")

    # 2) Pipeline item (Pós-venda RXP / Pagamento Confirmado)
    note_text = (
        f"Venda Kiwify confirmada\n"
        f"Produto: {product_name}\n"
        f"Valor: R$ {amount:,.2f}\n"
        f"Pedido: {payload.get('kiwify_order_id') or payload.get('order_id') or payload.get('id')}"
    ).replace(",", "X").replace(".", ",").replace("X", ".")
    note = None
    item = None
    try:
        item = create_pipeline_item(settings, contact_id=contact_id)
    except EvoCRMError as e:
        # Se contato ja tem item no pipeline, EvoCRM pode retornar 422; nao bloqueia o resto
        log.warning("create_pipeline_item falhou (seguindo): %s", e)
    try:
        note = add_contact_note(settings, contact_id, note_text)
    except EvoCRMError as e:
        log.warning("add_contact_note falhou: %s", e)

    item_id = None
    if item:
        data = item.get("data") or item
        item_id = data.get("id") or (data.get("pipeline_item") or {}).get("id")

    return {
        "contact_id": contact_id,
        "contact_created": created,
        "pipeline_item_id": item_id,
        "note_created": bool(note),
    }
