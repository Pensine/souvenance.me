-- Proposed memory: the AI spots, the user decides.
--
-- A conversation contains more memorable things than anyone bothers to
-- dictate. Letting the assistant spot them removes the capture friction
-- — the first documented cause of abandonment for this kind of system.
--
-- But a memory written unilaterally by an AI is exactly what this project
-- holds against the assistants on the market. The difference was never about
-- who spots: it is about who decides, and whether what was decided can be
-- seen. Hence this table: a proposal is NOT an event. It waits. Nothing
-- enters the substrate without a second act.
--
-- Refusals are kept just like acceptances: what one does not want memorized
-- is information about oneself, and a log that only kept the yeses would not
-- tell the truth about what happened.
CREATE TABLE memory_proposals (
    id BIGSERIAL PRIMARY KEY,
    proposed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    content TEXT NOT NULL,          -- what the assistant understood, in plain words
    kind TEXT NOT NULL,             -- 'fact' (verifiable) | 'inference' (about the person)
    rationale TEXT,                 -- why it thinks this matters, shown to the user
    status TEXT NOT NULL DEFAULT 'pending',   -- 'pending' | 'confirmed' | 'declined'
    decided_at TIMESTAMPTZ,
    decline_reason TEXT,
    event_id BIGINT REFERENCES events(id),    -- filled in at confirmation only
    CONSTRAINT memory_proposals_kind CHECK (kind IN ('fact', 'inference')),
    CONSTRAINT memory_proposals_status CHECK (status IN ('pending', 'confirmed', 'declined')),
    -- an event exists only for a confirmed proposal, and vice versa
    CONSTRAINT memory_proposals_event_iff_confirmed
        CHECK ((status = 'confirmed') = (event_id IS NOT NULL))
);
CREATE INDEX memory_proposals_pending_idx ON memory_proposals(proposed_at)
    WHERE status = 'pending';

-- Event provenance: distinguish what the user deliberately deposited from
-- what an assistant proposed and the user accepted.
--
-- Without this column, the two become indistinguishable the next day, and the
-- question "what did the system decide to retain on its own?" has no answer
-- any more. It is precisely the question one cannot ask the assistants on the
-- market; here it must remain a simple query.
ALTER TABLE events ADD COLUMN origin TEXT NOT NULL DEFAULT 'declared';
ALTER TABLE events ADD CONSTRAINT events_origin
    CHECK (origin IN ('declared', 'proposed'));
CREATE INDEX events_origin_idx ON events(origin);
