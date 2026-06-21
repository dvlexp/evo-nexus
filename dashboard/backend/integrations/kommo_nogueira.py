"""Kommo CRM client para a conta Nogueira Resolve (nogueiraresolveadv.kommo.com).

Fornece find_lead_by_phone() e add_lead_note() com retry exponencial.
Credenciais lidas de env vars definidas em .env:
  NOGUEIRA_KOMMO_TOKEN      — long-lived JWT (válido até 2031)
  NOGUEIRA_KOMMO_BASE_URL   — https://nogueiraresolveadv.kommo.com
  NOGUEIRA_KOMMO_ACCOUNT_ID — 35241960
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL = os.getenv("NOGUEIRA_KOMMO_BASE_URL", "https://nogueiraresolveadv.kommo.com")
_TOKEN = os.getenv("NOGUEIRA_KOMMO_TOKEN", "")
_ACCOUNT_ID = os.getenv("NOGUEIRA_KOMMO_ACCOUNT_ID", "35241960")

_HEADERS = {
    "Authorization": f"Bearer {_TOKEN}",
    "Content-Type": "application/json",
}

_MAX_RETRIES = 3
_BACKOFF_BASE = 1.5


def _normalize_phone(phone: str) -> str:
    """Remove todos os caracteres não numéricos do telefone."""
    return re.sub(r"\D", "", phone)


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    delay = 1.0
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.request(method, url, headers=_HEADERS, timeout=15, **kwargs)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", delay))
                logger.warning("Kommo rate limit, aguardando %ss", retry_after)
                time.sleep(retry_after)
                delay *= _BACKOFF_BASE
                continue
            return resp
        except requests.RequestException as exc:
            if attempt == _MAX_RETRIES - 1:
                raise
            logger.warning("Kommo request falhou (tentativa %d/%d): %s", attempt + 1, _MAX_RETRIES, exc)
            time.sleep(delay)
            delay *= _BACKOFF_BASE
    raise RuntimeError("Máximo de tentativas atingido")


def find_lead_by_phone(phone: str) -> Optional[dict]:
    """Busca o lead mais recente no Kommo pelo número de telefone.

    Retorna o lead (dict) se encontrado, None caso contrário.
    O número é normalizado (apenas dígitos) antes da busca.
    """
    digits = _normalize_phone(phone)
    if not digits:
        logger.warning("Telefone inválido: %r", phone)
        return None

    url = f"{_BASE_URL}/api/v4/contacts"
    resp = _request_with_retry("GET", url, params={"query": digits, "limit": 5})
    if resp.status_code == 204:
        logger.debug("Nenhum contato encontrado para %s", digits)
        return None
    if not resp.ok:
        logger.error("Erro ao buscar contato no Kommo: %d %s", resp.status_code, resp.text[:200])
        return None

    data = resp.json()
    contacts = data.get("_embedded", {}).get("contacts", [])
    if not contacts:
        return None

    contact = contacts[0]
    contact_id = contact["id"]

    # Busca leads associados ao contato
    leads_url = f"{_BASE_URL}/api/v4/contacts/{contact_id}/links"
    lresp = _request_with_retry("GET", leads_url)
    if not lresp.ok:
        logger.warning("Não foi possível buscar leads do contato %d", contact_id)
        return None

    links_data = lresp.json()
    lead_links = [
        lnk for lnk in links_data.get("_embedded", {}).get("links", [])
        if lnk.get("to_entity_type") == "leads"
    ]
    if not lead_links:
        logger.debug("Contato %d não tem leads vinculados", contact_id)
        return None

    lead_id = lead_links[0]["to_entity_id"]

    # Busca detalhes do lead
    lead_resp = _request_with_retry("GET", f"{_BASE_URL}/api/v4/leads/{lead_id}")
    if not lead_resp.ok:
        logger.error("Erro ao buscar lead %d: %d", lead_id, lead_resp.status_code)
        return None

    lead = lead_resp.json()
    logger.info("Lead encontrado para %s: id=%d nome=%r", digits, lead["id"], lead.get("name"))
    return lead


def add_lead_note(lead_id: int, text: str, note_type: str = "common") -> bool:
    """Adiciona uma nota a um lead do Kommo.

    Retorna True em caso de sucesso, False em caso de erro.
    """
    url = f"{_BASE_URL}/api/v4/leads/{lead_id}/notes"
    payload = [{"note_type": note_type, "params": {"text": text[:10000]}}]
    resp = _request_with_retry("POST", url, json=payload)
    if not resp.ok:
        logger.error("Erro ao criar nota no lead %d: %d %s", lead_id, resp.status_code, resp.text[:200])
        return False
    logger.info("Nota adicionada ao lead %d", lead_id)
    return True
