import json

from pensine.llm import extract_json, parse_cli_output


def test_parse_cli_json_wrapper():
    out = parse_cli_output(json.dumps({"result": "[1, 2]", "cost_usd": 0.1}))
    assert out == "[1, 2]"


def test_parse_cli_plain_text():
    assert parse_cli_output("du texte brut\n") == "du texte brut"


def test_is_error_ne_passe_pas_pour_une_reponse():
    import pytest

    from pensine.llm import LLMUnavailable
    payload = json.dumps({"is_error": True, "result": "API Error: 401 revoked"})
    with pytest.raises(LLMUnavailable):
        parse_cli_output(payload)


def test_extract_json_nu():
    assert extract_json('[{"a": 1}]') == [{"a": 1}]


def test_extract_json_avec_fence():
    assert extract_json('```json\n[{"a": 1}]\n```') == [{"a": 1}]


def test_extract_json_avec_texte_autour():
    text = 'Voici les mémoires :\n[{"type": "episodic"}]\nVoilà.'
    assert extract_json(text) == [{"type": "episodic"}]


def test_fake_backend(monkeypatch):
    from pensine import config, llm
    monkeypatch.setattr(config, "LLM_BACKEND", "fake")
    monkeypatch.setenv("PENSINE_FAKE_LLM_RESPONSE", '[{"ok": true}]')
    assert llm.complete("peu importe") == '[{"ok": true}]'
