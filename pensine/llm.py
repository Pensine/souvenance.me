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


def complete(prompt: str, *, system: str = "", json_mode: bool = False) -> str:
    """One completion. `json_mode` asks the backend for a JSON object when it
    can enforce one (OpenAI-compatible `response_format`, Ollama `format`);
    the claude CLI and the Anthropic API have no such switch and rely on the
    prompt. Either way the caller still parses defensively (`parse_json`)."""
    backend = config.LLM_BACKEND
    json_mode = json_mode and config.LLM_JSON_MODE != "off"
    if backend == "fake":
        return _fake()
    if backend == "claude-cli":
        return _cli(prompt, system=system)
    if backend == "api":
        return _api([{"role": "user", "content": prompt}], system=system)
    if backend == "ollama":
        return _ollama(prompt, system=system, json_mode=json_mode)
    if backend == "openai":
        return _openai(_with_system([{"role": "user", "content": prompt}], system),
                       json_mode=json_mode)
    raise LLMUnavailable(f"unknown backend: {backend}")


def _fake() -> str:
    """Test backend. PENSINE_FAKE_LLM_RESPONSES (a JSON list of strings) is
    served one answer per call, the last one repeating — enough to script a
    malformed first answer followed by a valid retry."""
    seq = os.environ.get("PENSINE_FAKE_LLM_RESPONSES")
    if seq:
        answers = json.loads(seq)
        i = _FAKE_CALLS[0]
        _FAKE_CALLS[0] += 1
        return answers[min(i, len(answers) - 1)]
    return os.environ.get("PENSINE_FAKE_LLM_RESPONSE", "[]")


_FAKE_CALLS = [0]


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

def _ollama(prompt: str, *, system: str = "", json_mode: bool = False) -> str:
    """100% local backend (maximum resilience: the exit is the feature)."""
    return _ollama_chat(_with_system([{"role": "user", "content": prompt}], system),
                        json_mode=json_mode)


def _ollama_chat(messages: list[dict], *, model: str | None = None,
                 json_mode: bool = False) -> str:
    body = {"model": model or config.OLLAMA_MODEL, "messages": messages, "stream": False}
    if json_mode:
        body["format"] = "json"  # grammar-constrained decoding on Ollama's side
    try:
        payload = _post_json(f"{config.OLLAMA_URL}/api/chat", body)
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


# Structured output, from the strictest to none. Servers differ: OpenAI,
# vLLM, llama.cpp and Ollama /v1 take `json_object`; LM Studio only takes
# `json_schema`; mlx_lm.server ignores the field. A server that rejects a
# level is remembered (per endpoint, for the process) and asked the next one.
_JSON_FORMATS = (
    {"type": "json_object"},
    {"type": "json_schema", "json_schema": {"name": "answer", "schema": {"type": "object"}}},
)
_JSON_LEVEL: dict[str, int] = {}


def _rejects_format(code: int, detail: str) -> bool:
    d = detail.lower()
    return code in (400, 422) and ("response_format" in d or "json_schema" in d
                                   or "json_object" in d)


def _openai(messages: list[dict], *, model: str | None = None,
            json_mode: bool = False) -> str:
    if not config.LLM_BASE_URL:
        raise LLMUnavailable("PENSINE_LLM_BASE_URL not configured (openai backend)")
    model = model or config.LLM_MODEL
    if not model:
        raise LLMUnavailable("PENSINE_LLM_MODEL not configured (openai backend)")
    url = chat_completions_url(config.LLM_BASE_URL)
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"} if config.LLM_API_KEY else {}
    body = {"model": model, "messages": messages, "stream": False,
            "max_tokens": config.LLM_MAX_TOKENS}
    level = _JSON_LEVEL.get(url, 0) if json_mode else len(_JSON_FORMATS)
    payload = None
    try:
        for _ in range(len(_JSON_FORMATS) + 2):
            if level < len(_JSON_FORMATS):
                body["response_format"] = _JSON_FORMATS[level]
            else:
                body.pop("response_format", None)
            try:
                payload = _post_json(url, body, headers)
                break
            except urllib.error.HTTPError as exc:
                detail = _error_body(exc)
                if "response_format" in body and _rejects_format(exc.code, detail):
                    level += 1
                    _JSON_LEVEL[url] = level
                    continue
                # OpenAI's reasoning models reject max_tokens and only accept
                # max_completion_tokens
                if exc.code == 400 and "max_tokens" in detail and "max_tokens" in body:
                    body["max_completion_tokens"] = body.pop("max_tokens")
                    continue
                raise LLMUnavailable(f"{url} refused ({exc.code}): {detail}")
    except (urllib.error.URLError, OSError) as exc:
        raise LLMUnavailable(f"{url} unreachable: {exc}")
    if payload is None:
        raise LLMUnavailable(f"{url} refused every request format")
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
    """The JSON value in a model answer, repaired if need be (see parse_json)."""
    return parse_json(text)[0]


_FENCE = re.compile(r"```[ \t]*(?:json|JSON)?[ \t]*\n?(.*?)(?:```|$)", re.DOTALL)
_MAX_STARTS = 20


def parse_json(text: str) -> tuple[object, str]:
    """Find the JSON value in a model answer. Returns `(value, how)`:

      clean      the answer was the JSON and nothing else;
      repaired   it was wrapped (prose, code fence, a trailing remark) or
                 carried trailing commas — the value itself is whole;
      truncated  the answer stopped mid-value (token cap, runaway output):
                 every complete element is kept, the unfinished tail is cut
                 and the open brackets are closed.

    Small local models do all three. `truncated` loses data, so the caller
    decides whether to accept it (consolidation prefers a smaller batch).
    Raises ValueError (json.JSONDecodeError) when nothing can be recovered.
    """
    text = strip_thinking(text or "").strip()
    if text.startswith("<think>"):  # unclosed reasoning block: no answer in it
        raise json.JSONDecodeError("unterminated <think> block", text, 0)
    try:
        return json.loads(text), "clean"
    except ValueError:
        pass
    candidates = [m.group(1) for m in _FENCE.finditer(text) if m.group(1).strip()]
    candidates.append(text)
    decoder = json.JSONDecoder()
    first_error: ValueError | None = None
    for cand in candidates:
        # only brackets at depth 0: an object nested in a truncated answer
        # (one memory) must never pass for the whole answer
        for start in _top_level_starts(cand):
            try:  # whole value, trailing text ignored
                return decoder.raw_decode(cand, start)[0], "repaired"
            except ValueError as exc:
                first_error = first_error or exc
            fixed, truncated = _mend(cand[start:])  # trailing commas, truncation
            if fixed is None:
                continue
            try:
                return decoder.raw_decode(fixed)[0], "truncated" if truncated else "repaired"
            except ValueError as exc:
                first_error = first_error or exc
    raise first_error or json.JSONDecodeError("no JSON value found", text, 0)


def _top_level_starts(s: str) -> list[int]:
    """Positions of `{` or `[` that are not inside an earlier bracket
    (strings skipped): where a whole JSON value may begin."""
    starts: list[int] = []
    depth, in_str, esc = 0, False, False
    for i, c in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"' and depth:
            in_str = True
        elif c in "{[":
            if depth == 0:
                starts.append(i)
                if len(starts) >= _MAX_STARTS:
                    break
            depth += 1
        elif c in "}]" and depth:
            depth -= 1
    return starts


def _mend(s: str) -> tuple[str | None, bool]:
    """Repair a JSON text in one string-aware pass: drop trailing commas
    before a closing bracket; if the text ends inside a value, cut back to
    the last element that was complete and close what is still open.
    Returns (text, truncated) — text is None when there is nothing to keep."""
    out: list[str] = []
    stack: list[str] = []
    cuts: list[tuple[int, list[str]]] = []  # (length of out, open brackets) after a complete element
    in_str = esc = False
    for c in s:
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
            out.append(c)
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
            out.append(c)
        elif c in "}]":
            while out and out[-1] in " \t\r\n":
                out.pop()
            if out and out[-1] == ",":
                out.pop()
            if not stack or stack[-1] != c:
                break  # mismatched bracket: keep what came before
            stack.pop()
            out.append(c)
            if not stack:
                return "".join(out), False
            cuts.append((len(out), list(stack)))
        else:
            out.append(c)
    if not stack and not in_str:
        return ("".join(out) or None), False
    for length, open_ in reversed(cuts):  # last complete element first
        head = "".join(out[:length]).rstrip().rstrip(",")
        return head + "".join(reversed(open_)), True
    return None, True
