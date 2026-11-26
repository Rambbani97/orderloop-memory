"""Client factory shared by the CLI harness and the demo server.

Credentials are NEVER read from env vars or files here. The real clients
call the registered connector CLIs (``custom.meko`` / ``custom.gemini``)
as subprocesses; those CLIs hold the keys in the Secure Vault. When a
connector CLI is missing, ``auto`` falls back to the test doubles (stub LLM
/ FakeMeko) with a loud banner so nobody mistakes a smoke test for a real
run. Explicit ``gemini`` / ``real`` requests raise loudly instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.kb import LocalKB
from app.llm import GEMINI_CLI, make_llm_client
from app.meko_client import MEKO_CLI, MekoConfig, make_meko_client

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def build_kb() -> LocalKB:
    return LocalKB(DATA_DIR / "kb")


def build_llm(kind: str = "auto"):
    """kind: auto | gemini | stub.

    auto: Gemini (via the connector CLI) when the CLI exists, otherwise the
    deterministic stub (smoke tests / demo without credentials).
    """
    if kind == "auto":
        if Path(GEMINI_CLI).is_file():
            kind = "gemini"
        else:
            print("WARNING: Gemini connector CLI not found — falling back to "
                  "the stub LLM (smoke test only, no real model).", file=sys.stderr)
            kind = "stub"
    return make_llm_client(kind)


def build_meko(condition: str, kind: str = "auto", kb: LocalKB | None = None):
    """kind: auto | real | fake | null.

    auto: real Meko Cloud (via the connector CLI) when the CLI exists
    (condition B), otherwise FakeMeko (condition B) or NullMeko (condition A).
    """
    if kind == "auto":
        if condition == "A":
            kind = "null"
        elif Path(MEKO_CLI).is_file():
            kind = "real"
        else:
            print("WARNING: Meko connector CLI not found — falling back to "
                  "FakeMeko (smoke test only, no cloud quota used).",
                  file=sys.stderr)
            kind = "fake"
    if kind == "real":
        config = MekoConfig.from_env()
        return make_meko_client(condition, "real", config, kb)
    return make_meko_client(condition, kind, MekoConfig.from_env(), kb)


def describe_setup(llm, meko) -> dict:
    """One-line summary of what this run is actually using (for logs/UI)."""
    if meko is None:
        return {"llm": getattr(llm, "model", str(type(llm).__name__)),
                "meko": "not connected yet",
                "datapack_id": "",
                "quota_note": "Meko client is created lazily per condition"}
    return {
        "llm": getattr(llm, "model", str(type(llm).__name__)),
        "meko": type(meko).__name__,
        "datapack_id": getattr(getattr(meko, "config", None), "datapack_id", "") or "",
        "quota_note": ("FAKE MEKO — in-memory test double, no cloud quota used"
                       if type(meko).__name__ == "FakeMekoClient"
                       else "NULL MEKO — condition A, no Meko calls"
                       if type(meko).__name__ == "NullMekoClient"
                       else "MEKO CLOUD — real quota consumed"),
    }
