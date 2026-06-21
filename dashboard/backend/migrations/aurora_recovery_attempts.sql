-- Aurora Recovery Agent — schema + tables
-- DB alvo: evocrm (mesmo container pgvector da VPS RXP)
-- Schema dedicado: aurora
-- Owner: Bolt | Feature: aurora-recovery-agent | Phase: Build (Passo 1)

CREATE SCHEMA IF NOT EXISTS aurora;

-- Tabela principal de controle de tentativas de retomada.
-- Idempotencia via unique (conversation_id, attempt_number).
CREATE TABLE IF NOT EXISTS aurora.rxp_aurora_recovery_attempts (
    id                    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id       uuid        NOT NULL,
    contact_id            uuid        NOT NULL,
    attempt_number        int         NOT NULL CHECK (attempt_number BETWEEN 1 AND 3),
    template_name         text        NOT NULL,
    template_variables    jsonb       NOT NULL DEFAULT '{}'::jsonb,
    scheduled_for         timestamptz NOT NULL,
    sent_at               timestamptz,
    status                text        NOT NULL DEFAULT 'scheduled'
                                       CHECK (status IN ('scheduled','sent','responded','cancelled','failed','completed')),
    nicho_detectado       text,
    company_source        text,
    response_received_at  timestamptz,
    error_message         text,
    created_at            timestamptz NOT NULL DEFAULT NOW(),
    updated_at            timestamptz NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_recovery_attempt UNIQUE (conversation_id, attempt_number)
);

CREATE INDEX IF NOT EXISTS ix_recovery_status_scheduled
    ON aurora.rxp_aurora_recovery_attempts (status, scheduled_for);
CREATE INDEX IF NOT EXISTS ix_recovery_conversation
    ON aurora.rxp_aurora_recovery_attempts (conversation_id);
CREATE INDEX IF NOT EXISTS ix_recovery_contact
    ON aurora.rxp_aurora_recovery_attempts (contact_id);

-- Trigger trivial de updated_at
CREATE OR REPLACE FUNCTION aurora.touch_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_recovery_touch ON aurora.rxp_aurora_recovery_attempts;
CREATE TRIGGER trg_recovery_touch BEFORE UPDATE ON aurora.rxp_aurora_recovery_attempts
    FOR EACH ROW EXECUTE FUNCTION aurora.touch_updated_at();

-- Cache de empresa por dominio de email (usado por Passo 0 e fallback runtime).
CREATE TABLE IF NOT EXISTS aurora.rxp_domain_company_cache (
    domain       text        PRIMARY KEY,
    company_name text,
    source       text        NOT NULL CHECK (source IN ('cnpja','mautic','calcom','none')),
    raw          jsonb,
    fetched_at   timestamptz NOT NULL DEFAULT NOW(),
    expires_at   timestamptz NOT NULL DEFAULT (NOW() + INTERVAL '30 days')
);

CREATE INDEX IF NOT EXISTS ix_domain_cache_expiry
    ON aurora.rxp_domain_company_cache (expires_at);
