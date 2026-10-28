"""Setup wizard, without a terminal: options only, secrets
generated then kept, addresses reachable from the containers."""

import subprocess
import sys
from pathlib import Path

from pensine import setup_wizard as w

ROOT = Path(__file__).resolve().parent.parent


def _run(tmp_path, *args):
    env = tmp_path / ".env"
    code = w.main(["--yes", "--env-file", str(env), "--public-url", "", *args])
    assert code == 0
    return w.read_env(env), env


def test_genere_tous_les_secrets(tmp_path, capsys):
    values, env = _run(tmp_path, "--ai", "fake", "--owner", "Camille")
    for key, nbytes in w.SECRET_KEYS.items():
        assert len(values[key]) == 2 * nbytes, key
    assert values["PENSINE_OWNER_NAME"] == "Camille"
    assert values["PENSINE_LLM_BACKEND"] == "fake"
    assert values["COMPOSE_PROFILES"] == "app"
    assert values["POSTGRES_PASSWORD"] in values["PENSINE_DATABASE_URL"]
    assert env.stat().st_mode & 0o777 == 0o600
    out = capsys.readouterr().out
    assert f"/mcp/{values['PENSINE_MCP_TOKEN']}" in out
    assert f"Bearer {values['PENSINE_DEPOSIT_TOKEN']}" in out
    assert "Response" in out  # the AI was tried


def test_relance_garde_les_secrets_et_le_reste(tmp_path):
    first, env = _run(tmp_path, "--ai", "fake")
    env.write_text(env.read_text() + "PENSINE_CALENDAR_ICS_URLS=https://agenda.example/x.ics\n")
    second, _ = _run(tmp_path, "--ai", "fake", "--owner", "Camille")
    for key in w.SECRET_KEYS:
        assert first[key] == second[key]
    assert second["PENSINE_CALENDAR_ICS_URLS"] == "https://agenda.example/x.ics"


def test_modele_local_joint_depuis_docker(tmp_path):
    values, _ = _run(tmp_path, "--ai", "openai", "--base-url", "http://localhost:1234/v1",
                     "--model", "qwen3", "--no-test")
    assert values["PENSINE_LLM_BACKEND"] == "openai"
    assert values["PENSINE_LLM_BASE_URL"] == "http://host.docker.internal:1234/v1"
    assert values["PENSINE_LLM_MODEL"] == "qwen3"


def test_mode_natif_garde_localhost(tmp_path):
    values, _ = _run(tmp_path, "--mode", "native", "--ai", "openai", "--base-url",
                     "http://127.0.0.1:8080", "--model", "m", "--no-test")
    assert values["PENSINE_LLM_BASE_URL"] == "http://127.0.0.1:8080"
    assert "COMPOSE_PROFILES" not in values


def test_cle_anthropic_reconnue(tmp_path):
    values, _ = _run(tmp_path, "--ai", "api", "--api-key", "sk-ant-api03-xyz", "--no-test")
    assert values["PENSINE_LLM_BACKEND"] == "api"
    assert values["PENSINE_ANTHROPIC_API_KEY"] == "sk-ant-api03-xyz"


def test_autre_cle_compatible_openai(tmp_path):
    values, _ = _run(tmp_path, "--ai", "api", "--api-key", "sk-proj-abc", "--model",
                     "gpt-5-mini", "--no-test")
    assert values["PENSINE_LLM_BACKEND"] == "openai"
    assert values["PENSINE_LLM_BASE_URL"] == "https://api.openai.com/v1"
    assert values["PENSINE_LLM_API_KEY"] == "sk-proj-abc"


def test_abonnement_claude_avec_tunnel(tmp_path, capsys):
    values, _ = _run(tmp_path, "--ai", "claude", "--claude-token", "sk-ant-oat01-x",
                     "--tunnel-token", "eyJhIjoi", "--no-test")
    assert values["PENSINE_LLM_BACKEND"] == "claude-cli"
    assert values["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-x"
    assert values["COMPOSE_PROFILES"] == "app,tunnel"
    assert values["TUNNEL_TOKEN"] == "eyJhIjoi"


def test_adresse_publique(tmp_path, capsys):
    env = tmp_path / ".env"
    w.main(["--yes", "--env-file", str(env), "--ai", "fake",
            "--public-url", "https://memoire.example.org/"])
    values = w.read_env(env)
    assert values["PENSINE_PUBLIC_BASE_URL"] == "https://memoire.example.org"
    out = capsys.readouterr().out
    assert f"https://memoire.example.org/mcp/{values['PENSINE_MCP_TOKEN']}" in out
    assert "https://memoire.example.org/deposit" in out


def test_echec_de_l_ia_n_empeche_pas_d_ecrire(tmp_path, capsys):
    values, env = _run(tmp_path, "--ai", "openai", "--base-url", "http://127.0.0.1:9",
                       "--model", "m")
    assert env.exists() and values["PENSINE_LLM_BACKEND"] == "openai"
    assert "Failure" in capsys.readouterr().out


def test_essai_ne_laisse_pas_de_trace_dans_la_config(tmp_path):
    from pensine import config
    before = config.LLM_BACKEND
    _run(tmp_path, "--ai", "fake")
    assert config.LLM_BACKEND == before


def test_script_sans_dependances(tmp_path):
    """The script runs with plain Python only, outside any environment."""
    env = tmp_path / ".env"
    proc = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "setup.py"),
                           "--yes", "--ai", "fake", "--public-url", "",
                           "--env-file", str(env)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "PENSINE_MCP_TOKEN=" in env.read_text()
