"""Cliente Postgres para o banco rxp_outbound (VPS RXP / pgvector swarm).

A VPS roda Postgres dentro de um container Docker Swarm em rede interna
(rxpnet, 10.0.1.6), sem porta publica. Por isso usamos SSH + docker exec
psql como transporte. E feio, mas e o mesmo padrao ja usado pela skill
`n8n-deploy` da Bolt memory (project_n8n_deploy.md).

Para producao real, expor a porta 5432 via Docker stack ou criar tunnel
SSH dedicado seria o caminho.

Uso:

    from dashboard.backend.integrations.aurora_db import execute, query

    # SELECT (retorna lista de dicts)
    rows = query("SELECT id, cnpj FROM rxp_outbound_leads WHERE vertical=%s",
                 ("advocacia",))

    # INSERT / UPDATE / DELETE
    execute(
        "INSERT INTO rxp_outbound_leads (cnpj, razao_social, vertical) "
        "VALUES (%s, %s, %s) ON CONFLICT (cnpj) DO NOTHING",
        ("12345678000190", "Foo Bar Ltda", "advocacia"),
    )
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional

log = logging.getLogger(__name__)

# Configuracoes de transporte. Sobrescrever via env se necessario.
SSH_HOST = os.environ.get("RXP_SSH_HOST", "195.200.7.36")
SSH_PORT = os.environ.get("RXP_SSH_PORT", "2222")
SSH_USER = os.environ.get("RXP_SSH_USER", "root")
SSH_KEY = os.environ.get("RXP_SSH_KEY", os.path.expanduser("~/.ssh/vps_rxp_claude"))
PG_CONTAINER = os.environ.get(
    "RXP_PG_CONTAINER",
    "pgvector_pgvector.1.94c93dmmpbvy5zswpqoaz0mae",
)
PG_USER = os.environ.get("RXP_PG_USER", "postgres")
PG_DB = os.environ.get("RXP_PG_DB", "rxp_outbound")


class AuroraDBError(Exception):
    pass


def _ssh_base() -> list[str]:
    return [
        "ssh",
        "-i", SSH_KEY,
        "-p", SSH_PORT,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{SSH_USER}@{SSH_HOST}",
    ]


def _quote_param(value: Any) -> str:
    """Quote estilo psql E'...' para passar via -c quando necessario.

    Nao usado no fluxo principal (preferimos arquivo via stdin), mas
    util para queries ad-hoc.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        return _quote_param(json.dumps(value, ensure_ascii=False))
    s = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"E'{s}'"


def _render_sql(sql: str, params: Optional[Iterable[Any]] = None) -> str:
    """Substitui placeholders %s pelos parametros, com quoting seguro.

    Mantemos o estilo psycopg2 (%s) para que seja simples migrar para
    libpq direta quando a porta for exposta.
    """
    if not params:
        return sql
    out = []
    iter_params = iter(params)
    i = 0
    while i < len(sql):
        if sql[i:i+2] == "%s":
            try:
                val = next(iter_params)
            except StopIteration:
                raise AuroraDBError("Nao ha parametros suficientes para os placeholders %s")
            out.append(_quote_param(val))
            i += 2
        else:
            out.append(sql[i])
            i += 1
    return "".join(out)


def _run_psql(sql: str, json_output: bool = False) -> str:
    """Roda SQL via ssh + docker exec psql. Retorna stdout (string)."""
    # Estrategia: gravar SQL em /tmp via heredoc base64 para evitar quoting hell.
    import base64
    encoded = base64.b64encode(sql.encode("utf-8")).decode("ascii")
    tmpfile = f"/tmp/aurora_q_{uuid.uuid4().hex}.sql"

    remote_cmd = (
        f"echo {encoded} | base64 -d > {tmpfile} && "
        f"docker cp {tmpfile} {PG_CONTAINER}:{tmpfile} && "
        f"docker exec {PG_CONTAINER} psql -U {PG_USER} -d {PG_DB} "
        f"{'-At -F\"\\t\"' if not json_output else '-At'} "
        f"-v ON_ERROR_STOP=1 -f {tmpfile}; "
        f"rm -f {tmpfile}"
    )

    cmd = _ssh_base() + [remote_cmd]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise AuroraDBError(
            f"psql falhou (exit {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


def execute(sql: str, params: Optional[Iterable[Any]] = None) -> None:
    """Executa um statement DML. Sem retorno."""
    rendered = _render_sql(sql, params)
    _run_psql(rendered)


def query(sql: str, params: Optional[Iterable[Any]] = None) -> list[dict]:
    """Executa SELECT (ou DML com RETURNING) e retorna lista de dicts.

    Para DML com RETURNING, usa CTE `WITH q AS (...) SELECT json_agg(q)`,
    o que preserva a side-effect do INSERT/UPDATE/DELETE.
    """
    rendered = _render_sql(sql, params).rstrip(";").strip()

    upper = rendered.lstrip("(").upper()
    is_dml_returning = (
        upper.startswith(("INSERT", "UPDATE", "DELETE")) and "RETURNING" in upper
    )

    if is_dml_returning:
        wrapped = (
            "WITH q AS (\n" + rendered + "\n) "
            "SELECT COALESCE(json_agg(q), '[]'::json) FROM q;"
        )
    else:
        wrapped = (
            "SELECT COALESCE(json_agg(t), '[]'::json) FROM (\n"
            f"{rendered}"
            "\n) t;"
        )

    raw = _run_psql(wrapped, json_output=True).strip()
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuroraDBError(f"Resposta nao-JSON do psql: {raw[:200]} ({exc})")


def log_outbound_event(
    lead_id: str,
    event_type: str,
    channel: Optional[str] = None,
    template_or_email_id: Optional[str] = None,
    cadence_day: Optional[int] = None,
    campaign_id: Optional[str] = None,
    vertical: Optional[str] = None,
    sale_attribution: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Helper unificado para gravar eventos do funil em rxp_outbound_events.

    Idempotente para tipos 'wa_sent'/'email_sent' graças ao UNIQUE
    parcial em (lead_id, event_type, template_or_email_id).

    Usado por:
        - DISCOVERY (event_type='discovered')
        - INGEST (event_type='ingested' / 'queued')
        - DISPATCH WA (event_type='wa_sent' apos POST WABA)
        - EMAIL (event_type='email_sent' apos POST Mautic)
        - Webhooks Mautic (event_type='email_opened' / 'email_clicked')
        - Webhook Cal.com (event_type='meeting_booked')
        - Webhook Kiwify (event_type='sale_won')
    """
    execute(
        """
        INSERT INTO rxp_outbound_events
            (lead_id, event_type, channel, template_or_email_id,
             cadence_day, campaign_id, vertical, sale_attribution, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT DO NOTHING
        """,
        (
            lead_id,
            event_type,
            channel,
            template_or_email_id,
            cadence_day,
            campaign_id,
            vertical,
            sale_attribution,
            json.dumps(metadata or {}, ensure_ascii=False),
        ),
    )
