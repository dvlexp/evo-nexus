"""Normalizacao E.164 para telefones brasileiros.

Cobre o gap critico de instrumentacao identificado pelo Dex:
o webhook Kiwify retorna telefones com formatos variados (com/sem DDI,
com/sem mascara, com/sem 9 prefixo). Para o JOIN com rxp_outbound_leads
funcionar (CAC / Outbound Revenue Contribution), os telefones precisam
estar em formato E.164 canonico (`+5511999999999`).
"""

from __future__ import annotations

import re
from typing import Optional

_DIGIT_RE = re.compile(r"\D+")

# DDDs validos no Brasil (lista basica, suficiente para validacao defensiva).
# Fonte: ANATEL / Plano de Numeracao Brasileiro.
_BR_DDDS = {
    11, 12, 13, 14, 15, 16, 17, 18, 19,
    21, 22, 24, 27, 28,
    31, 32, 33, 34, 35, 37, 38,
    41, 42, 43, 44, 45, 46, 47, 48, 49,
    51, 53, 54, 55,
    61, 62, 63, 64, 65, 66, 67, 68, 69,
    71, 73, 74, 75, 77, 79,
    81, 82, 83, 84, 85, 86, 87, 88, 89,
    91, 92, 93, 94, 95, 96, 97, 98, 99,
}


def to_e164(raw: Optional[str], default_country: str = "BR") -> Optional[str]:
    """Converte um numero arbitrario para E.164 (`+5511999999999`).

    Aceita:
        "(11) 99999-9999"        -> "+5511999999999"
        "11999999999"            -> "+5511999999999"
        "5511999999999"          -> "+5511999999999"
        "+55 11 99999-9999"      -> "+5511999999999"
        "1199999999"  (8 digitos no celular antigo) -> "+551199999999"

    Retorna None se:
        - raw vazio ou None
        - apos limpeza nao tem digitos suficientes (< 10)
        - DDD invalido (BR)
        - default_country != BR e nao temos regras locais

    Atualmente so suporta BR. Outros paises retornam None com warning.
    """
    if not raw:
        return None

    digits = _DIGIT_RE.sub("", str(raw))
    if not digits:
        return None

    if default_country != "BR":
        # nao suportado ainda
        return None

    # Remove zeros a esquerda (tronco antigo)
    digits = digits.lstrip("0")

    # Casos com DDI 55 ja presente
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]

    # Agora deve estar so com DDD + numero local
    if len(digits) < 10 or len(digits) > 11:
        return None

    ddd = int(digits[:2])
    if ddd not in _BR_DDDS:
        return None

    return f"+55{digits}"


def is_e164(value: Optional[str]) -> bool:
    if not value:
        return False
    return bool(re.fullmatch(r"\+\d{10,15}", value))
