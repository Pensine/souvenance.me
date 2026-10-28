-- A memory has a place as much as a date.
--
-- Human memory does not file memories in a dated list: it situates them —
-- "it was in the car, on the road to Albertville, the summer when…".
-- Time has been native from the start (valid_from / valid_to); space was
-- not, even though photos already carried their GPS coordinates.
--
-- The place is a projection, like validity time: it can be recomputed,
-- improved, corrected. It therefore lives on `media` and `memories`, never on
-- `events` (append-only). A position sent with a deposit is also kept as-is
-- in the event payload: the source stays intact.
--
-- place_source says where the place comes from, because a place is not
-- equally reliable depending on its origin:
--   gps_photo       EXIF coordinates of a photo
--   raccourci       position sent by the Shortcut (iOS) at deposit time
--   nom_dictaphone  name given by the Voice Memos app (an address, no coordinates)
--   declare         place stated by the person
ALTER TABLE media ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION;
ALTER TABLE media ADD COLUMN IF NOT EXISTS lon DOUBLE PRECISION;
ALTER TABLE media ADD COLUMN IF NOT EXISTS place TEXT;
ALTER TABLE media ADD COLUMN IF NOT EXISTS place_source TEXT;

ALTER TABLE memories ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS lon DOUBLE PRECISION;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS place TEXT;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS place_source TEXT;

-- Photos already deposited have their coordinates in exif: we surface them.
UPDATE media
SET lat = (exif->>'lat')::double precision,
    lon = (exif->>'lon')::double precision,
    place_source = 'gps_photo'
WHERE lat IS NULL AND exif ? 'lat' AND exif ? 'lon';
