from datetime import datetime, timezone

from pensine.percepteurs.calendar_ics import parse_ics

SAMPLE = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART:20260803T140000Z
SUMMARY:Rendez-vous notaire
LOCATION:Annecy
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20260804
SUMMARY:Anniversaire — journée entière
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=Europe/Paris:20260804T183000
SUMMARY:Ligne pliée sur
  deux lignes (RFC 5545)
DESCRIPTION:Virgule échappée\\, et saut\\nde ligne
END:VEVENT
END:VCALENDAR
"""


def test_parse_trois_events():
    events = parse_ics(SAMPLE)
    assert len(events) == 3


def test_dtstart_utc():
    e = parse_ics(SAMPLE)[0]
    assert e["start"] == datetime(2026, 8, 3, 14, 0, tzinfo=timezone.utc)
    assert e["summary"] == "Rendez-vous notaire"
    assert e["location"] == "Annecy"


def test_journee_entiere():
    e = parse_ics(SAMPLE)[1]
    assert e["start"].date().isoformat() == "2026-08-04"


def test_ligne_pliee_et_echappements():
    e = parse_ics(SAMPLE)[2]
    assert e["summary"] == "Ligne pliée sur deux lignes (RFC 5545)"
    assert e["description"] == "Virgule échappée, et saut\nde ligne"
