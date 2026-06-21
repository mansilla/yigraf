# Graphify — Analysis

> Source: `origins/graphify` (safishamsi/graphify, PyPI `graphifyy` v0.8.40, YC S26, Python ≥3.10).
> A CLI + skill + MCP server that turns any folder (code, docs, PDFs, images, video) into a
> queryable knowledge graph, then makes that graph the agent's first stop instead of grep/read.

## 1. The problem it solves

**Token waste and context-window thrash.** When an agent answers "how does auth connect to the
DB?", it greps, opens many files, and re-reads them *every session* — slow, token-heavy, and it
never builds a durable map. Graphify's thesis: build the structural map **once**, persist it as a
compact graph, serve scoped subgraphs on every later query. Claimed **71.5× fewer tokens/query** on
a 52-file corpus (honest framing: at ~6 files the value is structural clarity, not token savings).

Second, subtler problem: **agents won't use an external map unless nudged at the right moment** — so
a large part of the codebase is machinery to inject "use the graph first" into as many agents as
possible.

## 2. How it works

### Broad agent integration — the most engineered part (3 tiers + MCP)
A per-platform config table (`__main__.py` `_PLATFORM_CONFIG`) covers ~20 agents by supporting
whichever tier a host offers, degrading gracefully:

1. **Skill/command files (universal).** A `SKILL.md` copied to each host's convention path
   (`.claude/skills/`, `.codex/skills/`, etc.). The skill body (`graphify/skill.md`, 600+ lines) is
   the orchestration *program* the host LLM executes using **its own model API** ("the host session
   itself is the LLM" — no API key needed). ~16 hand-tuned variants for host quirks, generated from
   `platforms.toml` via `tools/skillgen/`.
2. **Always-on instruction injection.** Packaged markdown blocks (`graphify/always_on/`) spliced
   idempotently into each host's persistent-instructions file via marker-based
   `_replace_or_append_section`. Content literally instructs: "for codebase questions, first run
   `graphify query`…". Reaches Cursor via `.cursor/rules/graphify.mdc` (`alwaysApply: true`).
3. **PreToolUse hooks (strongest nudge).** Intercept the agent *at the moment it's about to grep or
   read a file* and inject a reminder. The Bash hook matches `grep|rg|find|…` and, if `graph.json`
   exists, emits "MANDATORY: run `graphify query` before grepping." A Read/Glob hook nudges before
   reading source one-by-one. **Both fail open** (`|| true` everywhere) and skip `graphify-out/`.
   Ported per host (Codex `hooks.json`, Gemini `BeforeTool`, OpenCode/Kilo JS plugins). Hookless
   hosts (Trae/Aider) fall back to AGENTS.md, stated honestly.
4. **MCP server** for repeated/team access (below).

> **This multi-tier strategy is the single most reusable artifact in the repo.** It is a blueprint
> for "make my tool the agent's default reflex" across heterogeneous hosts.

### Data model — a NetworkX graph as `graph.json` (node-link)
- **Nodes** = code symbols (class/function/method), files, imported modules, plus concepts/entities
  from docs/papers/images. Fields: stable casefold `id`, `label`, `file_type`
  (`code|document|paper|image|rationale`), `source_file`, `source_location`, `community`.
- **Edges** = `relation` verb (`calls`, `imports`, `inherits`, `references`,
  `semantically_similar_to`, …) + `confidence` + optional `confidence_score` + `context` tag.
- **Hyperedges** = group relations over 3+ nodes.
- **Rationale nodes** — `# NOTE/# WHY/# HACK` comments, docstrings, design rationale extracted as
  *separate linked nodes*. The graph tracks the *why*, not just the *what*.
- **Confidence is first-class & honest:** every edge is `EXTRACTED` (1.0), `INFERRED` (0.55–0.95
  rubric), or `AMBIGUOUS` (flagged). The agent always knows found-vs-guessed.

Storage: plain files under `graphify-out/` (`graph.json`, `GRAPH_REPORT.md`, `graph.html`, SHA256
`cache/`, `manifest.json`). Optional cross-project **global graph** at `~/.graphify/global.json`.
Optional Neo4j/FalkorDB push — but the native store is JSON, no DB required.

### Parsing/indexing — three passes
1. **Code structure (free, local, no LLM).** Tree-sitter ASTs, ~80 extensions / 36+ languages.
   Symbol nodes + structural edges, then a call-graph second pass: same-file resolved calls =
   `EXTRACTED`, cross-file label-matched = `INFERRED`. Parallelized via `ProcessPoolExecutor`.
2. **Video/audio (local).** faster-whisper, seeded with top code god-nodes.
3. **Docs/papers/images (LLM).** Skill dispatches **parallel subagents**, each reads a 20–25 file
   chunk and writes a JSON fragment; fragments merged. **Code is never sent to the LLM**; code-only
   corpora skip pass 3.

**Clustering:** Leiden (graspologic) or Louvain fallback. **No embeddings/vector DB** — the
LLM-emitted `semantically_similar_to` edges *are* the similarity signal; communities fall out of
edge density. Determinism via sorted partitioning + pinned `PYTHONHASHSEED`.
**Analysis:** god nodes (highest degree) + "surprising connections" (composite cross-community /
cross-file / cross-language bridge scoring).

### Queries
**CLI:** `query`, `path A B`, `explain`, `affected`. **MCP** (`graphify/serve.py`): `query_graph`,
`get_node`, `get_neighbors`, `get_community`, `god_nodes`, `graph_stats`, `shortest_path` + PR tools
+ resources (`graphify://report`, `god-nodes`, …). stdio (per-dev) and Streamable HTTP (team, with
bearer/API-key auth) transports; **hot-reloads** `graph.json` on mtime change.
The retriever is clever with no model in the loop: **IDF-weighted term scoring**, exact>prefix>
substring precedence, score-gap seed selection, **hub-aware traversal** (refuses to route through
p99-degree super-hubs), context-filter inference from question verbs, token-budgeted renderer.

### Lifecycle
Index (`/graphify .`) → keep fresh via **detached git post-commit/post-checkout hooks** (AST-only
rebuild, no LLM cost, returns instantly; pinned interpreter; JSON union merge driver so parallel
commits never conflict) → query (agent nudged by hook/always-on text; MCP hot-reloads mid-session).

## 3. Ideas worth stealing
1. **The multi-tier integration strategy** (skill → always-on → fail-open hooks → MCP).
2. **Hooks that nudge, never block, and fail open.**
3. **Structure-as-similarity (no embeddings).**
4. **IDF + hub-aware token-budgeted graph traversal** — lightweight GraphRAG with no model.
5. **First-class confidence provenance** (`EXTRACTED/INFERRED/AMBIGUOUS`).
6. **Rationale nodes** — capture *why* code exists.
7. **Free incremental refresh via detached git hooks** + JSON merge driver.
8. **Composite "surprise" scoring** — proactive insight, not just query response.

## 4. What's lacking
- **Maps code structure + doc concepts, not work-in-progress.** No conversation memory, no active
  plans/goals/TODOs, no "what am I doing now." (Their separate product *Penpax* targets memory —
  conceding graphify doesn't.)
- **Intent/behavioral semantics are shallow.** Cross-file `calls` are label-matched heuristics
  (`INFERRED`), not true resolved call graphs; cross-language calls suppressed as resolver noise. No
  data-flow, taint, or runtime behavior.
- **Semantic extraction is LLM-bounded & non-deterministic;** code-only corpora lose the conceptual
  layer.
- **Auto-refresh is AST-only** — doc/paper/image nodes go stale until a manual update.
- **Scale ceilings** (HTML viz aggregates >5k nodes; 512 MiB graph cap).
- **LLM-controlled-content security surface** (sanitizes labels to block prompt injection from a
  malicious corpus).

## 5. Tech stack
Python ≥3.10. Deps: `networkx`, `numpy`, `rapidfuzz`, 28 tree-sitter grammars; optional Leiden
(graspologic, py<3.13), MCP, Neo4j/FalkorDB, PDF/office/video, jieba, LLM backends
(anthropic/openai/gemini/ollama/bedrock/azure/…). Distributed as PyPI `graphifyy` (CLI `graphify`);
MCP via `graphify-mcp` (Starlette + uvicorn StreamableHTTP). ~80 test files, security-conscious
(bandit/pip-audit/safety). Production-grade.
