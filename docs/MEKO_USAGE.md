# Meko usage

How OrderLoop Memory uses Meko (cloud.mekodata.ai) as its context layer.
Meko is the context engine / data layer — it is **not** an LLM.

## Connection

- Single MCP endpoint: `https://mcp.mekodata.ai/mcp` (Streamable HTTP).
- Auth: `Authorization: Bearer <mko_tkn_…>` + a mandatory `User-Agent`
  header. The key lives only in the Secure Vault; the app never sees it.
  Every tool call goes through the registered connector CLI
  (`~/workspace/custom-connectors/custom.meko/bin/client.py`), invoked as
  a subprocess by `app/meko_client.py` (`MekoCLIClient`). No key is ever
  in an env var, a file, an argument or a log.
- The Meko REST API (`https://api.mekodata.ai`) is NOT used: its host is
  not registered in the connector, so REST calls would be refused.
  Knowledge-base upload uses the MCP tool
  `knowledgebase_upload_document` instead (`scripts/seed_kb.py`).

## Tools actually used

| Tool | When | Notes |
|---|---|---|
| `context_search` | 1× per ticket (condition B) | before any fix op; the harness enforces this |
| `memory_add` | after a human approves a fix | metadata: ticket_id, cluster, memory_key, source, agent, approved_by |
| `conversation_capture` | only when a fix is proposed to HITL (condition B) | one minimal `conversation_add_message` call per proposed fix (decision only: ticket id + subject, diagnosis, executed ops, verification — no ticket body, no final answer); turns count against quota |
| `track_token_usage` | not called by the harness yet | client method exists; token usage is reported from the harness metrics instead |
| `knowledgebase_search` | not used by agents | KB is searched via `context_search` buckets (and locally in condition A) |
| `memory_promote` | only if needed | private → Collective Memory; owner/maintainer only; one-way |

The client (`app/meko_client.py`, `MekoCLIClient`) calls 17 of the 57 MCP
tools the server exposes (allow-listed in the connector CLI); the agents
call only the four above. `memory_search` and `knowledgebase_search` are
deliberately **not** called by agents — one `context_search` per ticket
is the whole retrieval budget.

## Datapacks

- Demo: `contextcon-theme2-support`
- Official runs: `orderloop-run-b1`, `orderloop-run-b2`, `orderloop-run-b3`
  (one per run, so runs do not contaminate each other)
- Spike (26 Nov 2026): `orderloop-spike`
  (`9e3216dd-7e33-4a60-b1e9-2bfb690d7e71`) and `orderloop-spike-e2e`
  (`7e1853aa-0130-44f0-ac00-d2b2a64d4b6f`) — throwaway, do not reuse
  for official runs. Datapack slots used: 3 of 10 (default + 2 spike).
- The default datapack from account creation (`meko_default_datapack`)
  is not used.
- 12 KB articles are seeded into each run datapack with
  `scripts/seed_kb.py` (MCP upload via `knowledgebase_upload_document`).

## Free-tier quotas (lifetime, never reset)

1,000 `context_search` · 1,000 `memory_search` · 1,000 KB search ·
10,000 `memory_add` · 1,000 conversation turns · 2,000 searchable turns ·
10 datapacks · 100 MB storage. Quota exceeded → error
`free_tier_limit_reached`. Deleting data does **not** restore quota.

**Official-run budget:** ~108 `context_search` + ~50 `memory_add` +
~216 turns across 6 runs — well inside the free tier. The demo and
smoke tests use `FakeMekoClient` (in-memory, zero quota).

## Spike findings (26 Nov 2026) — verified live

1. **Cross-agent reuse works without `memory_promote`.** A `memory_add`
   by `orderloop-triage` is readable by `orderloop-specialist` via both
   `memory_search` and `context_search` (memory bucket, score ~0.67).
2. **KB upload is two-step.** `knowledgebase_upload_document` returns a
   presigned S3 POST (`url` + `fields` + content-hash-derived `key`);
   the file bytes must be POSTed multipart to S3, then
   `knowledgebase_document_status` polled until `COMPLETED`
   (kb-01 fast, kb-02 took >60 s once). Re-uploading identical content
   reuses the same key.
3. **Server response shapes differ from the MCP schema docs.**
   `context_search` returns
   `{"results": {"memory": [{"id", "memory", "score", "metadata"}],
   "knowledge_base": [...], "conversation": {"hits": [...],
   "thread": [...]}}}` — not `{"buckets": {...}}` with
   `{"memory_id", "text"}`. `MekoCLIClient._normalize_search` converts
   it; without the normalizer the LLM saw "(no relevant memory…)" and
   every repeat classified a miss. `conversation_id` is required on
   (apparently) every tool call, and server refusals arrive as normal
   results with an `"error"` key (`isError: false`).
4. **Meko auto-extracts fact memories from conversation turns.** After
   1 explicit `memory_add`, the spike datapack held 7 memories: the fix
   plus 6 auto-extracted facts with empty metadata. Facts can outrank
   the fix in `context_search` (a far-repeat ticket used a fact memory
   instead of the fix → classified miss). **Fixed 26 Nov 2026 (pre-run
   fixes):** `prefer_fix_memories` in `app/agents.py` stable-sorts
   memory hits so agent-stored fixes (`metadata.source == "agent"` or a
   `memory_key`) come before facts, for both the prompt and the pick;
   `app/harness.py` logs a Meko turn only when a fix is proposed to
   HITL, with minimal content (`build_trace_messages`: id + subject,
   diagnosis, ops, verification — no body, no final answer). Regression
   tests: `tests/test_fix_preference.py` (10 tests, incl. a T-003
   scenario that reproduces the spike's ranking inversion).

## Open questions (to verify in the spike phase, before official runs)

1. ~~Whether a `memory_add` by the owner service account is already
   readable by all agents in the datapack, or an explicit
   `memory_promote` step is needed for cross-agent reuse. This is the
   load-bearing assumption of the whole demo — verify first.~~
   **Answered in the spike: readable without promote (see above).**
2. ~~The exact REST payload for KB document upload (`scripts/seed_kb.py`
   follows the documented shape; adjust if the API differs).~~
   **Answered in the spike: no REST upload — MCP two-step flow (see
   above).**
3. The "credit upgrade via Discord ContextCon" claim is **unverified**
   (no official source found) — do not rely on it.
4. Meko's internal embedding / reranker model names are not published —
   do not claim them.

## Local vs Cloud

- **Meko Local** for development and pilot runs (no quota consumed).
- **Meko Cloud** for official runs and the demo (the hackathon requires
  the cloud product; quotas above apply).
