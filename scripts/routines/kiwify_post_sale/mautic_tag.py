"""Sub-step Mautic Tag.

Upsert do contato no Mautic + tag `paid-{slug-product-name}` conforme
ADR §4.7. Mautic 6.0.7 tem bug intermitente em PermissionRepository
(diagnostico Hawk 19/06/2026): role=null no UserProvider causa
TypeError 500 transitorio. Mitigacao: retry com backoff exponencial
(3 tentativas, 2s/4s/8s). Erro persistente nao bloqueia o fluxo,
mas o orquestrador marca failed e cria ticket EvoNexus.

Mautic API: Basic Auth. Memory custom-int-mautic SKILL.md.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Optional

from .config import Settings, slugify_product

log = logging.getLogger(__name__)

# Retry config (Hawk recomendou para mitigar Mautic 500 intermitente)
RETRY_DELAYS = (2, 4, 8)  # segundos
RETRYABLE_STATUSES = {500, 502, 503, 504}


class MauticError(Exception):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def _request(settings: Settings, method: str, path: str, body: Optional[dict] = None) -> dict:
    """Faz request HTTP com retry/backoff em 5xx (Mautic intermitente)."""
    url = f"{settings.mautic_url}/api/{path.lstrip('/')}"
    creds = base64.b64encode(f"{settings.mautic_user}:{settings.mautic_password}".encode()).decode()
    headers = {
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None

    last_err: Optional[MauticError] = None
    for attempt, delay in enumerate([0, *RETRY_DELAYS]):
        if delay > 0:
            time.sleep(delay)
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                if attempt > 0:
                    log.info("Mautic recuperou apos %d tentativas: %s %s", attempt, method, path)
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            try:
                body_text = e.read().decode("utf-8", errors="replace")
            except Exception:
                body_text = ""
            last_err = MauticError(
                f"HTTP {e.code} {method} {url}: {body_text[:400]}",
                status=e.code,
            )
            if e.code in RETRYABLE_STATUSES and attempt < len(RETRY_DELAYS):
                log.warning(
                    "Mautic %s (tentativa %d/%d, aguardando %ds): %s",
                    e.code, attempt + 1, len(RETRY_DELAYS) + 1, RETRY_DELAYS[attempt], body_text[:120],
                )
                continue
            raise last_err from None
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = MauticError(f"Network error {method} {url}: {e}")
            if attempt < len(RETRY_DELAYS):
                log.warning("Mautic network err (tentativa %d): %s", attempt + 1, e)
                continue
            raise last_err from None
    # Defensivo: nao deveria chegar aqui
    if last_err:
        raise last_err
    return {}


def upsert_contact(settings: Settings, email: str, first_name: str, phone: Optional[str] = None) -> dict:
    """Cria contato; se ja existe, atualiza (Mautic faz isso automatico em POST)."""
    body = {"email": email, "firstname": first_name}
    if phone:
        body["mobile"] = phone
    resp = _request(settings, "POST", "contacts/new", body=body)
    return resp.get("contact") or resp


def add_tag(settings: Settings, contact_id: int, tag: str) -> dict:
    return _request(settings, "PATCH", f"contacts/{contact_id}/edit", body={"tags": [tag]})


def run(payload: dict, settings: Settings, *, dry_run: bool = False) -> dict:
    customer = payload.get("Customer") or payload.get("customer") or {}
    product = payload.get("Product") or payload.get("product") or {}

    email = (customer.get("email") or "").lower().strip()
    if not email:
        return {"status": "skipped", "reason": "Customer sem email"}

    first_name = (customer.get("full_name") or customer.get("name") or "").split(" ")[0]
    phone = customer.get("mobile") or customer.get("phone") or ""
    product_name = product.get("product_name") or product.get("name") or ""
    tag = f"paid-{slugify_product(product_name)}" if product_name else "paid"

    if dry_run:
        return {
            "dry_run": True,
            "would_upsert_email": email,
            "would_apply_tag": tag,
            "phone": phone,
        }

    try:
        contact = upsert_contact(settings, email=email, first_name=first_name, phone=phone)
    except MauticError as e:
        # Circuit breaker leve: Hawk esta investigando Mautic 500. Nao bloqueia
        # o orquestrador. Reporta como failed mas sem stack trace gigante.
        log.warning("Mautic upsert falhou: %s", e)
        raise

    contact_id = contact.get("id") or (contact.get("fields") or {}).get("core", {}).get("id", {}).get("value")
    if not contact_id:
        # Fallback: parse no dict toplevel
        if isinstance(contact, dict):
            contact_id = contact.get("id")
    if not contact_id:
        raise MauticError(f"Mautic upsert sem id no retorno: {str(contact)[:200]}")

    try:
        add_tag(settings, contact_id, tag)
    except MauticError as e:
        log.warning("Mautic add_tag falhou (seguindo): %s", e)

    return {"contact_id": contact_id, "tag": tag}
