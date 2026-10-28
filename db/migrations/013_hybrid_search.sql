-- Full-text search, to merge with vector search.
--
-- The vector finds what RESEMBLES the question; it misses what NAMES it: a
-- first name, a place, a number, a rare word. Before, recall did one OR the
-- other (full-text was only an ILIKE fallback when embeddings were missing).
-- Now both run and are merged (pensine/retrieval.py).
--
-- 'simple' configuration + unaccent, and not 'french' or 'english':
--   · the corpus is mixed (memos in French, memos and conversations in
--     English, often on the same day); a stemmer applies the rules of its
--     language to the other and produces false stems, and the language of a
--     memory is not stored anywhere;
--   · what the vector misses is mostly proper names and rare words, which
--     stemmers do not help with;
--   · unaccent: « ete » finds « été », « Chambery » finds « Chambéry ».
-- Stop words are filtered on the query side (FR + EN), and word weight is
-- computed on the fly (IDF): a first name present everywhere weighs nothing,
-- a rare word weighs a lot.
CREATE EXTENSION IF NOT EXISTS unaccent;

-- unaccent() is not IMMUTABLE (it depends on the current dictionary): a
-- generated column requires it. The dictionary is therefore named explicitly.
CREATE OR REPLACE FUNCTION pensine_unaccent(text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
    AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$;

ALTER TABLE memories ADD COLUMN IF NOT EXISTS content_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('simple', pensine_unaccent(content))) STORED;

CREATE INDEX IF NOT EXISTS memories_content_tsv_idx ON memories USING GIN (content_tsv);
