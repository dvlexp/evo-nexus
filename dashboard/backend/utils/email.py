"""Normalizacao de email para o pipeline outbound RXP.

Lowercase + trim + validacao regex basica (RFC 5322 simplificada).
Foco: garantir match com Mautic e Kiwify nos joins de atribuicao.
"""

from __future__ import annotations

import re
from typing import Optional

_EMAIL_RE = re.compile(
    r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,63}$"
)


def normalize(raw: Optional[str]) -> Optional[str]:
    """Lowercase + trim + validacao basica. None se invalido."""
    if not raw:
        return None
    value = str(raw).strip().lower()
    if not value:
        return None
    if not _EMAIL_RE.match(value):
        return None
    return value


def is_valid(value: Optional[str]) -> bool:
    return normalize(value) is not None
