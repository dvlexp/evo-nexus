"""Persistencia idempotente das execucoes do orquestrador.

Tabelas:
    - public.kiwify_orders             (idempotency PK = kiwify_order_id)
    - public.kiwify_post_sale_runs     (1 linha por sub_step por sale_id)

Wrapper sobre dashboard.backend.integrations.aurora_db (SSH+docker+psql).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from dashboard.backend.integrations.aurora_db import execute, query


SUB_STEPS = ("evocrm_sync", "whatsapp_confirm", "mautic_tag", "directus_provision")

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_DRY_RUN = "dry_run"


def upsert_order(payload: dict) -> bool:
    """Insert ou no-op se ja existe (idempotencia por kiwify_order_id).

    Retorna True se a linha foi nova (insert), False se ja existia (no-op).
    """
    sale_id = payload.get("kiwify_order_id") or payload.get("order_id") or payload.get("id")
    if not sale_id:
        raise ValueError("Payload sem kiwify_order_id / order_id / id")

    customer = payload.get("Customer") or payload.get("customer") or {}
    product = payload.get("Product") or payload.get("product") or {}
    commissions = payload.get("Commissions") or payload.get("commissions") or {}

    rows = query(
        """
        INSERT INTO kiwify_orders (
            kiwify_order_id, customer_email, customer_name, customer_phone,
            product_id, product_name, gross_amount, net_amount, currency,
            payment_method, status, raw_payload
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s::jsonb
        )
        ON CONFLICT (kiwify_order_id) DO NOTHING
        RETURNING kiwify_order_id
        """,
        (
            sale_id,
            (customer.get("email") or "").lower().strip(),
            customer.get("full_name") or customer.get("name") or "",
            customer.get("mobile") or customer.get("phone") or "",
            product.get("product_id") or product.get("id") or "",
            product.get("product_name") or product.get("name") or "",
            float(commissions.get("charge_amount") or payload.get("amount") or 0) / 100.0 if isinstance(commissions.get("charge_amount"), int) else (commissions.get("charge_amount") or payload.get("amount") or 0),
            float(commissions.get("my_commission") or 0) / 100.0 if isinstance(commissions.get("my_commission"), int) else (commissions.get("my_commission") or 0),
            payload.get("currency") or commissions.get("currency") or "BRL",
            payload.get("payment_method") or "",
            payload.get("order_status") or payload.get("status") or "",
            json.dumps(payload, ensure_ascii=False, default=str),
        ),
    )
    return bool(rows)


def start_run(sale_id: str, sub_step: str, dry_run: bool = False) -> bool:
    """Marca um sub_step como running. Idempotente (uniq sale_id,sub_step).

    Retorna True se quem invocou pegou o lock (nova linha OU linha existente
    em status que admite re-execucao). Retorna False se ja esta ok ou running
    (outro processo).
    """
    # Insert nova linha; ON CONFLICT -> update se status nao ok
    rows = query(
        """
        INSERT INTO kiwify_post_sale_runs (sale_id, sub_step, status, attempt, started_at)
        VALUES (%s, %s, %s, 1, now())
        ON CONFLICT (sale_id, sub_step) DO UPDATE
        SET status     = CASE
                            WHEN kiwify_post_sale_runs.status IN ('ok', 'skipped') THEN kiwify_post_sale_runs.status
                            ELSE EXCLUDED.status
                         END,
            attempt    = CASE
                            WHEN kiwify_post_sale_runs.status IN ('ok', 'skipped') THEN kiwify_post_sale_runs.attempt
                            ELSE kiwify_post_sale_runs.attempt + 1
                         END,
            started_at = CASE
                            WHEN kiwify_post_sale_runs.status IN ('ok', 'skipped') THEN kiwify_post_sale_runs.started_at
                            ELSE now()
                         END
        RETURNING status, attempt
        """,
        (sale_id, sub_step, STATUS_DRY_RUN if dry_run else STATUS_RUNNING),
    )
    if not rows:
        return False
    return rows[0]["status"] not in (STATUS_OK, STATUS_SKIPPED)


def finish_run(
    sale_id: str,
    sub_step: str,
    status: str,
    result: Optional[dict] = None,
    error: Optional[str] = None,
) -> None:
    execute(
        """
        UPDATE kiwify_post_sale_runs
           SET status        = %s,
               result        = %s::jsonb,
               error_message = %s,
               finished_at   = now()
         WHERE sale_id = %s AND sub_step = %s
        """,
        (
            status,
            json.dumps(result or {}, ensure_ascii=False, default=str),
            error,
            sale_id,
            sub_step,
        ),
    )


def get_runs(sale_id: str) -> dict[str, dict]:
    """Retorna {sub_step: {status, result, error_message, attempt}}."""
    rows = query(
        """
        SELECT sub_step, status, attempt, error_message, result
          FROM kiwify_post_sale_runs
         WHERE sale_id = %s
        """,
        (sale_id,),
    )
    return {r["sub_step"]: r for r in rows}


def is_step_ok(sale_id: str, sub_step: str) -> bool:
    rows = query(
        "SELECT status FROM kiwify_post_sale_runs WHERE sale_id=%s AND sub_step=%s",
        (sale_id, sub_step),
    )
    return bool(rows) and rows[0]["status"] in (STATUS_OK, STATUS_SKIPPED)
