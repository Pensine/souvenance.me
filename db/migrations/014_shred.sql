-- Real erasure in an append-only log: crypto-shredding.
--
-- With PENSINE_SHRED=1, each new deposit is sealed under the key of its
-- scope (one deposit, or one subject); keys live outside the database
-- (PENSINE_KEYS_DIR), hence outside dumps. Forgetting a scope = purging its
-- projections (memories, graph, media…) then destroying its key: the events
-- row remains, unreadable. See pensine/shred.py.
--
-- This table holds NO key and no subject label: only the opaque identifier
-- of a scope and the date it was forgotten.
-- Without effect while the flag is off: no existing row changes.
CREATE TABLE IF NOT EXISTS shred_scopes (
    id TEXT PRIMARY KEY,             -- 'depot_<hex>' | 'sujet_<condensé>'
    kind TEXT NOT NULL,              -- 'depot' | 'sujet'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    forgotten_at TIMESTAMPTZ         -- non-NULL: key destroyed
);

-- find the deposits of a scope without scanning the whole log
CREATE INDEX IF NOT EXISTS events_portee_idx ON events ((payload #>> '{_scelle,portee}'))
    WHERE payload ? '_scelle';

-- Raw candidates of each night, BEFORE the evidence cascade: what the model
-- proposed, kept or not. They alone make it possible to replay a real night
-- under several severities (scripts/integrity_report.py, recall / invention
-- frontier). With PENSINE_SHRED=1, each row is sealed in layers under the key
-- of each of its deposits: forgetting any one is enough. Bounded retention
-- (PENSINE_CANDIDATES_RETENTION_DAYS, 365 by default; 0 = keep nothing).
-- Only counts come out of it.
CREATE TABLE IF NOT EXISTS night_candidates (
    id BIGSERIAL PRIMARY KEY,
    night_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    batch_event_ids BIGINT[] NOT NULL,     -- the deposits shown to the model tonight
    source_event_ids BIGINT[] NOT NULL,    -- those the candidate cites (∩ batch)
    issue TEXT,                            -- outcome of the cascade (codes from evidence.verify)
    payload JSONB NOT NULL                 -- the candidate, sealed if PENSINE_SHRED=1
);
CREATE INDEX IF NOT EXISTS night_candidates_night_idx ON night_candidates(night_at);
