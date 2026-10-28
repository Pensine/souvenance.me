"""Setup wizard — `python3 scripts/setup.py` (or `souvenance setup`).

Three questions (which AI, your first name, your public address), a real test
of the chosen AI, all secrets generated, a .env written, then the addresses to
paste into Claude, ChatGPT and the iOS shortcut. Re-runnable: secrets already
present are kept (changing the password of an already-created database would
make it unreadable).

Without a terminal, or with --yes, nothing is asked: the options are enough.

    python3 scripts/setup.py --yes --ai openai \\
        --base-url http://localhost:1234/v1 --model qwen3-30b-a3b

Standard library only: it runs before any installation.
`souvenance check` re-runs the AI test with the configuration in place
(useful in a container: docker compose run --rm api python -m
pensine.setup_wizard check).
"""

from __future__ import annotations  # Python 3.9 is enough (stock macOS)

import argparse
import json
import os
import secrets
import socket
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

SECRET_KEYS = {
    "POSTGRES_PASSWORD": 24,
    "PENSINE_DEPOSIT_TOKEN": 32,
    "PENSINE_MEDIA_LINK_SECRET": 32,
    "PENSINE_WEBAPP_PASSWORD": 12,
    "PENSINE_MCP_TOKEN": 24,
}
AI_CHOICES = ("claude", "anthropic", "openai", "ollama", "fake")
PRESETS = {"openai": "https://api.openai.com/v1", "mistral": "https://api.mistral.ai/v1"}
DEFAULT_CLAUDE_MODEL = "claude-sonnet-5-5"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


# -- .env ----------------------------------------------------------------------

def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        out[key] = value.split(" #")[0].strip().strip("'\"")
    return out


SECTIONS = [
    ("Database", ["POSTGRES_PASSWORD", "PENSINE_DB_PORT", "PENSINE_DATABASE_URL"]),
    ("Identity", ["PENSINE_OWNER_NAME", "TZ"]),
    ("Access (generated secrets — do not share)",
     ["PENSINE_DEPOSIT_TOKEN", "PENSINE_MEDIA_LINK_SECRET", "PENSINE_MEDIA_LINK_TTL_S",
      "PENSINE_WEBAPP_PASSWORD", "PENSINE_MCP_TOKEN", "PENSINE_PUBLIC_BASE_URL"]),
    ("Intelligence", ["PENSINE_LLM_BACKEND", "PENSINE_LLM_MODEL", "PENSINE_LLM_BASE_URL",
                      "PENSINE_LLM_API_KEY", "PENSINE_ANTHROPIC_API_KEY",
                      "CLAUDE_CODE_OAUTH_TOKEN", "PENSINE_OLLAMA_URL",
                      "PENSINE_OLLAMA_MODEL"]),
    ("Services", ["PENSINE_MCP_TRANSPORT", "PENSINE_EMBEDDINGS", "COMPOSE_PROFILES",
                  "SOUVENANCE_API_PORT", "SOUVENANCE_MCP_PORT", "TUNNEL_TOKEN"]),
]


def render_env(values: dict[str, str]) -> str:
    lines = ["# Written by scripts/setup.py — re-run it rather than editing by hand.",
             "# Contains secrets: this file never leaves this machine.", ""]
    seen: set[str] = set()
    for title, keys in SECTIONS:
        block = [f"{k}={values[k]}" for k in keys if k in values]
        if block:
            lines += [f"# {title}", *block, ""]
        seen.update(keys)
    rest = [f"{k}={v}" for k, v in values.items() if k not in seen]
    if rest:
        lines += ["# Other settings (kept)", *rest, ""]
    return "\n".join(lines)


def write_env(path: Path, values: dict[str, str]) -> None:
    path.write_text(render_env(values), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


# -- Questions -----------------------------------------------------------------

class Asker:
    def __init__(self, interactive: bool):
        self.interactive = interactive

    def ask(self, question: str, default: str = "") -> str:
        if not self.interactive:
            return default
        shown = f" [{default}]" if default else ""
        answer = input(f"{question}{shown}: ").strip()
        return answer or default

    def choose(self, question: str, options: list[tuple[str, str]], default: str) -> str:
        if not self.interactive:
            return default
        print(question)
        for i, (_key, label) in enumerate(options, 1):
            print(f"  {i}. {label}")
        keys = [k for k, _ in options]
        while True:
            raw = input(f"Your choice [{keys.index(default) + 1}]: ").strip()
            if not raw:
                return default
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return keys[int(raw) - 1]
            if raw in keys:
                return raw
            print("  (type the number of a line)")


# -- Network --------------------------------------------------------------------

def port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) != 0


def free_port(preferred: int, span: int = 20) -> int:
    for p in range(preferred, preferred + span):
        if port_free(p):
            return p
    return preferred


def for_container(url: str) -> str:
    """Inside a container, "localhost" is the container itself: a model
    running on the host machine is reached through host.docker.internal."""
    parts = urllib.parse.urlsplit(url)
    if parts.hostname in LOCAL_HOSTS:
        netloc = "host.docker.internal" + (f":{parts.port}" if parts.port else "")
        return urllib.parse.urlunsplit(parts._replace(netloc=netloc))
    return url


def list_models(base_url: str, api_key: str = "") -> list[str]:
    from pensine.llm import chat_completions_url
    url = chat_completions_url(base_url).removesuffix("/chat/completions") + "/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"}
                                 if api_key else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.load(resp)
    except Exception:
        return []
    return [m.get("id") for m in data.get("data") or [] if m.get("id")]


# -- Testing the AI -------------------------------------------------------------

def try_llm(settings: dict[str, str]) -> tuple[bool, str]:
    """A tiny call with these settings. (succeeded, response or error)."""
    from pensine import config, llm

    mapping = {"PENSINE_LLM_BACKEND": "LLM_BACKEND", "PENSINE_LLM_MODEL": "LLM_MODEL",
               "PENSINE_LLM_BASE_URL": "LLM_BASE_URL", "PENSINE_LLM_API_KEY": "LLM_API_KEY",
               "PENSINE_ANTHROPIC_API_KEY": "ANTHROPIC_API_KEY",
               "PENSINE_OLLAMA_URL": "OLLAMA_URL", "PENSINE_OLLAMA_MODEL": "OLLAMA_MODEL",
               "PENSINE_CLAUDE_BIN": "CLAUDE_BIN"}
    saved = {attr: getattr(config, attr) for attr in mapping.values()}
    saved_timeout, saved_token = llm.TIMEOUT_S, os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    try:
        for key, attr in mapping.items():
            if key in settings:
                setattr(config, attr, settings[key])
        if settings.get("CLAUDE_CODE_OAUTH_TOKEN"):
            os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = settings["CLAUDE_CODE_OAUTH_TOKEN"]
        llm.TIMEOUT_S = 120
        # (the test prompt stays French, like the rest of the model's prompts)
        answer = llm.complete("Réponds seulement par le mot : OK").strip()
        return (bool(answer), answer[:200] or "empty response")
    except Exception as exc:  # LLMUnavailable, network, SDK…
        return False, str(exc)[:500]
    finally:
        for attr, value in saved.items():
            setattr(config, attr, value)
        llm.TIMEOUT_S = saved_timeout
        if saved_token is None:
            os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        else:
            os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = saved_token


# -- The wizard ---------------------------------------------------------------

def configure_ai(args, ask: Asker, existing: dict[str, str]) -> dict[str, str]:
    """AI settings, as seen from the host (the test runs from here)."""
    ai = args.ai or ask.choose(
        "Which AI will do the night work (sorting, linking, summarizing)?",
        [("claude", "My Claude subscription (Pro or Max) — recommended"),
         ("api", "An API key (Anthropic, OpenAI, Mistral…)"),
         ("local", "A model running at home (LM Studio, Ollama, mlx…)")],
        "claude")
    out: dict[str, str] = {}
    if ai == "api":
        key = args.api_key or ask.ask("Paste your API key")
        if key.startswith("sk-ant-"):
            ai = "anthropic"
        else:
            provider = ask.choose("Which provider?",
                                  [("openai", "OpenAI"), ("mistral", "Mistral"),
                                   ("autre", "Other (OpenAI-compatible)")], "openai")
            args.base_url = args.base_url or PRESETS.get(provider) or \
                ask.ask("API address (often ends with /v1)")
            ai = "openai"
        args.api_key = key
    elif ai == "local":
        args.base_url = args.base_url or ask.ask(
            "Model server address", "http://localhost:1234/v1")
        ai = "openai"

    if ai == "claude":
        out["PENSINE_LLM_BACKEND"] = "claude-cli"
        out["PENSINE_LLM_MODEL"] = args.model or existing.get("PENSINE_LLM_MODEL") \
            or DEFAULT_CLAUDE_MODEL
        token = args.claude_token or existing.get("CLAUDE_CODE_OAUTH_TOKEN", "")
        if args.mode == "docker" and not token:
            print("\nInside Docker, the Claude CLI needs a subscription token:\n"
                  "  on this machine, run `claude setup-token`, sign in,\n"
                  "  then paste the token it displays here (it starts with sk-ant-oat).")
            token = ask.ask("Claude subscription token (empty = later)")
        if token:
            out["CLAUDE_CODE_OAUTH_TOKEN"] = token
    elif ai == "anthropic":
        out["PENSINE_LLM_BACKEND"] = "api"
        out["PENSINE_ANTHROPIC_API_KEY"] = args.api_key or ask.ask("Anthropic API key")
        out["PENSINE_LLM_MODEL"] = args.model or DEFAULT_CLAUDE_MODEL
    elif ai == "openai":
        base = args.base_url or ask.ask("API address", "http://localhost:1234/v1")
        key = args.api_key or ""
        model = args.model
        if not model:
            models = list_models(base, key)
            model = ask.ask("Model name" + (f" (available: {', '.join(models[:8])})"
                                               if models else ""),
                            models[0] if models else "")
        out.update(PENSINE_LLM_BACKEND="openai", PENSINE_LLM_BASE_URL=base,
                   PENSINE_LLM_MODEL=model, PENSINE_LLM_API_KEY=key)
    elif ai == "ollama":
        out.update(PENSINE_LLM_BACKEND="ollama",
                   PENSINE_OLLAMA_URL=args.base_url or "http://localhost:11434",
                   PENSINE_OLLAMA_MODEL=args.model or "qwen3")
    elif ai == "fake":
        out["PENSINE_LLM_BACKEND"] = "fake"
    else:
        raise SystemExit(f"Unknown AI: {ai} (expected: {', '.join(AI_CHOICES)})")
    return out


def build_env(args, ask: Asker, existing: dict[str, str]) -> tuple[dict, dict]:
    """(.env values, AI settings as seen from the host for the test)."""
    values = dict(existing)
    for key, nbytes in SECRET_KEYS.items():
        if not values.get(key):
            values[key] = secrets.token_hex(nbytes)

    values["PENSINE_OWNER_NAME"] = args.owner or ask.ask(
        "Your first name (the memory will refer to you this way)",
        existing.get("PENSINE_OWNER_NAME", ""))
    values["TZ"] = args.tz or existing.get("TZ") or _local_tz()

    ai = configure_ai(args, ask, existing)
    host_ai = dict(ai)
    for key in ("PENSINE_LLM_BACKEND", "PENSINE_LLM_MODEL", "PENSINE_LLM_BASE_URL",
                "PENSINE_LLM_API_KEY", "PENSINE_ANTHROPIC_API_KEY",
                "CLAUDE_CODE_OAUTH_TOKEN", "PENSINE_OLLAMA_URL", "PENSINE_OLLAMA_MODEL"):
        values.pop(key, None)
    if args.mode == "docker":
        for key in ("PENSINE_LLM_BASE_URL", "PENSINE_OLLAMA_URL"):
            if ai.get(key):
                ai[key] = for_container(ai[key])
    values.update(ai)

    if args.public_url is None:
        args.public_url = ask.ask(
            "Public HTTPS address (Cloudflare tunnel, e.g. https://memory.example.org;"
            " empty = this machine only)", existing.get("PENSINE_PUBLIC_BASE_URL", ""))
    public = (args.public_url or "").rstrip("/")

    tunnel = args.tunnel_token or existing.get("TUNNEL_TOKEN", "")
    if args.mode == "docker" and public and not tunnel and args.tunnel_token is None:
        tunnel = ask.ask("Cloudflare tunnel token (empty = I expose it another way)")

    port = int(existing.get("PENSINE_DB_PORT") or 0) or free_port(5432)
    values["PENSINE_DB_PORT"] = str(port)
    values["PENSINE_DATABASE_URL"] = (
        f"postgresql://pensine:{values['POSTGRES_PASSWORD']}@127.0.0.1:{port}/pensine")
    values.setdefault("PENSINE_MEDIA_LINK_TTL_S", "900")
    values.setdefault("PENSINE_EMBEDDINGS", "1")
    values["PENSINE_MCP_TRANSPORT"] = "streamable-http"
    if args.mode == "docker":
        values["SOUVENANCE_API_PORT"] = existing.get("SOUVENANCE_API_PORT") or str(free_port(8300))
        values["SOUVENANCE_MCP_PORT"] = existing.get("SOUVENANCE_MCP_PORT") or str(free_port(8400))
        values["COMPOSE_PROFILES"] = "app,tunnel" if tunnel else "app"
    if tunnel:
        values["TUNNEL_TOKEN"] = tunnel
    api_port = values.get("SOUVENANCE_API_PORT", "8300")
    values["PENSINE_PUBLIC_BASE_URL"] = public or f"http://localhost:{api_port}"
    return values, host_ai


def _local_tz() -> str:
    tz = os.environ.get("TZ", "")
    if tz:
        return tz
    try:  # /etc/localtime → …/zoneinfo/Europe/Paris
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return "UTC"


def summary(values: dict[str, str], mode: str) -> str:
    public = values["PENSINE_PUBLIC_BASE_URL"]
    local_only = public.startswith("http://localhost")
    mcp_base = (f"http://localhost:{values.get('SOUVENANCE_MCP_PORT', '8400')}"
                if local_only else public)
    mcp_url = f"{mcp_base}/mcp/{values['PENSINE_MCP_TOKEN']}"
    start = ("docker compose up -d --build" if mode == "docker"
             else "./install.sh   (Linux server)")
    lines = [
        "",
        "Ready. Start with:",
        f"    {start}",
        "",
        "1. Connect Claude (or ChatGPT) — add a custom connector:",
        f"    {mcp_url}",
        "   (this address contains your key: share it with no one)",
    ]
    if local_only:
        lines.append("   claude.ai and ChatGPT require a public HTTPS address: "
                     "see docs/installer-chez-soi.md, \"tunnel\" step.")
    lines += [
        "",
        "2. iOS shortcut \"Pensine\" (deposit a voice note, a photo, a PDF):",
        f"    URL     : {public}/deposit   (POST method, \"file\" field)",
        f"    Header  : Authorization = Bearer {values['PENSINE_DEPOSIT_TOKEN']}",
        "",
        "3. Your timeline, in the browser:",
        f"    {public}/app   — password: {values['PENSINE_WEBAPP_PASSWORD']}",
        "",
        "This information stays in the .env file; re-run this wizard "
        "to display it again.",
    ]
    return "\n".join(lines)


def parse_args(argv):
    p = argparse.ArgumentParser(prog="souvenance setup", description=__doc__.split("\n")[0])
    p.add_argument("--ai", choices=AI_CHOICES + ("api", "local"),
                   help="claude (subscription), anthropic (key), openai (OpenAI-"
                        "compatible, local or online), ollama, fake (trial)")
    p.add_argument("--api-key", default="")
    p.add_argument("--base-url", default="", help="address of the model server")
    p.add_argument("--model", default="")
    p.add_argument("--claude-token", default="", help="token from `claude setup-token`")
    p.add_argument("--owner", default=None, help="your first name")
    p.add_argument("--public-url", default=None, help="public HTTPS address")
    p.add_argument("--tunnel-token", default=None, help="Cloudflare tunnel token")
    p.add_argument("--tz", default="", help="timezone (e.g. Europe/Paris)")
    p.add_argument("--mode", choices=("docker", "native"), default="docker")
    p.add_argument("--env-file", type=Path, default=ENV_PATH)
    p.add_argument("--no-test", action="store_true", help="do not test the AI")
    p.add_argument("--yes", "-y", action="store_true",
                   help="ask nothing (options and defaults)")
    return p.parse_args(argv)


def setup(argv=None) -> int:
    args = parse_args(argv)
    ask = Asker(interactive=not args.yes and sys.stdin.isatty())
    existing = read_env(args.env_file)
    if existing:
        print(f"{args.env_file} exists: its secrets are kept, the rest is updated.")
    values, host_ai = build_env(args, ask, existing)

    if args.no_test:
        print("AI test: skipped (--no-test).")
    elif host_ai.get("PENSINE_LLM_BACKEND") == "claude-cli" and args.mode == "docker" \
            and not _has_claude_cli():
        print("AI test: the Claude CLI is not on this machine; it will be\n"
              "inside the container. After startup:\n"
              "    docker compose run --rm api python -m pensine.setup_wizard check")
    else:
        print("Testing the AI (one tiny call)…")
        ok, detail = try_llm(host_ai)
        print(("  Response: " if ok else "  Failure: ") + detail)
        if not ok:
            print("  The configuration is written anyway: fix it and re-run,\n"
                  "  or run `python -m pensine.setup_wizard check` later.")

    write_env(args.env_file, values)
    print(f"Configuration written: {args.env_file}")
    print(summary(values, args.mode))
    return 0


def _has_claude_cli() -> bool:
    import shutil
    return shutil.which(os.environ.get("PENSINE_CLAUDE_BIN", "claude")) is not None


def check() -> int:
    """Test the AI with the configuration in place (.env, environment)."""
    from pensine import config
    print(f"Backend: {config.LLM_BACKEND} — model: {config.LLM_MODEL or config.OLLAMA_MODEL}")
    ok, detail = try_llm({})
    print(("Response: " if ok else "Failure: ") + detail)
    return 0 if ok else 1


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["check"]:
        return check()
    if argv[:1] == ["setup"]:
        argv = argv[1:]
    return setup(argv)


if __name__ == "__main__":
    sys.exit(main())
