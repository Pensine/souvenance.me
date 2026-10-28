"""HTTP backends of the compute adapter, against a fake local server:
OpenAI-compatible (LM Studio, mlx, vLLM, Mistral, OpenAI...), native Ollama,
Anthropic without the SDK."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from pensine import config, llm


class FakeServer:
    """Records the requests; `replies`: list of (code, body) served
    in order (the last one repeats)."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"path": self.path, "body": body,
                                       "headers": {k.lower(): v for k, v in self.headers.items()}})
                code, reply = outer.replies[0] if len(outer.replies) == 1 \
                    else outer.replies.pop(0)
                data = json.dumps(reply).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, args=(0.05,), daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _chat(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


@pytest.fixture
def server():
    created = []

    def make(*replies):
        s = FakeServer(replies or [(200, _chat("ok"))])
        created.append(s)
        return s

    yield make
    for s in created:
        s.close()


@pytest.fixture
def openai_backend(monkeypatch):
    def use(url, model="mon-modele", key=""):
        monkeypatch.setattr(config, "LLM_BACKEND", "openai")
        monkeypatch.setattr(config, "LLM_BASE_URL", url)
        monkeypatch.setattr(config, "LLM_MODEL", model)
        monkeypatch.setattr(config, "LLM_API_KEY", key)
        monkeypatch.setattr(config, "VISION_MODEL", "")
    return use


@pytest.mark.parametrize("base,expected", [
    ("http://localhost:1234", "http://localhost:1234/v1/chat/completions"),
    ("http://localhost:1234/", "http://localhost:1234/v1/chat/completions"),
    ("http://localhost:11434/v1", "http://localhost:11434/v1/chat/completions"),
    ("https://api.mistral.ai/v1/", "https://api.mistral.ai/v1/chat/completions"),
    ("https://g.example/v1beta/openai", "https://g.example/v1beta/openai/chat/completions"),
    ("https://x.example/v1/chat/completions", "https://x.example/v1/chat/completions"),
])
def test_adresse_du_point_d_appel(base, expected):
    assert llm.chat_completions_url(base) == expected


def test_openai_complete(server, openai_backend):
    s = server((200, _chat("[1, 2]")))
    openai_backend(s.url, key="cle-secrete")
    assert llm.complete("bonjour", system="tu es bref") == "[1, 2]"
    req = s.requests[0]
    assert req["path"] == "/v1/chat/completions"
    assert req["body"]["model"] == "mon-modele"
    assert req["body"]["messages"] == [{"role": "system", "content": "tu es bref"},
                                       {"role": "user", "content": "bonjour"}]
    assert req["body"]["max_tokens"] == config.LLM_MAX_TOKENS
    assert req["headers"]["authorization"] == "Bearer cle-secrete"


def test_openai_sans_cle_pas_d_en_tete(server, openai_backend):
    s = server()
    openai_backend(s.url)
    llm.complete("x")
    assert "authorization" not in s.requests[0]["headers"]


def test_openai_retire_le_brouillon_think(server, openai_backend):
    s = server((200, _chat("<think>je réfléchis…</think>\n\n[]")))
    openai_backend(s.url)
    assert llm.complete("x") == "[]"


def test_openai_max_completion_tokens_en_repli(server, openai_backend):
    s = server((400, {"error": {"message": "Unsupported parameter: 'max_tokens'"}}),
               (200, _chat("ok")))
    openai_backend(s.url)
    assert llm.complete("x") == "ok"
    assert "max_tokens" not in s.requests[1]["body"]
    assert s.requests[1]["body"]["max_completion_tokens"] == config.LLM_MAX_TOKENS


def test_openai_erreur_devient_pause(server, openai_backend):
    s = server((401, {"error": "clé invalide"}))
    openai_backend(s.url)
    with pytest.raises(llm.LLMUnavailable, match="401"):
        llm.complete("x")


def test_openai_injoignable(openai_backend):
    openai_backend("http://127.0.0.1:9")  # discard port: nobody is listening
    with pytest.raises(llm.LLMUnavailable, match="unreachable"):
        llm.complete("x")


def test_openai_sans_modele(openai_backend):
    openai_backend("http://127.0.0.1:9", model="")
    with pytest.raises(llm.LLMUnavailable, match="PENSINE_LLM_MODEL"):
        llm.complete("x")


def test_openai_vision(server, openai_backend, tmp_path, monkeypatch):
    s = server((200, _chat("Un chat sur un toit.")))
    openai_backend(s.url)
    monkeypatch.setattr(config, "VISION_MODEL", "modele-vision")
    img = tmp_path / "p.png"
    img.write_bytes(b"\x89PNG fake")
    assert llm.describe_image(img, prompt="Décris") == "Un chat sur un toit."
    body = s.requests[0]["body"]
    assert body["model"] == "modele-vision"
    parts = body["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "Décris"}
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_ollama_texte_et_vision(server, monkeypatch, tmp_path):
    s = server((200, {"message": {"role": "assistant", "content": "réponse"}}))
    monkeypatch.setattr(config, "LLM_BACKEND", "ollama")
    monkeypatch.setattr(config, "OLLAMA_URL", s.url)
    monkeypatch.setattr(config, "OLLAMA_MODEL", "qwen3")
    monkeypatch.setattr(config, "VISION_MODEL", "qwen2.5vl")
    assert llm.complete("x", system="sys") == "réponse"
    assert s.requests[0]["path"] == "/api/chat"
    assert s.requests[0]["body"]["messages"][0] == {"role": "system", "content": "sys"}
    img = tmp_path / "p.jpg"
    img.write_bytes(b"jpeg")
    assert llm.describe_image(img, prompt="Décris") == "réponse"
    msg = s.requests[1]["body"]["messages"][0]
    assert s.requests[1]["body"]["model"] == "qwen2.5vl"
    assert msg["content"] == "Décris" and msg["images"] == ["anBlZw=="]


def test_anthropic_sans_sdk(server, monkeypatch):
    import builtins

    s = server((200, {"content": [{"type": "text", "text": "salut"}]}))
    real_import = builtins.__import__

    def no_anthropic(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_anthropic)
    monkeypatch.setattr(config, "LLM_BACKEND", "api")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(llm, "ANTHROPIC_URL", s.url + "/v1/messages")
    assert llm.complete("x", system="sys") == "salut"
    req = s.requests[0]
    assert req["headers"]["x-api-key"] == "sk-ant-test"
    assert req["body"]["system"] == "sys"


# -- Structured output (JSON mode) ----------------------------------------------

def test_openai_json_mode_asks_for_a_json_object(server, openai_backend, monkeypatch):
    monkeypatch.setattr(llm, "_JSON_LEVEL", {})
    s = server((200, _chat('{"memories": []}')))
    openai_backend(s.url)
    llm.complete("x", json_mode=True)
    assert s.requests[0]["body"]["response_format"] == {"type": "json_object"}


def test_openai_without_json_mode_sends_no_format(server, openai_backend):
    s = server()
    openai_backend(s.url)
    llm.complete("x")
    assert "response_format" not in s.requests[0]["body"]


def test_openai_json_mode_off_by_config(server, openai_backend, monkeypatch):
    monkeypatch.setattr(config, "LLM_JSON_MODE", "off")
    s = server()
    openai_backend(s.url)
    llm.complete("x", json_mode=True)
    assert "response_format" not in s.requests[0]["body"]


def test_openai_falls_back_to_json_schema_then_none(server, openai_backend, monkeypatch):
    """LM Studio refuses json_object but takes json_schema; another server
    refuses both: the call still goes through, and the refusal is remembered."""
    monkeypatch.setattr(llm, "_JSON_LEVEL", {})
    refuse = (400, {"error": "'response_format.type' must be 'json_schema' or 'text'"})
    s = server(refuse, refuse, (200, _chat("{}")))
    openai_backend(s.url)
    assert llm.complete("x", json_mode=True) == "{}"
    formats = [r["body"].get("response_format") for r in s.requests]
    assert formats[0] == {"type": "json_object"}
    assert formats[1]["type"] == "json_schema"
    assert formats[2] is None
    llm.complete("y", json_mode=True)  # remembered: no refused format sent again
    assert "response_format" not in s.requests[3]["body"]


def test_openai_other_400_is_still_a_pause(server, openai_backend, monkeypatch):
    monkeypatch.setattr(llm, "_JSON_LEVEL", {})
    s = server((400, {"error": "model not found"}))
    openai_backend(s.url)
    with pytest.raises(llm.LLMUnavailable, match="400"):
        llm.complete("x", json_mode=True)


def test_ollama_json_mode_sets_format(server, monkeypatch):
    s = server((200, {"message": {"role": "assistant", "content": "{}"}}))
    monkeypatch.setattr(config, "LLM_BACKEND", "ollama")
    monkeypatch.setattr(config, "OLLAMA_URL", s.url)
    llm.complete("x", json_mode=True)
    assert s.requests[0]["body"]["format"] == "json"
    llm.complete("x")
    assert "format" not in s.requests[1]["body"]
