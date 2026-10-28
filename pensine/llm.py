"""Compute adapter — the intelligent layer is interchangeable (§11).

Backends:
- `claude-cli`: Claude Code headless (`claude -p`), covered by the user's
  Max/Pro subscription. The default.
- `api`       : Anthropic API with a key (PENSINE_ANTHROPIC_API_KEY).
- `openai`    : any OpenAI-compatible server (/v1/chat/completions) —
  OpenAI, Mistral, LM Studio, mlx_lm.server, vLLM, llama.cpp, Ollama /v1.
  PENSINE_LLM_BASE_URL, PENSINE_LLM_MODEL, PENSINE_LLM_API_KEY (optional).
- `ollama`    : Ollama native API (PENSINE_OLLAMA_URL, PENSINE_OLLAMA_MODEL).
- `fake`      : for tests — returns PENSINE_FAKE_LLM_RESPONSE.

Zero-maintenance principle: if the backend breaks, the caller treats the
failure as a pause (events accumulate, consolidation catches up) — never a loss.
"""

from __future__ import annotations  # the setup wizard runs under Python 3.9

import base64
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import config

TIMEOUT_S = 1800

MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
               ".gif": "image/gif", ".webp": "image/webp"}


class LLMUnavailable(RuntimeError):
    """The backend is unavailable — a pause, not a loss."""


def complete(prompt: str, *, system: str = "") -> str:
    backend = config.LLM_BACKEND
    if backend == "fake":
        return os.environ.get("PENSINE_FAKE_LLM_RESPONSE", "[]")
    if backend == "claude-cli":
        return _cli(prompt, system=system)
    if backend == "api":
        return _api([{"role": "user", "content": prompt}], system=system)
    if backend == "ollama":
        return _ollama(prompt, system=system)
    if backend == "openai":
        return _openai(_with_system([{"role": "user", "content": prompt}], system))
    raise LLMUnavailable(f"unknown backend: {backend}")


def describe_image(path: Path, *, prompt: str) -> str:
    backend = config.LLM_BACKEND
    if backend == "fake":
        return os.environ.get("PENSINE_FAKE_VISION_RESPONSE", "(description de test)")
    if backend == "claude-cli":
        # Claude Code reads the file itself (Read tool, vision included)
        # ("Fichier image" is part of the French prompt text sent to the model)
        return _cli(f"{prompt}\n\nFichier image : {path}",
                    extra_args=["--allowedTools", "Read", "--add-dir", str(path.parent)])
    media_type = MEDIA_TYPES.get(path.suffix.lower(), "image/jpeg")
    data = base64.standard_b64encode(path.read_bytes()).decode()
    if backend == "api":
        return _api([{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                         "data": data}},
            {"type": "text", "text": prompt},
        ]}])
    if backend == "openai":
        return _openai([{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{data}"}},
        ]}], model=config.VISION_MODEL or config.LLM_MODEL)
    if backend == "ollama":
        # Ollama's native API takes images alongside the text
        return _ollama_chat([{"role": "user", "content": prompt, "images": [data]}],
                            model=config.VISION_MODEL or config.OLLAMA_MODEL)
    raise LLMUnavailable(f"unknown backend: {backend}")


def _cli(prompt: str, *, system: str = "", extra_args: list[str] | None = None) -> str:
    cmd = [config.CLAUDE_BIN, "-p", prompt, "--output-format", "json"]
    if config.LLM_MODEL:
        # without this flag, PENSINE_LLM_MODEL was ignored and the CLI used
        # its default model — the config must tell the truth
        cmd += ["--model", config.LLM_MODEL]
    if system:
        cmd += ["--append-system-prompt", system]
    cmd += extra_args or []
    try:
        # stdin closed: otherwise the CLI inherits the terminal and may wait
        # for input that will never come (consolidation runs with no human)
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=TIMEOUT_S, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise LLMUnavailable(f"`{config.CLAUDE_BIN}` not found — install Claude Code, "
                             "set PENSINE_CLAUDE_BIN, or switch to "
                             "PENSINE_LLM_BACKEND=api")
    except subprocess.TimeoutExpired:
        raise LLMUnavailable("claude -p: timeout")
    if proc.returncode != 0:
        # claude writes some errors (auth in particular) to stdout
        detail = (proc.stderr.strip() or proc.stdout.strip())[:500]
        raise LLMUnavailable(f"claude -p failed: {detail}")
    return parse_cli_output(proc.stdout)


def parse_cli_output(stdout: str) -> str:
    """`claude -p --output-format json` wraps the result; we extract the text."""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout.strip()
    if isinstance(payload, dict):
        if payload.get("is_error"):
            # an error message is not an answer: letting it through would
            # write noise into the memories
            raise LLMUnavailable(f"claude -p: {str(payload.get('result', ''))[:500]}")
        return str(payload.get("result", payload))
    return str(payload)


# -- Dependency-free HTTP -------------------------------------------------------

def _with_system(messages: list[dict], system: str) -> list[dict]:
    return ([{"role": "system", "content": system}] if system else []) + messages


def _post_json(url: str, body: dict, headers: dict | None = None) -> dict:
    """POST JSON → JSON. An HTTPError keeps the response body: the server
    says why there (unknown model, rejected parameter, invalid key)."""
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.load(resp)


def _error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", "replace")[:300]
    except Exception:
        return str(exc)


_THINK = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL)


def strip_thinking(text: str) -> str:
    """Local reasoning models (Qwen3, DeepSeek-R1…) prefix their answer with a
    <think> block: it is a draft, not the answer."""
    return _THINK.sub("", text, count=1)


# -- Ollama (API native) ------------------------------------------------------

def _ollama(prompt: str, *, system: str = "") -> str:
    """100% local backend (maximum resilience: the exit is the feature)."""
    return _ollama_chat(_with_system([{"role": "user", "content": prompt}], system))


def _ollama_chat(messages: list[dict], *, model: str | None = None) -> str:
    try:
        payload = _post_json(f"{config.OLLAMA_URL}/api/chat", {
            "model": model or config.OLLAMA_MODEL, "messages": messages, "stream": False})
    except urllib.error.HTTPError as exc:
        raise LLMUnavailable(f"Ollama refused ({exc.code}): {_error_body(exc)}")
    except (urllib.error.URLError, OSError) as exc:
        raise LLMUnavailable(f"Ollama unreachable ({config.OLLAMA_URL}): {exc}")
    try:
        return strip_thinking(payload["message"]["content"])
    except (KeyError, TypeError):
        raise LLMUnavailable(f"unexpected Ollama response: {str(payload)[:200]}")


# -- OpenAI-compatible ---------------------------------------------------------

def chat_completions_url(base_url: str) -> str:
    """The address as pasted, reduced to the endpoint:
    `http://host:1234` → `…/v1/chat/completions`; a base with a path
    (`…/v1`, `…/v1beta/openai`) → `+ /chat/completions`; a full address
    is kept as is."""
    base = base_url.strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if urllib.parse.urlparse(base).path in ("", "/"):
        base += "/v1"
    return base + "/chat/completions"


def _openai(messages: list[dict], *, model: str | None = None) -> str:
    if not config.LLM_BASE_URL:
        raise LLMUnavailable("PENSINE_LLM_BASE_URL not configured (openai backend)")
    model = model or config.LLM_MODEL
    if not model:
        raise LLMUnavailable("PENSINE_LLM_MODEL not configured (openai backend)")
    url = chat_completions_url(config.LLM_BASE_URL)
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"} if config.LLM_API_KEY else {}
    body = {"model": model, "messages": messages, "stream": False,
            "max_tokens": config.LLM_MAX_TOKENS}
    try:
        try:
            payload = _post_json(url, body, headers)
        except urllib.error.HTTPError as exc:
            detail = _error_body(exc)
            # OpenAI's reasoning models reject max_tokens and only accept
            # max_completion_tokens
            if exc.code == 400 and "max_tokens" in detail:
                body["max_completion_tokens"] = body.pop("max_tokens")
                payload = _post_json(url, body, headers)
            else:
                raise LLMUnavailable(f"{url} refused ({exc.code}): {detail}")
    except urllib.error.HTTPError as exc:
        raise LLMUnavailable(f"{url} refused ({exc.code}): {_error_body(exc)}")
    except (urllib.error.URLError, OSError) as exc:
        raise LLMUnavailable(f"{url} unreachable: {exc}")
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMUnavailable(f"unexpected response from {url}: {str(payload)[:200]}")
    if isinstance(content, list):  # some servers return blocks
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return strip_thinking(content or "")


# -- Anthropic -----------------------------------------------------------------

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def _api(messages: list[dict], *, system: str = "") -> str:
    key = config.ANTHROPIC_API_KEY
    if not key:
        raise LLMUnavailable("PENSINE_ANTHROPIC_API_KEY not configured")
    try:
        from anthropic import Anthropic
    except ImportError:
        # without the SDK, the same call over raw HTTP: one dependency fewer
        return _anthropic_http(messages, system=system, key=key)
    client = Anthropic(api_key=key)
    resp = client.messages.create(
        model=config.LLM_MODEL, max_tokens=8192,
        system=system or None, messages=messages,
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def _anthropic_http(messages: list[dict], *, system: str, key: str) -> str:
    body = {"model": config.LLM_MODEL, "max_tokens": 8192, "messages": messages}
    if system:
        body["system"] = system
    try:
        payload = _post_json(ANTHROPIC_URL, body, {
            "x-api-key": key, "anthropic-version": "2023-06-01"})
    except urllib.error.HTTPError as exc:
        raise LLMUnavailable(f"Anthropic API refused ({exc.code}): {_error_body(exc)}")
    except (urllib.error.URLError, OSError) as exc:
        raise LLMUnavailable(f"Anthropic API unreachable: {exc}")
    return "".join(b.get("text", "") for b in payload.get("content") or []
                   if b.get("type") == "text")


def extract_json(text: str):
    """The LLM sometimes answers with text around the JSON — we isolate the block."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        text = text.removeprefix("json").strip()
    start = min((i for i in (text.find("["), text.find("{")) if i >= 0), default=-1)
    if start > 0:
        text = text[start:]
    end = max(text.rfind("]"), text.rfind("}"))
    if end >= 0:
        text = text[:end + 1]
    return json.loads(text)
