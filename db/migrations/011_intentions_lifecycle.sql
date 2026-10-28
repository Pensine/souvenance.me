-- What is coming: a "next step" becomes an intention, with a life of its own.
--
-- The intentions table only served time capsules. Projects mentioned in
-- passing ("next step: call Charles") ended up buried in a memory, undated,
-- invisible in "what is coming".
--
-- A step is born from a deposit (consolidation spots it), attaches to a
-- subject or a deadline, then closes: done, or abandoned, with its reason.
-- With no news for two months, it is "on hold" — a status computed at read
-- time, never a reminder: the rule of silence holds, an intention only comes
-- back when it is talked about or when the timeline is opened.
--
--   kind               'capsule' (sealed message, never shown before its date)
--                      or 'etape' (next step of a life subject)
--   source_event_ids   the deposit(s) it comes from
--   last_mentioned_at  last time a deposit mentioned it
--   outcome            'fait' | 'abandonne' (with resolved_at)
--   outcome_note       what happened, one sentence
ALTER TABLE intentions ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'capsule';
ALTER TABLE intentions ADD COLUMN IF NOT EXISTS source_event_ids BIGINT[];
ALTER TABLE intentions ADD COLUMN IF NOT EXISTS last_mentioned_at TIMESTAMPTZ;
ALTER TABLE intentions ADD COLUMN IF NOT EXISTS outcome TEXT;
ALTER TABLE intentions ADD COLUMN IF NOT EXISTS outcome_note TEXT;

DO $$ BEGIN
    ALTER TABLE intentions ADD CONSTRAINT intentions_kind
        CHECK (kind IN ('capsule', 'etape'));
    ALTER TABLE intentions ADD CONSTRAINT intentions_outcome
        CHECK (outcome IS NULL OR outcome IN ('fait', 'abandonne'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
