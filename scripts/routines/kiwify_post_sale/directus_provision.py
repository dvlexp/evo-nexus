"""Sub-step Directus Provision.

Cria usuario na plataforma de membros RXP + atribui role do curso comprado.
Regra critica (memory feedback_kommo_masterflow_modulo_exclusivo):
    Para Kommo MasterFlow e Kommo MasterSetup, criar primeiro o
    Modulo Exclusivo do Cliente no Directus (com nome do cliente)
    e SO DEPOIS liberar acesso.

Tambem detecta caso comprador != cliente real (ex: marido compra para
esposa) e adiciona warning para Daniel revisar (nao tem como resolver
automaticamente sem metadata explicita).
"""

from __future__ import annotations

import json
import logging
import secrets
import string
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from .config import Settings, directus_mapping_for

log = logging.getLogger(__name__)


class DirectusError(Exception):
    pass


def _request(settings: Settings, method: str, path: str, body: Optional[dict] = None, params: Optional[dict] = None) -> dict:
    url = f"{settings.directus_url}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": f"Bearer {settings.directus_token}",
        "Content-Type": "application/json",
    }
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
        raise DirectusError(f"HTTP {e.code} {method} {url}: {body_text[:300]}") from None


def _generate_password(n: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def find_user_by_email(settings: Settings, email: str) -> Optional[dict]:
    resp = _request(
        settings,
        "GET",
        "/users",
        params={
            "filter[email][_eq]": email,
            "fields": "id,email,role,products,first_name,last_name",
            "limit": 1,
        },
    )
    items = resp.get("data") or []
    return items[0] if items else None


def create_user(settings: Settings, email: str, name: str, role_id: str, product_slug: str, phone: Optional[str] = None) -> dict:
    first_last = (name or email).split(" ", 1) + [""]
    payload = {
        "email": email,
        "password": _generate_password(),
        "role": role_id,
        "status": "active",
        "first_name": first_last[0],
        "last_name": first_last[1],
        "products": [product_slug],
    }
    if phone:
        payload["whatsapp"] = phone
    resp = _request(settings, "POST", "/users", body=payload)
    return resp.get("data") or {}


def merge_user_products(settings: Settings, user_id: str, product_slug: str, current: list) -> dict:
    products = list({*current, product_slug})
    return _request(settings, "PATCH", f"/users/{user_id}", body={"products": products})


def create_exclusive_module(settings: Settings, course_id: int, user_id: str, customer_name: str) -> dict:
    """Cria modulo exclusivo do cliente na coleção rxp_site_modules.

    Schema confirmado em memory rxp_membros_plataforma:
        course_id (FK), is_exclusive=true, exclusive_users (M2M com user_id)
    """
    title = f"Encontros Gravados - {customer_name}"
    body = {
        "course_id": course_id,
        "title": title,
        "is_exclusive": True,
        "exclusive_users": [{"directus_users_id": user_id}],
        "status": "published",
    }
    return _request(settings, "POST", "/items/rxp_site_modules", body=body)


def _names_diverge(buyer_name: str, customer_name: str) -> bool:
    """Heuristica simples: se ambos sao validos e nao tem nenhum termo em comum (case-insens), divergem."""
    if not buyer_name or not customer_name:
        return False
    a = {t for t in buyer_name.lower().split() if len(t) > 2}
    b = {t for t in customer_name.lower().split() if len(t) > 2}
    if not a or not b:
        return False
    return len(a & b) == 0


def run(payload: dict, settings: Settings, *, dry_run: bool = False) -> dict:
    customer = payload.get("Customer") or payload.get("customer") or {}
    product = payload.get("Product") or payload.get("product") or {}

    email = (customer.get("email") or "").lower().strip()
    name = customer.get("full_name") or customer.get("name") or ""
    phone = customer.get("mobile") or customer.get("phone") or ""

    product_name = product.get("product_name") or product.get("name") or ""
    product_slug = product.get("product_slug") or product.get("slug") or ""

    mapping = directus_mapping_for(product_name, product_slug)
    warnings: list[str] = []

    if not mapping:
        return {
            "status": "skipped",
            "reason": f"Produto sem mapping Directus: {product_name!r} / slug={product_slug!r}",
            "warnings": warnings,
        }

    if not email:
        return {"status": "skipped", "reason": "Customer sem email"}

    # Detecta divergencia comprador vs cliente real (memory feedback Kommo MasterFlow)
    # Algumas vendas Kiwify carregam metadados (campo subscriber, custom_fields, etc.)
    # Por enquanto so loga aviso se houver discrepancia evidente.
    metadata_customer = (
        payload.get("subscriber")
        or payload.get("metadata", {}).get("customer")
        or {}
    )
    real_customer_name = metadata_customer.get("full_name") or metadata_customer.get("name") or ""
    if real_customer_name and _names_diverge(name, real_customer_name):
        warnings.append(
            f"Comprador ({name}) != cliente declarado ({real_customer_name}). "
            "Provisionamento usou dados do comprador. Daniel: verificar."
        )

    customer_name_for_module = real_customer_name or name or email

    if dry_run:
        existing = find_user_by_email(settings, email)
        return {
            "dry_run": True,
            "mapping": mapping,
            "would_create_user": existing is None,
            "existing_user_id": (existing or {}).get("id"),
            "needs_exclusive_module": mapping["needs_exclusive_module"],
            "exclusive_module_title": f"Encontros Gravados - {customer_name_for_module}",
            "warnings": warnings,
        }

    # 1) Achar ou criar user
    existing = find_user_by_email(settings, email)
    created_user = False
    if existing:
        user_id = existing["id"]
        current_products = existing.get("products") or []
        if mapping["product_slug"] not in current_products:
            merge_user_products(settings, user_id, mapping["product_slug"], current_products)
    else:
        new_user = create_user(
            settings,
            email=email,
            name=name,
            role_id=mapping["role_id"],
            product_slug=mapping["product_slug"],
            phone=phone,
        )
        user_id = new_user.get("id")
        created_user = True
        if not user_id:
            raise DirectusError(f"create_user nao retornou id: {new_user}")

    # 2) Regra MasterFlow/MasterSetup: criar modulo exclusivo ANTES de liberar acesso
    module = None
    if mapping["needs_exclusive_module"]:
        try:
            module = create_exclusive_module(
                settings,
                course_id=mapping["course_id"],
                user_id=user_id,
                customer_name=customer_name_for_module,
            )
        except DirectusError as e:
            warnings.append(f"Modulo exclusivo nao criado (precisa criar manual): {e}")
            log.warning("create_exclusive_module falhou: %s", e)

    return {
        "user_id": user_id,
        "user_created": created_user,
        "role_id": mapping["role_id"],
        "product_slug": mapping["product_slug"],
        "exclusive_module_created": bool(module),
        "exclusive_module_id": ((module or {}).get("data") or {}).get("id"),
        "warnings": warnings,
    }
