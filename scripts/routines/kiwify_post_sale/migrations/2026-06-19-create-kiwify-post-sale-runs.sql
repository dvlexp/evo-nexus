-- Migration: Tabelas minimas para o orquestrador Kiwify Post-Sale (Fase 2)
-- Banco alvo: rxp_outbound (VPS RXP / pgvector)
-- Idempotencia + auditoria por sub-step
--
-- Como aplicar:
--   ssh -p 2222 root@195.200.7.36 \
--     "docker cp - pgvector_pgvector.1.94c93dmmpbvy5zswpqoaz0mae:/tmp/m.sql" \
--     < this_file
--   docker exec pgvector_pgvector.1.94c93dmmpbvy5zswpqoaz0mae \
--     psql -U postgres -d rxp_outbound -f /tmp/m.sql
--
-- ou via dashboard.backend.integrations.aurora_db.execute (ver scripts/routines/kiwify_post_sale/db.py)

BEGIN;

-- Tabela minima de pedidos Kiwify (idempotencia). Schema completo
-- (50+ campos do ADR §4) chega na Fase 1 do plano; aqui ficamos com
-- o minimo necessario para o orquestrador rodar e nao duplicar.
CREATE TABLE IF NOT EXISTS kiwify_orders (
    kiwify_order_id          text PRIMARY KEY,
    customer_email           text NOT NULL,
    customer_name            text,
    customer_phone           text,
    product_id               text,
    product_name             text,
    gross_amount             numeric(12,2),
    net_amount               numeric(12,2),
    currency                 text DEFAULT 'BRL',
    payment_method           text,
    status                   text,
    raw_payload              jsonb NOT NULL DEFAULT '{}'::jsonb,
    received_at              timestamptz NOT NULL DEFAULT now(),
    created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_kiwify_orders_email   ON kiwify_orders (customer_email);
CREATE INDEX IF NOT EXISTS idx_kiwify_orders_product ON kiwify_orders (product_id);

-- Tabela de runs por sub-step. Uma linha por (sale_id, sub_step).
-- Garante idempotencia atomica e permite retry/replay.
CREATE TABLE IF NOT EXISTS kiwify_post_sale_runs (
    id                       bigserial PRIMARY KEY,
    sale_id                  text NOT NULL,
    sub_step                 text NOT NULL,        -- evocrm_sync | whatsapp_confirm | mautic_tag | directus_provision
    status                   text NOT NULL,        -- pending | running | ok | failed | skipped | dry_run
    attempt                  int  NOT NULL DEFAULT 1,
    error_message            text,
    result                   jsonb DEFAULT '{}'::jsonb,
    started_at               timestamptz,
    finished_at              timestamptz,
    created_at               timestamptz NOT NULL DEFAULT now(),
    UNIQUE (sale_id, sub_step)
);

CREATE INDEX IF NOT EXISTS idx_kiwify_runs_sale   ON kiwify_post_sale_runs (sale_id);
CREATE INDEX IF NOT EXISTS idx_kiwify_runs_status ON kiwify_post_sale_runs (status);

COMMIT;
