"""Adaptateur compute — la couche intelligente est interchangeable (§11).

Backends :
- `claude-cli` : Claude Code headless (`claude -p`), couvert par l'abonnement
  Max/Pro de l'utilisateur. Le défaut.
- `api`       : API Anthropic avec clé (PENSINE_ANTHROPIC_API_KEY).
- `fake`      : pour les tests — renvoie PENSINE_FAKE_LLM_RESPONSE.

Principe zéro-MCO : si le backend casse, l'appelant traite l'échec comme une
pause (les events s'accumulent, la consolidation rattrape) — jamais une perte.
"""

import base64
import json
import os
import subprocess
from pathlib import Path

from . import config

TIMEOUT_S = 1800


class LLMUnavailable(RuntimeError):
    """Le backend est indisponible — pause, pas perte."""


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
    raise LLMUnavailable(f"backend inconnu : {backend}")


def describe_image(path: Path, *, prompt: str) -> str:
    backend = config.LLM_BACKEND
    if backend == "fake":
        return os.environ.get("PENSINE_FAKE_VISION_RESPONSE", "(description de test)")
    if backend == "claude-cli":
        # Claude Code lit le fichier lui-même (outil Read, vision incluse)
        return _cli(f"{prompt}\n\nFichier image : {path}",
                    extra_args=["--allowedTools", "Read", "--add-dir", str(path.parent)])
    if backend == "api":
        media_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                      ".gif": "image/gif", ".webp": "image/webp"}.get(path.suffix.lower(),
                                                                      "image/jpeg")
        data = base64.standard_b64encode(path.read_bytes()).decode()
        return _api([{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                         "data": data}},
            {"type": "text", "text": prompt},
        ]}])
    raise LLMUnavailable(f"backend inconnu : {backend}")


def _cli(prompt: str, *, system: str = "", extra_args: list[str] | None = None) -> str:
    cmd = ["claude", "-p", prompt, "--output-format", "json"]
    if config.LLM_MODEL:
        # sans ce flag, PENSINE_LLM_MODEL était ignoré et le CLI prenait
        # son modèle par défaut — la config doit dire la vérité
        cmd += ["--model", config.LLM_MODEL]
    if system:
        cmd += ["--append-system-prompt", system]
    cmd += extra_args or []
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
    except FileNotFoundError:
        raise LLMUnavailable("`claude` introuvable — installer Claude Code sur le VPS "
                             "ou passer PENSINE_LLM_BACKEND=api")
    except subprocess.TimeoutExpired:
        raise LLMUnavailable("claude -p : timeout")
    if proc.returncode != 0:
        # claude écrit certaines erreurs (auth notamment) sur stdout
        detail = (proc.stderr.strip() or proc.stdout.strip())[:500]
        raise LLMUnavailable(f"claude -p a échoué : {detail}")
    return parse_cli_output(proc.stdout)


def parse_cli_output(stdout: str) -> str:
    """`claude -p --output-format json` enveloppe le résultat ; on extrait le texte."""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout.strip()
    if isinstance(payload, dict):
        if payload.get("is_error"):
            # un message d'erreur n'est pas une réponse : le laisser passer
            # écrirait du bruit dans les mémoires
            raise LLMUnavailable(f"claude -p : {str(payload.get('result', ''))[:500]}")
        return str(payload.get("result", payload))
    return str(payload)


def _ollama(prompt: str, *, system: str = "") -> str:
    """Backend 100 % local (résilience maximale : the exit is the feature).
    La vision n'est pas couverte — describe_image dégrade en pause."""
    import urllib.error
    import urllib.request

    messages = ([{"role": "system", "content": system}] if system else []) + \
        [{"role": "user", "content": prompt}]
    body = json.dumps({"model": config.OLLAMA_MODEL, "messages": messages,
                       "stream": False}).encode()
    req = urllib.request.Request(
        f"{config.OLLAMA_URL}/api/chat", data=body,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            payload = json.load(resp)
    except (urllib.error.URLError, OSError) as exc:
        raise LLMUnavailable(f"Ollama injoignable ({config.OLLAMA_URL}) : {exc}")
    try:
        return payload["message"]["content"]
    except (KeyError, TypeError):
        raise LLMUnavailable(f"réponse Ollama inattendue : {str(payload)[:200]}")


def _api(messages: list[dict], *, system: str = "") -> str:
    try:
        from anthropic import Anthropic
    except ImportError:
        raise LLMUnavailable("paquet `anthropic` absent — pip install 'pensine[api]'")
    key = config.ANTHROPIC_API_KEY
    if not key:
        raise LLMUnavailable("PENSINE_ANTHROPIC_API_KEY non configurée")
    client = Anthropic(api_key=key)
    resp = client.messages.create(
        model=config.LLM_MODEL, max_tokens=8192,
        system=system or None, messages=messages,
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def extract_json(text: str):
    """Le LLM répond parfois avec du texte autour du JSON — on isole le bloc."""
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
