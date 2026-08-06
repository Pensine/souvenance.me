import json

import pytest

from pensine.importers import detect_format, parse_chatgpt, parse_claude, parse_file

CHATGPT = [{
    "title": "Projet maison",
    "create_time": 1720000000.0,
    "mapping": {
        "a": {"message": {"author": {"role": "system"}, "create_time": 1720000000.0,
                          "content": {"content_type": "text", "parts": ["ignore"]}}},
        "b": {"message": {"author": {"role": "user"}, "create_time": 1720000010.0,
                          "content": {"content_type": "text",
                                      "parts": ["On reporte les travaux ?"]}}},
        "c": {"message": {"author": {"role": "assistant"}, "create_time": 1720000020.0,
                          "content": {"content_type": "text",
                                      "parts": ["Voici les options…"]}}},
        "d": {"message": None},
    },
}]

CLAUDE = [{
    "name": "Trail des Glières",
    "created_at": "2026-05-02T08:00:00Z",
    "chat_messages": [
        {"sender": "human", "text": "Plan d'allure pour 4h ?",
         "created_at": "2026-05-02T08:00:01Z"},
        {"sender": "assistant", "text": "Départ prudent…",
         "created_at": "2026-05-02T08:00:05Z"},
        {"sender": "human", "text": "", "created_at": "2026-05-02T08:01:00Z"},
    ],
}]


def test_detect():
    assert detect_format(CHATGPT) == "chatgpt"
    assert detect_format(CLAUDE) == "claude"
    assert detect_format([{"foo": 1}]) is None


def test_chatgpt_filtre_system_et_ordonne():
    events = parse_chatgpt(CHATGPT)
    assert len(events) == 1
    msgs = events[0]["payload"]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert events[0]["payload"]["title"] == "Projet maison"
    assert events[0]["occurred_at"].year == 2024


def test_claude_ignore_messages_vides():
    events = parse_claude(CLAUDE)
    assert events[0]["payload"]["message_count"] == 2
    assert events[0]["payload"]["provider"] == "claude"


def test_parse_file_format_inconnu(tmp_path):
    p = tmp_path / "conversations.json"
    p.write_text(json.dumps([{"mystery": True}]))
    with pytest.raises(ValueError, match="Format non reconnu"):
        parse_file(p)


def test_troncature_longs_messages():
    data = [{"name": "x", "created_at": "2026-01-01T00:00:00Z",
             "chat_messages": [{"sender": "human", "text": "a" * 9000,
                                "created_at": "2026-01-01T00:00:01Z"}]}]
    events = parse_claude(data)
    assert len(events[0]["payload"]["messages"][0]["text"]) == 2000
