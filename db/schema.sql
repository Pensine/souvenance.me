-- JUMEAU — SQL schema v1 (appendix A of the founding document)
-- Note: `media` is created before `events` (events.media_id references it).

CREATE EXTENSION IF NOT EXISTS vector;

-- Pensine: raw media — THE ORIGINAL FILE IS KEPT FOREVER
-- (the transcript is only a search index attached to the file)
CREATE TABLE media (
    id BIGSERIAL PRIMARY KEY,
    captured_at TIMESTAMPTZ NOT NULL,
    kind TEXT NOT NULL,            -- 'audio','photo','video','pdf'
    storage_path TEXT NOT NULL,    -- raw file, encrypted, never modified
    duration_s INT,
    transcript TEXT,               -- WhisperX (word-level aligned)
    speakers JSONB,                -- pyannote/ECAPA: [{segment, entity_id|'unknown'}]
    exif JSONB,                    -- photos: date, GPS
    description TEXT               -- images/keyframes: Claude Code vision
);

-- Layer 0: the substrate (append-only, never UPDATE/DELETE)
CREATE TABLE events (
    id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source TEXT NOT NULL,          -- 'conversation','calendar','mail','sport_tracker','daily_log','pensieve'
    kind TEXT NOT NULL,            -- 'message','meeting','activity','decision','deposit',...
    payload JSONB NOT NULL,        -- raw content, reprocessed by the perceiver
    media_id BIGINT REFERENCES media(id),
    hash TEXT NOT NULL             -- integrity / deduplication
);
CREATE UNIQUE INDEX events_hash_idx ON events(hash);
CREATE INDEX events_occurred_at_idx ON events(occurred_at);
CREATE INDEX events_source_idx ON events(source);

-- Append-only guard: no UPDATE/DELETE on the event log
CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'events is append-only (layer 0): % is forbidden', TG_OP;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER events_append_only
    BEFORE UPDATE OR DELETE ON events
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- Layer 1: derived memories (recomputable projections of events)
CREATE TABLE memories (
    id BIGSERIAL PRIMARY KEY,
    type TEXT NOT NULL,            -- 'episodic','semantic','procedural','reflection'
    content TEXT NOT NULL,
    embedding VECTOR(768),         -- nomic-embed-text-v1.5 (BGE-M3 : 1024)
    confidence REAL NOT NULL,      -- metacognition: calibrated, never implicit
    importance REAL NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,          -- NULL = still true; time is native
    source_event_ids BIGINT[],     -- full traceability
    access_count INT DEFAULT 0,
    last_accessed_at TIMESTAMPTZ,  -- for active forgetting
    superseded_by BIGINT REFERENCES memories(id)  -- reconsolidation
);
CREATE INDEX memories_type_idx ON memories(type);
CREATE INDEX memories_valid_idx ON memories(valid_from, valid_to);

-- Minimal temporal graph (triples)
CREATE TABLE entities (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL             -- 'person','place','project','organization','belief'
);
CREATE TABLE relations (
    id BIGSERIAL PRIMARY KEY,
    subject_id BIGINT REFERENCES entities(id),
    predicate TEXT NOT NULL,
    object_id BIGINT REFERENCES entities(id),
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,
    source_event_ids BIGINT[]
);

-- Layer 3: the persona lives in Git (markdown files); here, the pointer
CREATE TABLE persona_versions (
    id BIGSERIAL PRIMARY KEY,
    git_commit TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ratified_by_user BOOLEAN NOT NULL DEFAULT false  -- the user is the final author
);

-- Prediction-error loop (phase 3)
CREATE TABLE predictions (
    id BIGSERIAL PRIMARY KEY,
    context TEXT NOT NULL,         -- 'draft_email','decision','calibration_question'
    predicted TEXT NOT NULL,
    actual TEXT,
    error_score REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Temporal engine: landmarks (human coordinates of time)
CREATE TABLE landmarks (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,            -- 'UTMB 2027','moving house','start of chapter X'
    at_date DATE NOT NULL,
    kind TEXT NOT NULL,            -- 'race','life_event','chapter_start','chapter_end'
    cycle TEXT                     -- 'saison_trail','annuel',... if recurring
);

-- Temporal engine: prospective memory (remembering the future)
CREATE TABLE intentions (
    id BIGSERIAL PRIMARY KEY,
    content TEXT NOT NULL,         -- 'try the backyard sleep strategy'
    trigger_kind TEXT NOT NULL,    -- 'date','delta_landmark','topic'
    trigger_value TEXT NOT NULL,   -- '2026-10-15' | 'J-30:backyard_2026' | 'immobilier'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    surfaced_at TIMESTAMPTZ,       -- resurfaces in context, never as a notification
    resolved_at TIMESTAMPTZ
);

-- Layer 7: audit
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor TEXT NOT NULL,           -- 'consolidation','mcp','governor'
    action TEXT NOT NULL,
    detail JSONB
);
