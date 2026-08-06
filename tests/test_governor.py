"""La constitution est exécutable — donc testable."""

from pathlib import Path

import pytest
import yaml

from pensine.governor import Governor


@pytest.fixture
def gov(tmp_path: Path) -> Governor:
    p = tmp_path / "constitution.yaml"
    p.write_text(yaml.safe_dump({
        "exclusions": {"sources": ["mail_pro"], "motifs": ["ACME Corp"]},
    }), encoding="utf-8")
    return Governor(p)


def test_source_exclue(gov):
    ok, reason = gov.event_allowed("mail_pro", {"subject": "réunion"})
    assert not ok and "mail_pro" in reason


def test_motif_exclu_insensible_casse(gov):
    ok, reason = gov.event_allowed("mail", {"subject": "budget acme corp Q3"})
    assert not ok and "ACME Corp" in reason


def test_event_intime_passe(gov):
    ok, _ = gov.event_allowed("pensieve", {"note": "vocal du sommet"})
    assert ok


def test_actions_sortantes_refusees(gov):
    assert not gov.action_allowed("send_email")
    assert not gov.action_allowed("notify_user")
    assert gov.action_allowed("recall")
    assert gov.action_allowed("daily_log")


def test_constitution_injectee_dans_prompt(gov):
    text = gov.constitution_text()
    assert "ACME Corp" in text
    assert "jamais auto-ratifié" in text


def test_defauts_sans_fichier(tmp_path):
    g = Governor(tmp_path / "absent.yaml")
    ok, _ = g.event_allowed("calendar", {"summary": "n'importe quoi"})
    assert ok  # pas d'exclusion par défaut
    assert not g.action_allowed("publish_post")  # sortant toujours interdit en v1
