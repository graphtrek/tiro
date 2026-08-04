"""Validation for the web terminal (web.py).

    uv run python test_web.py

Builds a throwaway vault in a temp dir, boots the FastAPI app with the real
lifespan (headroom off), then swaps the session's agent for a stub so every
check runs without a model or API calls.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Must be set before web (via cli/main) loads .env: env vars win over .env values.
os.environ["HEADROOM"] = "0"
os.environ["LOG_LEVEL"] = "OFF"

from test_agent import check, make_vault


class _StubUsage:
    requests = 2


class _StubResult:
    output = "Use a **1:16** ratio. Source: [[Coffee Brewing]]"

    def __init__(self) -> None:
        self.usage = _StubUsage()

    def new_messages(self):
        from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

        return [
            ModelResponse(
                parts=[
                    ToolCallPart(tool_name="search_vault", args={"query": "coffee ratio"}),
                    TextPart(content=self.output),
                ]
            )
        ]

    def all_messages(self):
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        return [ModelRequest(parts=[UserPromptPart(content="ratio?")]), *self.new_messages()]


class _StubAgent:
    def run_sync(self, prompt, message_history=None, usage_limits=None):
        return _StubResult()


def main() -> None:
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        vault_dir = base / "coffee"
        vault_dir.mkdir()
        make_vault(vault_dir)
        os.environ["VAULT_PATH"] = str(base)
        os.environ["VAULT_NAME"] = "coffee"

        import web
        from fastapi.testclient import TestClient

        print("web terminal tests (no API):")
        with TestClient(web.app) as client:
            ok &= check("lifespan builds the session", web.SESSION is not None)
            ok &= check("no headroom proxy with HEADROOM=0", web.SESSION.proxy is None)
            web.SESSION.agent = _StubAgent()

            r = client.get("/")
            ok &= check("GET / serves the page", r.status_code == 200 and "you ›" in r.text)
            ok &= check(
                "served page turns [[wikilinks]] in note text into clickable /?read= links",
                "convertWikilinks" in r.text and "/?read=" in r.text,
            )

            s = client.get("/api/status").json()
            ok &= check("status names the vault", s["vault_name"] == "coffee")
            ok &= check("status counts the notes", s["notes"] == 3)
            ok &= check("status reports model and prompt", bool(s["model"]) and bool(s["prompt_file"]))
            ok &= check("status reports headroom off", s["headroom"] is None)

            def post(msg: str):
                return client.post("/api/message", json={"message": msg})

            r = post("/help").json()
            ok &= check("/help returns info with the commands", r["kind"] == "info" and "/save-note" in r["markdown"])
            r = post("/").json()
            ok &= check("bare / is help too", r["kind"] == "info" and "Commands" in r["markdown"])

            r = post("/notes").json()
            ok &= check("/notes lists the vault's notes", r["kind"] == "info" and "Coffee Brewing" in r["markdown"])

            r = post("/graph").json()
            ok &= check(
                "/graph reports counts and signals the frontend to open a tab",
                r["kind"] == "info" and r["open_graph"] is True and "notes" in r["markdown"],
            )
            gr = client.get("/graph")
            ok &= check("GET /graph serves the graph page", gr.status_code == 200 and "coffee" in gr.text)
            ok &= check("GET /graph embeds the vault's notes as graph nodes", "Coffee Brewing" in gr.text)
            ok &= check(
                "GET /graph links back to the terminal at /",
                '<a class="back" href="/"' in gr.text,
            )
            ok &= check(
                "the back link targets a named tab so it never replaces the graph's own tab",
                'target="vault-agent-terminal"' in gr.text,
            )

            r = post("/read Coffee Brewing").json()
            ok &= check("/read returns the note text", r["kind"] == "info" and "1:16" in r["markdown"])
            r = post("/read 1").json()
            ok &= check("/read by /notes ID works", r["kind"] == "info" and "1:16" in r["markdown"])
            r = post("/read 99").json()
            ok &= check("/read with an out-of-range ID falls back to name lookup", "No note named '99'" in r["markdown"])
            r = post("/read").json()
            ok &= check("/read without a name is an error", r["kind"] == "error" and "usage" in r["error"])

            r = post("/prompt").json()
            ok &= check("/prompt shows the prompt file", r["kind"] == "info" and "system_prompt.md" in r["markdown"])

            r = post("/vault").json()
            ok &= check("/vault lists vaults with the active one marked", r["kind"] == "info" and "● active" in r["markdown"])
            r = post("/model").json()
            ok &= check("/model lists providers", r["kind"] == "info" and "gemma-mlx" in r["markdown"])

            r = post("/valut").json()
            ok &= check("a typo command never reaches the model", r["kind"] == "error" and "unknown command: /valut" in r["error"])
            r = post("/exit").json()
            ok &= check("/exit is rejected on the web", r["kind"] == "error")
            r = post("   ").json()
            ok &= check("blank input is an error", r["kind"] == "error")

            r = post("/save-note Nope").json()
            ok &= check("/save-note before any turn is an error", r["kind"] == "error" and "nothing to save" in r["error"])

            r = post("What ratio should I use?").json()
            ok &= check("a question returns an answer", r["kind"] == "answer" and "1:16" in r["markdown"])
            ok &= check("answer lists the tools used", r["tools"][0]["tool"] == "search_vault")
            ok &= check("answer reports round-trips and wall time", r["requests"] == 2 and r["wall_ms"] >= 0)
            ok &= check("turn extends the session history", len(web.SESSION.history) == 2)

            r = post("/save-note Web Answer").json()
            ok &= check("/save-note saves the last answer", r["kind"] == "info" and "Web Answer" in r["markdown"])
            ok &= check("saved note lands in the vault", (vault_dir / "Web Answer.md").is_file())
            ok &= check("saved note keeps the answer text", "1:16" in (vault_dir / "Web Answer.md").read_text(encoding="utf-8"))

            r = post("/clear").json()
            ok &= check("/clear empties the history", r["kind"] == "info" and web.SESSION.history == [])

            web.TURN_LOCK.acquire()
            try:
                r = post("hello")
                ok &= check("a message during a running turn gets 409", r.status_code == 409 and r.json()["kind"] == "error")
            finally:
                web.TURN_LOCK.release()

    print("\n", "ALL PASSED" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
