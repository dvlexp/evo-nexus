"""Settings carregadas em runtime (nao no import, para nao cachear envs).

Padrao Settings reusavel (ver memory project_aurora_recovery: dataclass com
funcao load() que faz os.environ.get(...) na hora — evita armadilha de cache
em testes).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


# ----------------------------------------------------------------------------
# IDs FIXOS — descobertos na exploracao (curl no EvoCRM RXP em 2026-06-19)
# ----------------------------------------------------------------------------

# Pipeline "Pós-venda RXP" no EvoCRM (api-crm.resultadosexponenciais.com.br)
EVO_CRM_POSTVENDA_PIPELINE_ID = "b99874f9-d379-4129-ace7-b2b3017eec1d"
EVO_CRM_POSTVENDA_STAGE_PAGAMENTO_CONFIRMADO = "bdf5a965-11cc-43ff-837d-bdd78eff098c"

# Inbox Aurora (WABA Cloud via Evolution Xmacna) — fallback caso conversation
# precise ser criada para abrigar a mensagem outbound
EVO_CRM_AURORA_INBOX_ID = "a987f4cf-93f6-4bc4-a670-2b8b6510f3ad"

# Template WABA para confirmacao de compra (id Meta 1324418402449413)
# Status: APPROVED em 2026-06-20 (UTILITY, pt_BR). Caminho feliz ativo.
# Vars: {{1}} = nome, {{2}} = produto
WABA_TEMPLATE_CONFIRMACAO_NAME = "rxp_confirmacao_compra"
WABA_TEMPLATE_CONFIRMACAO_LANG = "pt_BR"

# Mapping produto Kiwify -> role/product_slug Directus
# Fonte: memory rxp_membros_plataforma + ADR §4.6 + custom-int-kiwify SKILL.md:280
# Quando a Fase 1.2 do plano entregar a collection product_course_mapping no
# Directus, isto vira lookup dinamico. Por ora, hardcoded.
PRODUCT_TO_DIRECTUS = {
    # slug -> dict com role_id, product_slug, exclusive_module (bool)
    "kommo-masterflow": {
        "role_id": "6d977de1-046b-4a3b-a304-d9175aa0e359",
        "product_slug": "kommo-masterflow",
        "course_id": 2,
        "needs_exclusive_module": True,  # regra MasterFlow/MasterSetup
        "display_name": "Kommo MasterFlow",
    },
    "kommo-master-setup": {
        "role_id": "854e5321-d6b6-4c91-95e7-bee4fa637240",
        "product_slug": "kommo-master-setup",
        "course_id": 3,
        "needs_exclusive_module": True,  # regra MasterFlow/MasterSetup
        "display_name": "Kommo MasterSetup",
    },
    "kommo-mastersetup": {  # alias
        "role_id": "854e5321-d6b6-4c91-95e7-bee4fa637240",
        "product_slug": "kommo-master-setup",
        "course_id": 3,
        "needs_exclusive_module": True,
        "display_name": "Kommo MasterSetup",
    },
    "n8n-masterflow": {
        "role_id": "16e8b4bb-1dcb-4f59-b9fa-904acee162d6",
        "product_slug": "n8n-masterflow",
        "course_id": 1,
        "needs_exclusive_module": False,
        "display_name": "N8N MasterFlow",
    },
}


@dataclass(frozen=True)
class Settings:
    evo_crm_url: str
    evo_crm_token: str
    mautic_url: str
    mautic_user: str
    mautic_password: str
    directus_url: str
    directus_token: str
    waba_phone_id: str
    waba_token: str
    telegram_bot_token: str
    telegram_chat_id: str
    dashboard_api_token: str
    dry_run: bool


def load() -> Settings:
    """Carrega env vars em runtime. Falha cedo se faltar nada critico."""
    def req(key: str) -> str:
        v = os.environ.get(key)
        if not v:
            raise RuntimeError(f"Env var obrigatoria nao definida: {key}")
        return v

    return Settings(
        evo_crm_url=req("EVO_CRM_URL").rstrip("/"),
        evo_crm_token=req("EVO_CRM_TOKEN"),
        mautic_url=req("MAUTIC_URL").rstrip("/"),
        mautic_user=req("MAUTIC_USER"),
        mautic_password=req("MAUTIC_PASSWORD"),
        directus_url=req("DIRECTUS_URL").rstrip("/"),
        directus_token=req("DIRECTUS_TOKEN"),
        waba_phone_id=req("WABA_RXP_PHONE_NUMBER_ID"),
        waba_token=req("WABA_RXP_TOKEN"),
        telegram_bot_token=req("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", "8860803037"),
        dashboard_api_token=os.environ.get("DASHBOARD_API_TOKEN", ""),
        dry_run=os.environ.get("KIWIFY_POST_SALE_DRY_RUN", "false").lower() in ("1", "true", "yes"),
    )


def slugify_product(product_name: str) -> str:
    """Slugify simples para Mautic tag paid-{slug} e Directus lookup.

    'Kommo Master Flow' -> 'kommo-master-flow'
    Preserva alias historico tambem (Kommo MasterFlow == kommo-masterflow).
    """
    import re
    import unicodedata
    text = unicodedata.normalize("NFKD", product_name or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text


def directus_mapping_for(product_name: str, product_slug: str | None = None) -> dict | None:
    """Lookup do produto Kiwify -> config Directus.

    Tenta primeiro pelo slug do webhook; depois pelo nome slugificado.
    """
    if product_slug:
        v = PRODUCT_TO_DIRECTUS.get(product_slug.lower())
        if v:
            return v
    slug = slugify_product(product_name)
    # 'kommo-master-flow' == 'kommo-masterflow' como alias historico
    return PRODUCT_TO_DIRECTUS.get(slug) or PRODUCT_TO_DIRECTUS.get(slug.replace("-master-", "-master"))
