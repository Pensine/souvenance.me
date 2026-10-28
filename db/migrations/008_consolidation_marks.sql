-- "Seen, nothing to draw from it": an examination with no harvest must remain
-- a conclusion.
--
-- An event was considered "to be consolidated" as long as no memory cited it.
-- Consequence: an event that consolidation legitimately decides has nothing
-- worth retaining — an empty logbook entry, a test, a notification with no
-- content — was never marked as processed. It came back every night, cost a
-- model call, and piled up with its kind in the prompt of every following
-- cycle.
--
-- The marker cannot live on `events`: the append-only trigger forbids any
-- UPDATE, and rightly so. That a cycle examined an event is not a fact about
-- the person's life — it is a state of the processing, hence a projection,
-- hence its place is here.
--
-- FULL REPLAY: `DELETE FROM consolidation_marks;` then rerunning
-- consolidation makes the current engine reread the whole log. This is the
-- central promise of the architecture — a better model rereads the same life
-- — and it stays true because this marker is disposable.
CREATE TABLE consolidation_marks (
    event_id BIGINT PRIMARY KEY REFERENCES events(id),
    examined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    produced_memory BOOLEAN NOT NULL DEFAULT false
);

-- Events already consolidated before this migration have no marker.
-- We mark them according to what they produced; otherwise the first cycle
-- would reexamine the whole corpus and create duplicate memories.
INSERT INTO consolidation_marks (event_id, examined_at, produced_memory)
SELECT DISTINCT e.id, now(), true
FROM events e
WHERE EXISTS (SELECT 1 FROM memories m WHERE e.id = ANY(m.source_event_ids))
ON CONFLICT (event_id) DO NOTHING;
