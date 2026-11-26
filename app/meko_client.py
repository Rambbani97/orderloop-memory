"""Meko clients for OrderLoop agents.

Three implementations, one interface:

- :class:`MekoCLIClient` — the real thing: it shells out to the registered
  connector CLI (``custom.meko``, ``bin/client.py``) for every tool call.
  The API key lives only in the Secure Vault; this module never sees it,
  never reads it from env vars or files, and never passes it in arguments
  or environment. One subprocess per tool call; each call writes its JSON
  arguments to a temporary file that is deleted afterwards.
- :class:`NullMekoClient` — condition A (baseline): every call is a no-op
  that records itself. Used to prove condition A never touches Meko.
- :class:`FakeMekoClient` — in-memory test double for smoke tests and the
  demo server when no key is configured. Memories/KB/conversations live in
  dicts; ``context_search`` scores by token overlap.

No key is ever written to a file by this module. ``MekoCLIClient`` raises
:class:`MekoConfigError` immediately when the connector CLI is missing.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.kb import LocalKB, tokenize

DEFAULT_MCP_URL = "https://mcp.mekodata.ai/mcp"
USER_AGENT = "orderloop-memory/1.0"
MEKO_CLI = Path.home() / "workspace" / "custom-connectors" / "custom.meko" / "bin" / "client.py"
# All Meko conversations are created under this agent id (the cross-project
# bucket). The MCP schema requires conversation_add_message to use the same
# agent_id as conversation_create; per-call agent attribution (triage vs
# specialist) still travels on memory_add / context_search themselves.
CONVERSATION_AGENT_ID = "meko_agent"


class MekoConfigError(RuntimeError):
    """Raised when Meko is requested without a usable configuration."""


@dataclass
class MekoConfig:
    datapack_id: str = ""
    mcp_url: str = DEFAULT_MCP_URL
    user_agent: str = USER_AGENT
    cli: str | Path = MEKO_CLI

    @classmethod
    def from_env(cls) -> "MekoConfig":
        # NOTE: no API key here, ever. The key lives in the Secure Vault and
        # only the registered connector CLI may use it (via subprocess).
        return cls(
            datapack_id=os.environ.get("MEKO_DATAPACK_ID", ""),
            mcp_url=os.environ.get("MEKO_MCP_URL", DEFAULT_MCP_URL),
            cli=os.environ.get("MEKO_CLI", str(MEKO_CLI)),
        )


class BaseMekoClient:
    """Interface used by agents and the harness."""

    def __init__(self, config: MekoConfig | None = None):
        self.config = config or MekoConfig()
        self.calls: list[dict] = []  # every tool call, for protocol auditing

    def _record(self, tool: str, args: dict) -> None:
        self.calls.append({"tool": tool, "args": args})

    def context_search(self, query: str, limit: int = 10, conversation_id: str = "",
                       agent_id: str = "") -> dict:
        raise NotImplementedError

    def memory_add(self, text: str, metadata: dict | None = None, agent_id: str = "") -> dict:
        raise NotImplementedError

    def memory_search(self, query: str, limit: int = 10, agent_id: str = "") -> dict:
        raise NotImplementedError

    def memory_get_all(self, promoted: bool = False, agent_id: str = "") -> dict:
        raise NotImplementedError

    def memory_get_by_id(self, memory_id: str, agent_id: str = "") -> dict:
        raise NotImplementedError

    def knowledgebase_search(self, query: str, limit: int = 5, agent_id: str = "") -> dict:
        raise NotImplementedError

    def knowledgebase_upload_document(self, name: str, text: str, agent_id: str = "") -> dict:
        raise NotImplementedError

    def knowledgebase_document_status(self, document_key: str, agent_id: str = "") -> dict:
        raise NotImplementedError

    def conversation_create(self, agent_id: str = "") -> dict:
        raise NotImplementedError

    def conversation_add_message(self, conversation_id: str, user_message: str,
                                 agent_reply: str, agent_id: str = "",
                                 reasoning: list | None = None, plan: list | None = None) -> dict:
        raise NotImplementedError

    def conversation_capture(self, conversation_id: str, messages: list[dict],
                             agent_id: str = "") -> dict:
        """Store one ticket exchange (user + assistant messages) as a turn."""
        raise NotImplementedError

    def track_token_usage(self, conversation_id: str, name: str, input_tokens: int,
                          output_tokens: int, model: str, agent_id: str = "") -> dict:
        raise NotImplementedError

    def datapack_create(self, name: str, description: str = "") -> dict:
        raise NotImplementedError

    def datapack_list(self) -> dict:
        raise NotImplementedError

    def datapack_describe(self, datapack_id: str) -> dict:
        raise NotImplementedError

    def memory_promote(self, memory_ids: list[str], agent_id: str = "") -> dict:
        raise NotImplementedError

    def close(self) -> None:
        pass


class NullMekoClient(BaseMekoClient):
    """Condition A: Meko is never called. Every method records + no-ops."""

    def _disabled(self, tool: str, args: dict) -> dict:
        self._record(tool, args)
        return {"ok": False, "disabled": True,
                "reason": "condition A (baseline) — Meko is not used"}

    def context_search(self, query: str, limit: int = 10, conversation_id: str = "",
                       agent_id: str = "") -> dict:
        self._record("context_search", {"query": query})
        return {"ok": True, "disabled": True, "buckets": {"memory": [], "knowledge_base": [],
                                                          "conversation": []},
                "match_quality": "none", "agent_hint": "Meko disabled in condition A."}

    def memory_add(self, text: str, metadata: dict | None = None, agent_id: str = "") -> dict:
        return self._disabled("memory_add", {"text": text[:80]})

    def memory_search(self, query: str, limit: int = 10, agent_id: str = "") -> dict:
        return self._disabled("memory_search", {"query": query})

    def memory_get_all(self, promoted: bool = False, agent_id: str = "") -> dict:
        return self._disabled("memory_get_all", {"promoted": promoted})

    def memory_get_by_id(self, memory_id: str, agent_id: str = "") -> dict:
        return self._disabled("memory_get_by_id", {"memory_id": memory_id})

    def knowledgebase_search(self, query: str, limit: int = 5, agent_id: str = "") -> dict:
        return self._disabled("knowledgebase_search", {"query": query})

    def knowledgebase_upload_document(self, name: str, text: str, agent_id: str = "") -> dict:
        return self._disabled("knowledgebase_upload_document", {"name": name})

    def knowledgebase_document_status(self, document_key: str, agent_id: str = "") -> dict:
        return self._disabled("knowledgebase_document_status",
                              {"document_key": document_key})

    def conversation_create(self, agent_id: str = "") -> dict:
        return self._disabled("conversation_create", {})

    def conversation_add_message(self, conversation_id: str, user_message: str,
                                 agent_reply: str, agent_id: str = "",
                                 reasoning: list | None = None, plan: list | None = None) -> dict:
        return self._disabled("conversation_add_message", {"conversation_id": conversation_id})

    def conversation_capture(self, conversation_id: str, messages: list[dict],
                             agent_id: str = "") -> dict:
        return self._disabled("conversation_capture", {"conversation_id": conversation_id})

    def track_token_usage(self, conversation_id: str, name: str, input_tokens: int,
                          output_tokens: int, model: str, agent_id: str = "") -> dict:
        return self._disabled("track_token_usage", {"conversation_id": conversation_id})

    def datapack_create(self, name: str, description: str = "") -> dict:
        return self._disabled("datapack_create", {"name": name})

    def datapack_list(self) -> dict:
        return self._disabled("datapack_list", {})

    def datapack_describe(self, datapack_id: str) -> dict:
        return self._disabled("datapack_describe", {"datapack_id": datapack_id})

    def memory_promote(self, memory_ids: list[str], agent_id: str = "") -> dict:
        return self._disabled("memory_promote", {"memory_ids": memory_ids})


class FakeMekoClient(BaseMekoClient):
    """In-memory Meko for smoke tests / demo mode without credentials."""

    def __init__(self, config: MekoConfig | None = None, kb: LocalKB | None = None):
        super().__init__(config)
        self.memories: list[dict] = []
        self.conversations: dict[str, list[dict]] = {}
        self.token_usage: list[dict] = []
        self.datapacks: dict[str, dict] = {"fake-default": {"datapack_id": "fake-default",
                                                            "name": "fake-default"}}
        self.kb = kb
        self._mem_seq = 0
        self._conv_seq = 0

    def _score(self, query: str, text: str) -> int:
        return len(tokenize(query) & tokenize(text))

    def context_search(self, query: str, limit: int = 10, conversation_id: str = "",
                       agent_id: str = "") -> dict:
        self._record("context_search", {"query": query})
        mem_hits = []
        for mem in self.memories:
            score = self._score(query, mem["text"])
            if score > 0:
                mem_hits.append({"memory_id": mem["id"], "text": mem["text"],
                                 "score": score, "metadata": mem.get("metadata", {})})
        mem_hits.sort(key=lambda h: -h["score"])
        kb_hits = []
        if self.kb is not None:
            for doc in self.kb.search(query, limit=limit):
                kb_hits.append({"id": doc["id"], "title": doc["title"],
                                "excerpt": doc["excerpt"], "score": doc["score"]})
        conv_hits = []
        for conv_id, turns in self.conversations.items():
            for turn in turns:
                score = self._score(query, turn.get("user_message", "") + " " + turn.get("agent_reply", ""))
                if score > 0:
                    conv_hits.append({"conversation_id": conv_id, "score": score,
                                      "excerpt": turn.get("agent_reply", "")[:300]})
        conv_hits.sort(key=lambda h: -h["score"])
        top_mem = mem_hits[0]["score"] if mem_hits else 0
        quality = "high" if top_mem >= 4 else ("medium" if top_mem >= 2 else "low")
        hint = ("Strong memory match — reuse it and cite it." if quality == "high"
                else "Weak or no memory match — solve from the knowledge base." if quality == "low"
                else "Possible memory match — check whether it really applies.")
        return {"ok": True, "buckets": {"memory": mem_hits[:limit],
                                         "knowledge_base": kb_hits,
                                         "conversation": conv_hits[:limit]},
                "match_quality": quality, "agent_hint": hint}

    def memory_add(self, text: str, metadata: dict | None = None, agent_id: str = "") -> dict:
        self._record("memory_add", {"text": text[:80]})
        self._mem_seq += 1
        mem_id = f"mem-{self._mem_seq:03d}"
        self.memories.append({"id": mem_id, "text": text,
                              "metadata": metadata or {}, "promoted": False})
        return {"ok": True, "memory_id": mem_id}

    def memory_search(self, query: str, limit: int = 10, agent_id: str = "") -> dict:
        self._record("memory_search", {"query": query})
        hits = [m for m in self.memories if self._score(query, m["text"]) > 0]
        hits.sort(key=lambda m: -self._score(query, m["text"]))
        return {"ok": True, "results": hits[:limit]}

    def memory_get_all(self, promoted: bool = False, agent_id: str = "") -> dict:
        self._record("memory_get_all", {"promoted": promoted})
        mems = [m for m in self.memories if bool(m.get("promoted")) == promoted]
        return {"ok": True, "results": mems}

    def memory_get_by_id(self, memory_id: str, agent_id: str = "") -> dict:
        self._record("memory_get_by_id", {"memory_id": memory_id})
        for m in self.memories:
            if m["id"] == memory_id:
                return {"ok": True, **m}
        return {"ok": False, "error": "memory not found"}

    def knowledgebase_search(self, query: str, limit: int = 5, agent_id: str = "") -> dict:
        self._record("knowledgebase_search", {"query": query})
        if self.kb is None:
            return {"ok": True, "results": []}
        return {"ok": True, "results": self.kb.search(query, limit=limit)}

    def knowledgebase_upload_document(self, name: str, text: str, agent_id: str = "") -> dict:
        self._record("knowledgebase_upload_document", {"name": name})
        if self.kb is not None:
            self.kb.docs.append({"id": name, "title": name, "path": f"fake://{name}",
                                 "text": text, "tokens": tokenize(name + " " + text)})
        return {"ok": True, "status": "completed", "document_id": f"kb-{name}"}

    def knowledgebase_document_status(self, document_key: str, agent_id: str = "") -> dict:
        self._record("knowledgebase_document_status", {"document_key": document_key})
        return {"ok": True, "status": "completed", "document_key": document_key}

    def conversation_create(self, agent_id: str = "") -> dict:
        self._record("conversation_create", {})
        self._conv_seq += 1
        conv_id = f"conv-{self._conv_seq:03d}"
        self.conversations[conv_id] = []
        return {"ok": True, "conversation_id": conv_id}

    def conversation_add_message(self, conversation_id: str, user_message: str,
                                 agent_reply: str, agent_id: str = "",
                                 reasoning: list | None = None, plan: list | None = None) -> dict:
        self._record("conversation_add_message", {"conversation_id": conversation_id})
        self.conversations.setdefault(conversation_id, []).append(
            {"user_message": user_message, "agent_reply": agent_reply,
             "reasoning": reasoning or [], "plan": plan or []})
        return {"ok": True}

    def conversation_capture(self, conversation_id: str, messages: list[dict],
                             agent_id: str = "") -> dict:
        self._record("conversation_capture", {"conversation_id": conversation_id})
        user_msg = next((m.get("content", "") for m in messages
                         if m.get("role") == "user"), "")
        asst_msg = next((m.get("content", "") for m in reversed(messages)
                         if m.get("role") == "assistant"), "")
        return self.conversation_add_message(conversation_id, user_msg, asst_msg,
                                             agent_id=agent_id)

    def track_token_usage(self, conversation_id: str, name: str, input_tokens: int,
                          output_tokens: int, model: str, agent_id: str = "") -> dict:
        self._record("track_token_usage", {"conversation_id": conversation_id})
        self.token_usage.append({"conversation_id": conversation_id, "name": name,
                                 "input_tokens": input_tokens, "output_tokens": output_tokens,
                                 "total_tokens": input_tokens + output_tokens, "model": model})
        return {"ok": True}

    def datapack_create(self, name: str, description: str = "") -> dict:
        self._record("datapack_create", {"name": name})
        dp_id = f"fake-{name}"
        self.datapacks[dp_id] = {"datapack_id": dp_id, "name": name, "description": description}
        return {"ok": True, "datapack_id": dp_id, "name": name}

    def datapack_list(self) -> dict:
        self._record("datapack_list", {})
        return {"ok": True, "datapacks": list(self.datapacks.values())}

    def datapack_describe(self, datapack_id: str) -> dict:
        self._record("datapack_describe", {"datapack_id": datapack_id})
        dp = self.datapacks.get(datapack_id)
        if dp is None:
            return {"ok": False, "error": "datapack not found"}
        return {"ok": True, **dp}

    def memory_promote(self, memory_ids: list[str], agent_id: str = "") -> dict:
        self._record("memory_promote", {"memory_ids": memory_ids})
        promoted = []
        for mem in self.memories:
            if mem["id"] in memory_ids:
                mem["promoted"] = True
                promoted.append(mem["id"])
        return {"ok": True, "promoted": promoted}


class MekoCLIClient(BaseMekoClient):
    """Real Meko Cloud client via the registered connector CLI.

    Every tool call shells out to ``custom.meko/bin/client.py`` (one
    subprocess per call). The API key lives only in the Secure Vault; the
    CLI sends it as the Bearer header itself. This class never sees a key.

    Conversation ids: callers pass synthetic ids (e.g. ``"B1-T-001"`` from
    the harness) or none at all. Each synthetic id is mapped once to a real
    Meko conversation UUID (created under ``CONVERSATION_AGENT_ID``) and
    reused; ``memory_add`` without an explicit conversation uses the most
    recently used one.
    """

    def __init__(self, config: MekoConfig | None = None):
        super().__init__(config)
        self.cli = Path(self.config.cli)
        if not self.cli.is_file():
            raise MekoConfigError(
                f"Meko connector CLI not found at {self.cli}. It is part of "
                "the registered custom.meko connector.")
        self._conversations: dict[str, str] = {}  # synthetic id -> real UUID
        self._conv_agents: dict[str, str] = {}    # real UUID -> agent_id
        self._last_conversation: str = ""

    # -- subprocess plumbing --------------------------------------------
    def _run_cli(self, name: str, args: dict) -> dict:
        """One tool call through the connector CLI. Returns the parsed result."""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as fh:
            json.dump(args, fh)
            args_path = fh.name
        try:
            proc = subprocess.run(
                [sys.executable, str(self.cli), "call-tool",
                 "--name", name, "--arguments-file", args_path],
                capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            raise MekoConfigError(f"Meko call {name} timed out (120s)")
        finally:
            Path(args_path).unlink(missing_ok=True)
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise MekoConfigError(
                f"Meko call {name} failed: {detail[:300]}")
        try:
            raw = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise MekoConfigError(f"Meko call {name} returned non-JSON output")
        return self._parse_tool_result(raw)

    @staticmethod
    def _parse_tool_result(raw: dict) -> dict:
        """Unwrap the connector CLI's JSON-RPC result envelope."""
        if raw.get("isError"):
            texts = [b.get("text", "") for b in raw.get("content", [])
                     if isinstance(b, dict)]
            return {"ok": False, "error": "\n".join(texts)[:500]}
        payload = None
        structured = raw.get("structuredContent") or {}
        if isinstance(structured.get("result"), str):
            payload = structured["result"]
        elif raw.get("content"):
            first = raw["content"][0]
            if isinstance(first, dict):
                payload = first.get("text")
        if payload is None:
            return {"ok": True, "data": raw}
        if isinstance(payload, str):
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                return {"ok": True, "text": payload}
            if isinstance(parsed, dict):
                if "error" in parsed:
                    # Server-side refusal returned as a normal result.
                    return {"ok": False, "error": str(parsed.get("error")),
                            "detail": str(parsed.get("detail", ""))[:300]}
                parsed.setdefault("ok", True)
                return parsed
            return {"ok": True, "data": parsed}
        return {"ok": True, "data": payload}

    def _conversation(self, synthetic_id: str = "") -> str:
        """Map a caller-side conversation id to a real Meko UUID."""
        key = synthetic_id or "__default__"
        real = self._conversations.get(key)
        if real is None:
            args: dict = {"agent_id": CONVERSATION_AGENT_ID}
            if self.config.datapack_id:
                args["datapack_id"] = self.config.datapack_id
            self._record("conversation_create", {"agent_id": CONVERSATION_AGENT_ID})
            res = self._run_cli("conversation_create", args)
            real = res.get("id") or res.get("conversation_id", "")
            if not real:
                raise MekoConfigError(
                    f"conversation_create returned no id: {str(res)[:200]}")
            self._conversations[key] = real
            self._conv_agents[real] = CONVERSATION_AGENT_ID
        self._last_conversation = real
        return real

    def _tool(self, name: str, args: dict, datapack_arg: bool = True) -> dict:
        call_args = dict(args)
        # The server requires a conversation_id on (apparently) every tool
        # call, even when the MCP schema lists it as optional.
        if "conversation_id" not in call_args:
            call_args["conversation_id"] = self._conversation()
        if datapack_arg and self.config.datapack_id:
            call_args.setdefault("datapack_id", self.config.datapack_id)
        self._record(name, {k: (str(v)[:80]) for k, v in call_args.items()})
        return self._run_cli(name, call_args)

    @staticmethod
    def _normalize_memory_hits(hits: list) -> list:
        """Map server memory rows to the app's hit shape."""
        out = []
        for hit in hits or []:
            if not isinstance(hit, dict):
                continue
            meta = hit.get("metadata")
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except json.JSONDecodeError:
                    meta = {}
            out.append({
                "memory_id": hit.get("memory_id") or hit.get("id", ""),
                "text": hit.get("text") or hit.get("memory", ""),
                "score": hit.get("score"),
                "metadata": meta or {},
            })
        return out

    @staticmethod
    def _normalize_search(res: dict) -> dict:
        """Convert the server's context_search shape to the app's buckets.

        Real server shape: {"results": {"memory": [...], "knowledge_base":
        [...], "conversation": {"hits": [...], "thread": [...]}}, ...}.
        The app (agents.py / harness.py) reads {"buckets": {...}} with
        memory hits as {"memory_id", "text", "metadata"}.
        """
        if not isinstance(res, dict) or not res.get("ok", True):
            return res
        results = res.get("results") or {}
        buckets = res.get("buckets") or {}
        if results:
            kb_hits = []
            for hit in results.get("knowledge_base", []) or []:
                if not isinstance(hit, dict):
                    continue
                kb_hits.append({
                    "id": hit.get("id") or hit.get("document_id", ""),
                    "title": hit.get("title") or hit.get("filename", ""),
                    "excerpt": (hit.get("excerpt") or hit.get("text")
                                or hit.get("chunk") or hit.get("content", "")),
                    "score": hit.get("score"),
                })
            conv = results.get("conversation") or {}
            conv_hits = []
            if isinstance(conv, dict):
                for hit in conv.get("hits", []) or []:
                    if not isinstance(hit, dict):
                        continue
                    conv_hits.append({
                        "conversation_id": hit.get("conversation_id", ""),
                        "score": hit.get("score"),
                        "excerpt": (hit.get("excerpt") or hit.get("text")
                                    or hit.get("content", "")),
                    })
            elif isinstance(conv, list):
                conv_hits = conv
            buckets = {
                "memory": MekoCLIClient._normalize_memory_hits(
                    results.get("memory", [])),
                "knowledge_base": kb_hits,
                "conversation": conv_hits,
            }
        else:
            buckets["memory"] = MekoCLIClient._normalize_memory_hits(
                buckets.get("memory", []))
        res["buckets"] = buckets
        res.setdefault("match_quality", "unknown")
        res.setdefault("agent_hint", "")
        return res

    def context_search(self, query: str, limit: int = 10, conversation_id: str = "",
                       agent_id: str = "") -> dict:
        args: dict = {"query": query, "limit": limit,
                      "conversation_id": self._conversation(conversation_id)}
        if agent_id:
            args["agent_id"] = agent_id
        return self._normalize_search(self._tool("context_search", args))

    def memory_add(self, text: str, metadata: dict | None = None, agent_id: str = "") -> dict:
        args: dict = {"text": text,
                      "conversation_id": (self._last_conversation
                                          or self._conversation())}
        if metadata:
            args["metadata"] = json.dumps(metadata)
        if agent_id:
            args["agent_id"] = agent_id
        return self._tool("memory_add", args)

    def memory_search(self, query: str, limit: int = 10, agent_id: str = "") -> dict:
        args: dict = {"query": query, "limit": limit,
                      "conversation_id": self._last_conversation or self._conversation()}
        if agent_id:
            args["agent_id"] = agent_id
        res = self._tool("memory_search", args)
        if isinstance(res, dict) and isinstance(res.get("results"), list):
            res["results"] = self._normalize_memory_hits(res["results"])
        return res

    def memory_get_all(self, promoted: bool = False, agent_id: str = "") -> dict:
        args: dict = {"promoted": promoted,
                      "conversation_id": self._last_conversation or self._conversation()}
        if agent_id:
            args["agent_id"] = agent_id
        return self._tool("memory_get_all", args)

    def memory_get_by_id(self, memory_id: str, agent_id: str = "") -> dict:
        args: dict = {"memory_id": memory_id,
                      "conversation_id": self._last_conversation or self._conversation()}
        if agent_id:
            args["agent_id"] = agent_id
        return self._tool("memory_get_by_id", args)

    def knowledgebase_search(self, query: str, limit: int = 5, agent_id: str = "") -> dict:
        args: dict = {"query": query, "limit": limit,
                      "conversation_id": self._last_conversation or self._conversation()}
        if agent_id:
            args["agent_id"] = agent_id
        return self._tool("knowledgebase_search", args)

    def knowledgebase_upload_document(self, name: str, text: str, agent_id: str = "") -> dict:
        # Two-step flow: the MCP tool returns a presigned S3 POST (url +
        # fields); the file bytes must then be POSTed to that URL as
        # multipart/form-data. Without the POST the document never indexes.
        data = text.encode("utf-8")
        args: dict = {
            "filename": name,
            "size": len(data),
            "content_hash": hashlib.sha256(data).hexdigest(),
            "content_head_base64": base64.b64encode(data[:3072]).decode("ascii"),
            "conversation_id": self._last_conversation or self._conversation(),
        }
        if agent_id:
            args["agent_id"] = agent_id
        res = self._tool("knowledgebase_upload_document", args)
        if not isinstance(res, dict) or not res.get("ok", True):
            return res
        key = res.get("key") or ""
        if key:
            res["document_key"] = key
        if res.get("already_uploaded"):
            return res
        url = res.get("url") or ""
        fields = res.get("fields") or {}
        if not url or not fields:
            return {"ok": False, "error": "upload tool returned no presigned URL",
                    "detail": str(res)[:300], "document_key": key}
        try:
            self._post_to_presigned_url(url, fields, name, data)
        except Exception as exc:  # noqa: BLE001 - surfaced as a failed upload
            return {"ok": False, "error": f"S3 upload failed: {exc}",
                    "document_key": key}
        return res

    @staticmethod
    def _post_to_presigned_url(url: str, fields: dict, filename: str,
                               data: bytes) -> None:
        """POST file bytes to a presigned S3 URL (multipart/form-data)."""
        import urllib.request
        import uuid as _uuid

        boundary = "----orderloop" + _uuid.uuid4().hex
        parts: list[bytes] = []
        for k, v in fields.items():
            parts.append(
                f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                f"{v}\r\n".encode("utf-8"))
        parts.append(
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"file\"; "
            f"filename=\"{filename}\"\r\n"
            f"Content-Type: text/markdown\r\n\r\n".encode("utf-8"))
        parts.append(data)
        parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            if resp.status not in (200, 204):
                raise RuntimeError(f"S3 returned HTTP {resp.status}")

    def knowledgebase_document_status(self, document_key: str, agent_id: str = "") -> dict:
        args: dict = {"document_key": document_key,
                      "conversation_id": self._last_conversation or self._conversation()}
        if agent_id:
            args["agent_id"] = agent_id
        return self._tool("knowledgebase_document_status", args)

    def conversation_create(self, agent_id: str = "") -> dict:
        agent = agent_id or CONVERSATION_AGENT_ID
        res = self._tool("conversation_create", {"agent_id": agent})
        conv_id = res.get("id") or res.get("conversation_id", "")
        if not res.get("ok", True) or not conv_id:
            return {"ok": False, "error": str(res)[:300]}
        self._conv_agents[conv_id] = agent
        self._last_conversation = conv_id
        return {"ok": True, "conversation_id": conv_id}

    def conversation_add_message(self, conversation_id: str, user_message: str,
                                 agent_reply: str, agent_id: str = "",
                                 reasoning: list | None = None, plan: list | None = None) -> dict:
        real = self._conversation(conversation_id)
        args: dict = {"conversation_id": real,
                      "input": user_message, "output": agent_reply,
                      "agent_id": self._conv_agents.get(real, CONVERSATION_AGENT_ID)}
        if reasoning:
            args["reasoning"] = " ".join(reasoning)
        if plan:
            args["plan"] = plan
        return self._tool("conversation_add_message", args)

    def conversation_capture(self, conversation_id: str, messages: list[dict],
                             agent_id: str = "") -> dict:
        user_msg = next((m.get("content", "") for m in messages
                         if m.get("role") == "user"), "")
        asst_msg = next((m.get("content", "") for m in reversed(messages)
                         if m.get("role") == "assistant"), "")
        return self.conversation_add_message(conversation_id, user_msg, asst_msg,
                                             agent_id=agent_id)

    def track_token_usage(self, conversation_id: str, name: str, input_tokens: int,
                          output_tokens: int, model: str, agent_id: str = "") -> dict:
        args: dict = {"conversation_id": self._conversation(conversation_id),
                      "name": name,
                      "input_tokens": input_tokens, "output_tokens": output_tokens,
                      "total_tokens": input_tokens + output_tokens, "model": model}
        if agent_id:
            args["agent_id"] = agent_id
        return self._tool("track_token_usage", args)

    def datapack_create(self, name: str, description: str = "") -> dict:
        # NOTE: the server rejects a `description` argument (validation
        # error), so only `name` is sent. `description` is kept in the
        # signature for interface compatibility.
        return self._tool("datapack_create", {"name": name},
                          datapack_arg=False)

    def datapack_list(self) -> dict:
        return self._tool("datapack_list", {}, datapack_arg=False)

    def datapack_describe(self, datapack_id: str) -> dict:
        return self._tool("datapack_describe", {"datapack_id": datapack_id},
                          datapack_arg=False)

    def memory_promote(self, memory_ids: list[str], agent_id: str = "") -> dict:
        args: dict = {"memory_ids": memory_ids,
                      "conversation_id": self._last_conversation or self._conversation()}
        if agent_id:
            args["agent_id"] = agent_id
        return self._tool("memory_promote", args)


def make_meko_client(condition: str, meko_kind: str = "fake",
                     config: MekoConfig | None = None,
                     kb: LocalKB | None = None) -> BaseMekoClient:
    """Factory.

    condition ``A`` always returns :class:`NullMekoClient` (baseline never
    touches Meko). Condition ``B`` returns the real CLI client for
    ``meko_kind='real'`` or the in-memory fake for ``'fake'``.
    """
    cfg = config or MekoConfig.from_env()
    if condition == "A":
        return NullMekoClient(cfg)
    if meko_kind == "real":
        return MekoCLIClient(cfg)
    if meko_kind == "fake":
        return FakeMekoClient(cfg, kb=kb)
    raise ValueError(f"Unknown meko kind: {meko_kind!r} (use 'real' or 'fake')")
