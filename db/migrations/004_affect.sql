-- Affective layer: a memory carries a charge, not just a weight.
--
-- `importance` answers "does it matter?". It says nothing about what was
-- felt. A mundane lunch and a funeral can share the same importance; they do
-- not carry the same charge, and a memory that cannot tell the two apart does
-- not model a person.
--
-- Circumplex model (Russell, 1980): two orthogonal axes rather than a single
-- "good/bad" slider. Grief and anger are both negative but do not resemble
-- each other — one is subdued, the other is sharp. Without the second axis,
-- they become indistinguishable.
--
--   valence   -1 (distressing) … 0 (neutral) … +1 (happy)
--   arousal    0 (calm, subdued) … 1 (intense, activated)
--
-- NULL is a valid state, distinct from zero: "undetermined" is not
-- "neutral". Memories written before this migration stay NULL, and nothing
-- invents values for them retroactively — the originals are kept, and a future
-- reconsolidation can reread them.
ALTER TABLE memories ADD COLUMN valence REAL;
ALTER TABLE memories ADD COLUMN arousal REAL;

ALTER TABLE memories ADD CONSTRAINT memories_valence_range
    CHECK (valence IS NULL OR (valence >= -1.0 AND valence <= 1.0));
ALTER TABLE memories ADD CONSTRAINT memories_arousal_range
    CHECK (arousal IS NULL OR (arousal >= 0.0 AND arousal <= 1.0));

-- Intensity modulates consolidation: it is one of the best-established effects
-- of human memory (amygdala modulation). A charged memory resists forgetting;
-- a lukewarm one fades. The index serves the nightly decay, which filters on
-- arousal.
CREATE INDEX memories_arousal_idx ON memories(arousal) WHERE superseded_by IS NULL;
