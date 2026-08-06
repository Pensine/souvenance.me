-- JUMEAU — Schéma SQL v1 (annexe A du document fondateur)
-- Note : `media` est créée avant `events` (events.media_id la référence).

CREATE EXTENSION IF NOT EXISTS vector;

-- Pensine : médias bruts — LE FICHIER ORIGINAL EST CONSERVÉ POUR TOUJOURS
-- (le transcript n'est qu'un index de recherche accroché au fichier)
CREATE TABLE media (
    id BIGSERIAL PRIMARY KEY,
    captured_at TIMESTAMPTZ NOT NULL,
    kind TEXT NOT NULL,            -- 'audio','photo','video','pdf'
    storage_path TEXT NOT NULL,    -- fichier brut, chiffré, jamais modifié
    duration_s INT,
    transcript TEXT,               -- WhisperX (aligné mot-à-mot)
    speakers JSONB,                -- pyannote/ECAPA : [{segment, entity_id|'unknown'}]
    exif JSONB,                    -- photos : date, GPS
    description TEXT               -- images/keyframes : vision Claude Code
);

-- Couche 0 : le substrat (append-only, jamais de UPDATE/DELETE)
CREATE TABLE events (
    id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source TEXT NOT NULL,          -- 'conversation','calendar','mail','sport_tracker','daily_log','pensieve'
    kind TEXT NOT NULL,            -- 'message','meeting','activity','decision','deposit',...
    payload JSONB NOT NULL,        -- contenu brut retraité par le percepteur
    media_id BIGINT REFERENCES media(id),
    hash TEXT NOT NULL             -- intégrité / déduplication
);
CREATE UNIQUE INDEX events_hash_idx ON events(hash);
CREATE INDEX events_occurred_at_idx ON events(occurred_at);
CREATE INDEX events_source_idx ON events(source);

-- Garde-fou append-only : aucun UPDATE/DELETE sur le log d'événements
CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'events est append-only (couche 0) : % interdit', TG_OP;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER events_append_only
    BEFORE UPDATE OR DELETE ON events
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- Couche 1 : mémoires dérivées (projections recalculables des events)
CREATE TABLE memories (
    id BIGSERIAL PRIMARY KEY,
    type TEXT NOT NULL,            -- 'episodic','semantic','procedural','reflection'
    content TEXT NOT NULL,
    embedding VECTOR(768),         -- nomic-embed-text-v1.5 (BGE-M3 : 1024)
    confidence REAL NOT NULL,      -- métacognition : calibrée, jamais implicite
    importance REAL NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,          -- NULL = encore vrai ; le temps est natif
    source_event_ids BIGINT[],     -- traçabilité totale
    access_count INT DEFAULT 0,
    last_accessed_at TIMESTAMPTZ,  -- pour l'oubli actif
    superseded_by BIGINT REFERENCES memories(id)  -- reconsolidation
);
CREATE INDEX memories_type_idx ON memories(type);
CREATE INDEX memories_valid_idx ON memories(valid_from, valid_to);

-- Graphe temporel minimal (triplets)
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

-- Couche 3 : le persona vit dans Git (fichiers markdown) ; ici, le pointeur
CREATE TABLE persona_versions (
    id BIGSERIAL PRIMARY KEY,
    git_commit TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ratified_by_user BOOLEAN NOT NULL DEFAULT false  -- l'utilisateur est l'auteur final
);

-- Boucle prédiction-erreur (phase 3)
CREATE TABLE predictions (
    id BIGSERIAL PRIMARY KEY,
    context TEXT NOT NULL,         -- 'draft_email','decision','calibration_question'
    predicted TEXT NOT NULL,
    actual TEXT,
    error_score REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Moteur temporel : jalons (coordonnées humaines du temps)
CREATE TABLE landmarks (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,            -- 'UTMB 2027','déménagement','début chapitre X'
    at_date DATE NOT NULL,
    kind TEXT NOT NULL,            -- 'race','life_event','chapter_start','chapter_end'
    cycle TEXT                     -- 'saison_trail','annuel',... si récurrent
);

-- Moteur temporel : mémoire prospective (se souvenir du futur)
CREATE TABLE intentions (
    id BIGSERIAL PRIMARY KEY,
    content TEXT NOT NULL,         -- 'tester la stratégie de sommeil backyard'
    trigger_kind TEXT NOT NULL,    -- 'date','delta_landmark','topic'
    trigger_value TEXT NOT NULL,   -- '2026-10-15' | 'J-30:backyard_2026' | 'immobilier'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    surfaced_at TIMESTAMPTZ,       -- refait surface en contexte, jamais en notification
    resolved_at TIMESTAMPTZ
);

-- Couche 7 : audit
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor TEXT NOT NULL,           -- 'consolidation','mcp','governor'
    action TEXT NOT NULL,
    detail JSONB
);
