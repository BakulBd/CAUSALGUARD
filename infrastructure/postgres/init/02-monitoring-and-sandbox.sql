-- Read-only monitoring role for the CausalGuard telemetry source, plus a
-- throwaway sandbox database for empirical intervention verification.

\set ON_ERROR_STOP on

-- 1. Least-privilege monitoring role (used by CAUSALGUARD_POSTGRES__DSN).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'causalguard_monitor') THEN
        CREATE ROLE causalguard_monitor LOGIN PASSWORD 'monitor_secret';
    END IF;
END
$$;

GRANT pg_monitor TO causalguard_monitor;
GRANT CONNECT ON DATABASE production_db TO causalguard_monitor;
GRANT USAGE ON SCHEMA public TO causalguard_monitor;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO causalguard_monitor;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO causalguard_monitor;

-- 2. Sandbox database (used by CAUSALGUARD_SANDBOX__DSN). It is a full copy of
--    the schema so VACUUM / ANALYZE / pg_terminate_backend can run for real
--    without ever touching the primary.
SELECT 'CREATE DATABASE sandbox_db OWNER causalguard'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'sandbox_db')\gexec

\connect sandbox_db

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

CREATE TABLE IF NOT EXISTS orders (
    id           bigserial PRIMARY KEY,
    customer_id  bigint       NOT NULL,
    status       text         NOT NULL DEFAULT 'pending',
    total_cents  bigint       NOT NULL DEFAULT 0,
    payload      jsonb        NOT NULL DEFAULT '{}'::jsonb,
    created_at   timestamptz  NOT NULL DEFAULT now(),
    updated_at   timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS orders_customer_id_idx ON orders (customer_id);

INSERT INTO orders (customer_id, status, total_cents)
SELECT (random() * 50000)::bigint, 'paid', (random() * 250000)::bigint
FROM generate_series(1, 40000);

-- Generate churn so the sandbox has dead tuples for VACUUM to reclaim.
UPDATE orders SET status = 'shipped', updated_at = now() WHERE id % 2 = 0;
UPDATE orders SET status = 'refunded', updated_at = now() WHERE id % 5 = 0;

ANALYZE orders;
