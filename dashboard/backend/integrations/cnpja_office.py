"""Wrapper para CNPJa Office Search.

Decisao tecnica de @apex-architect (kiwify-post-sale §12):
fonte primaria de discovery para o outbound RXP. Quando CNPJA_API_KEY
nao esta configurado, o wrapper retorna um pool de mocks (5 CNPJs por
vertical) para que o pipeline rode em modo dev/teste sem falhar.

Doc oficial:
    https://docs.cnpja.com/  (endpoint /office com filtros)

Filtros aplicados conforme Nex (workspace/sales/rxp/[C]outbound-icp-filters.md §5):
    cnae_primario, situacao_cadastral, capital_social_min/max,
    qtd_socios_min/max, ufs_prioridade, data_abertura_max.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any, Optional

import requests

from dashboard.backend.utils.email import normalize as normalize_email
from dashboard.backend.utils.phone import to_e164

log = logging.getLogger(__name__)

CNPJA_BASE_URL = os.environ.get("CNPJA_BASE_URL", "https://api.cnpja.com")
CNPJA_API_KEY = os.environ.get("CNPJA_API_KEY", "").strip()

ICP_PROFILES = {
    "advocacia": {
        "cnae_primario": "6911-7/01",
        "ufs_priority": ["SP", "RJ", "MG", "PR", "SC", "RS", "DF"],
        "ufs_priority_2": ["GO", "BA", "PE", "CE"],
        "ufs_excluded": ["AM", "RR", "AP", "AC", "RO"],
        "capital_social_min": 10_000,
        "capital_social_max": 5_000_000,
        "qtd_socios_min": 2,
        "qtd_socios_max": 8,
        "funcionarios_max": 50,
        "data_abertura_max": "2024-06-17",
    },
    "contabilidade": {
        "cnae_primario": "6920-6/01",
        "ufs_priority": ["SP", "MG", "PR", "RS", "SC", "RJ", "DF", "GO"],
        "ufs_priority_2": ["BA", "PE", "CE", "MT", "MS"],
        "ufs_excluded": ["AM", "RR", "AP", "AC", "RO"],
        "capital_social_min": 10_000,
        "capital_social_max": 10_000_000,
        "qtd_socios_min": 2,
        "qtd_socios_max": 10,
        "funcionarios_max": 80,
        "data_abertura_max": "2024-06-17",
    },
}


def _build_params(vertical: str, limit: int) -> dict[str, Any]:
    """Monta querystring para o endpoint /office da CNPJa."""
    icp = ICP_PROFILES[vertical]
    return {
        "primary_activity.id": icp["cnae_primario"].replace("-", "").replace("/", ""),
        "status.id": 2,  # ATIVA
        "capital.gte": icp["capital_social_min"],
        "capital.lte": icp["capital_social_max"],
        "members.gte": icp["qtd_socios_min"],
        "members.lte": icp["qtd_socios_max"],
        "founded.lte": icp["data_abertura_max"],
        "address.state.in": ",".join(icp["ufs_priority"]),
        "limit": limit,
    }


def _make_mock_leads(vertical: str, count: int) -> list[dict]:
    """Gera leads sinteticos para teste local sem chave CNPJa."""
    base_cnpjs = {
        "advocacia": [
            ("11222333000181", "Silva e Souza Advogados Associados",  "SP", "Sao Paulo"),
            ("22333444000172", "Almeida Costa Sociedade de Advogados", "RJ", "Rio de Janeiro"),
            ("33444555000163", "Pereira Lima Advogados",                "MG", "Belo Horizonte"),
            ("44555666000154", "Oliveira Santos Advocacia",             "PR", "Curitiba"),
            ("55666777000145", "Ferreira Rocha Advogados",              "RS", "Porto Alegre"),
        ],
        "contabilidade": [
            ("66777888000136", "Contabilidade Sao Paulo Ltda",          "SP", "Sao Paulo"),
            ("77888999000127", "Escritorio Contabil Minas Ltda",        "MG", "Belo Horizonte"),
            ("88999000000118", "Contadores Associados Sul Ltda",        "PR", "Curitiba"),
            ("99000111000109", "Assessoria Contabil Rio Grande Ltda",   "RS", "Porto Alegre"),
            ("10111222000196", "ContaCerta Servicos Contabeis",         "SC", "Florianopolis"),
        ],
    }
    icp = ICP_PROFILES[vertical]
    pool = base_cnpjs[vertical][:count]
    out = []
    for cnpj, razao, uf, municipio in pool:
        out.append({
            "cnpj": cnpj,
            "razao_social": razao,
            "nome_fantasia": razao.split(" ")[0],
            "cnae_primario": icp["cnae_primario"],
            "uf": uf,
            "municipio": municipio,
            "num_socios": icp["qtd_socios_min"] + 1,
            "capital_social": icp["capital_social_min"] * 5,
            "funcionarios": 5,
            "telefone_e164": to_e164(f"11{cnpj[-9:]}"),
            "email": normalize_email(f"contato@{razao.split()[0].lower()}.com.br"),
            "data_abertura": "2020-01-15",
            "situacao_cadastral": "ATIVA",
            "website": None,
            "telefone_fixo_e164": None,
            "discovery_source": "cnpja_mock",
            "metadata": {"mock": True, "vertical": vertical},
        })
    return out


def _parse_office(raw: dict, vertical: str) -> dict:
    """Converte um item retornado pela CNPJa para o schema rxp_outbound_leads."""
    addr = raw.get("address") or {}
    activity = raw.get("primary_activity") or {}
    phones = raw.get("phones") or []
    emails = raw.get("emails") or []

    # Primeiro celular E.164, primeiro fixo se houver
    phone_e164 = None
    fixed_e164 = None
    for ph in phones:
        digits = f"{ph.get('area','')}{ph.get('number','')}".strip()
        e = to_e164(digits)
        if not e:
            continue
        # heuristica: 9 digitos pos-DDD = celular
        if len(digits) >= 11 and digits[2] == "9":
            phone_e164 = phone_e164 or e
        else:
            fixed_e164 = fixed_e164 or e

    primary_email = None
    for em in emails:
        v = em.get("address") if isinstance(em, dict) else em
        norm = normalize_email(v)
        if norm:
            primary_email = norm
            break

    return {
        "cnpj": (raw.get("taxId") or raw.get("cnpj") or "").replace(".", "").replace("/", "").replace("-", ""),
        "razao_social": raw.get("company", {}).get("name") if isinstance(raw.get("company"), dict) else raw.get("name"),
        "nome_fantasia": raw.get("alias") or raw.get("nome_fantasia"),
        "cnae_primario": activity.get("id") or activity.get("code"),
        "uf": addr.get("state"),
        "municipio": addr.get("city"),
        "num_socios": len(raw.get("members") or []),
        "capital_social": (raw.get("company") or {}).get("equity"),
        "funcionarios": (raw.get("company") or {}).get("employeeCount"),
        "telefone_e164": phone_e164,
        "email": primary_email,
        "data_abertura": raw.get("founded"),
        "situacao_cadastral": (raw.get("status") or {}).get("text"),
        "website": (raw.get("links") or [{}])[0].get("url") if raw.get("links") else None,
        "telefone_fixo_e164": fixed_e164,
        "discovery_source": "cnpja_office_search",
        "metadata": {"raw_keys": list(raw.keys())},
    }


def discover(vertical: str, limit: int = 10) -> list[dict]:
    """Roda Office Search para a vertical solicitada.

    Quando CNPJA_API_KEY nao esta setada: retorna mock (sem falhar).
    """
    if vertical not in ICP_PROFILES:
        raise ValueError(f"Vertical invalida: {vertical}")

    if not CNPJA_API_KEY:
        log.warning(
            "CNPJA_API_KEY ausente: retornando %d leads mock para vertical=%s",
            limit, vertical,
        )
        return _make_mock_leads(vertical, limit)

    params = _build_params(vertical, limit)
    headers = {"Authorization": CNPJA_API_KEY}
    try:
        resp = requests.get(
            f"{CNPJA_BASE_URL}/office",
            headers=headers,
            params=params,
            timeout=30,
        )
    except requests.RequestException as exc:
        log.error("CNPJa request falhou: %s. Caindo em mock.", exc)
        return _make_mock_leads(vertical, limit)

    if resp.status_code != 200:
        log.error(
            "CNPJa retornou %d: %s. Caindo em mock.",
            resp.status_code, resp.text[:300],
        )
        return _make_mock_leads(vertical, limit)

    body = resp.json()
    records = body.get("records") or body.get("data") or body.get("results") or body
    if not isinstance(records, list):
        log.error("CNPJa retornou formato inesperado: %s", type(records).__name__)
        return _make_mock_leads(vertical, limit)

    parsed = []
    for raw in records:
        try:
            parsed.append(_parse_office(raw, vertical))
        except Exception as exc:  # pragma: no cover
            log.warning("Falha ao parsear item CNPJa: %s", exc)
    return parsed
