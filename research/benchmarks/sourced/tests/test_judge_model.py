"""ModelJudge transports."""

import json


def test_claude_cli_transport_is_lean_and_unwraps_the_result(monkeypatch):
    """The judge on the user's subscription: no tool, no MCP server, no
    session, an empty working directory; the CLI's JSON envelope unwrapped."""
    import subprocess
    from sourced import judge
    seen = {}

    class P:
        returncode, stderr = 0, ""
        stdout = json.dumps({"result": '{"support": "supported"}'})

    def run(cmd, **kw):
        seen["cmd"], seen["cwd"] = cmd, kw.get("cwd")
        return P()
    monkeypatch.setattr(subprocess, "run", run)
    send = judge.claude_cli_transport("claude-sonnet-5-5")
    out = send({"messages": [{"role": "user", "content": "PROMPT"}]})
    assert out["choices"][0]["message"]["content"] == '{"support": "supported"}'
    cmd = seen["cmd"]
    assert cmd[:3] == ["claude", "-p", "PROMPT"] and "claude-sonnet-5-5" in cmd
    assert cmd[cmd.index("--tools") + 1] == "" and "--strict-mcp-config" in cmd
    assert "--no-session-persistence" in cmd and "--system-prompt" in cmd
    import os
    assert seen["cwd"] and os.listdir(seen["cwd"]) == []


def test_the_judge_is_told_who_wrote_each_deposit():
    """A friend's "my dog" is the friend's: the prompt names author and recipient."""
    from sourced.judge import ModelJudge
    truth = {"owner": "P0", "facts": [], "traps": [],
             "people": [{"id": "P0", "name": "Anton Kowalski"},
                        {"id": "P1", "name": "Vera Novak", "relation": "sister"}]}
    deps = [{"id": "D1", "kind": "voice_in", "created_at": "2025-02-06T09:00:00",
             "author": "P1", "recipient": "P0", "text": "My dog Otis woke me up at six again."}]
    seen = {}

    def transport(body):
        seen["prompt"] = body["messages"][-1]["content"]
        return {"choices": [{"message": {"content": '{"support": "supported", "facts": []}'}}]}
    j = ModelJudge(truth, deps, "http://stub", "stub", transport=transport)
    j.label({"content": "Vera Novak has a dog named Otis.",
             "citations": [{"deposit_id": "D1", "excerpt": "My dog Otis woke me up"}]})
    assert '"from": "Vera Novak"' in seen["prompt"] and '"to": "Anton Kowalski"' in seen["prompt"]

