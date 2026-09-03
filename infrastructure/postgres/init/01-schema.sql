-- CausalGuard demo schema: an `orders` table the reliability scenarios act on.
-- Runs once on first container start (docker-entrypoint-initdb.d).

\set ON_ERROR_STOP on

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
CREATE INDEX IF NOT EXISTS orders_status_idx      ON orders (status);
CREATE INDEX IF NOT EXISTS orders_created_at_idx  ON orders (created_at);

-- Seed ~250k rows so table/index sizes and scan costs are meaningful.
INSERT INTO orders (customer_id, status, total_cents, payload, created_at)
SELECT
    (random() * 50000)::bigint,
    (ARRAY['pending','paid','shipped','refunded','cancelled'])[1 + (random() * 4)::int],
    (random() * 250000)::bigint,
    jsonb_build_object('sku', 'SKU-' || (random() * 9999)::int, 'qty', 1 + (random() * 5)::int),
    now() - (random() * interval '90 days')
FROM generate_series(1, 250000);

ANALYZE orders;
