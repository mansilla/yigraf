# yigraf MCP server — the host-agnostic pull channel

`int:mcp-server` — `yigraf mcp` runs yigraf as an [MCP](https://modelcontextprotocol.io) server over
stdio, exposing the graph as tools. **One adapter reaches every MCP host** (Codex, Antigravity, Cursor,
Windsurf, Claude Code). It's the *pull* channel: the agent calls a tool to fetch the slice, instead of
a hook pushing it. On hosts with no lifecycle hook (e.g. the Antigravity IDE) this is how yigraf works
at all; on Claude Code the push hooks are still preferred (and this is optional/complementary).

## Tools

The full agent loop — **read** the governing slice, then **write** back links and the *why* — over MCP,
so a host with no lifecycle hook (e.g. the Antigravity IDE) still gets the whole of yigraf.

Every tool also takes `repo?` (the call's repo override); it's omitted below for brevity.

**Read — orient before acting**

| Tool | Args | Does |
|------|------|------|
| `context` | `query`, `family?`, `budget?` | Pull the token-budgeted slice: governing intents, plan, implementing signatures, prior decisions + *why*, drift. Call BEFORE changing code. |
| `status`  | — | The compact status line: counts, drift, freshness, conflicts, stale, diverged, semantic-index size. |
| `show`    | `target` | Read ONE node by id, in full and unbudgeted — every anchor, the whole `why`, its live drift, and any conflict it is a side of. `context` searches by *meaning*, so an id reaches it as noise; this is the verb for an id a warning handed you. |
| `conflicts` | — | List every open knowledge-conflict: the pair, their shared anchor, how close they read, which side provenance prefers, and the resolving verb. This is the listing behind `status`'s `⚠ N conflict`. |

**Write — the seam between code and intent**

| Tool | Args | Does |
|------|------|------|
| `link`    | `task`, `target` | Bind a finished task to the `sym:` it implements (or the `int:` it tracks), anchored to current content. Re-call to re-anchor after the code changes. |
| `unlink`  | `task`, `target` | Retire a declaration that is no longer true — a symbol gone for good, or an anchor wrongly declared. Also takes `mem:<id>` to retire a memory's `concerns` or `grounded_by` ref. No mind-change is recorded. |
| `reanchor` | `target`, `old`, `new` | Move ONE of a memory's anchors to where its subject moved. A locus repair, **not** a mind-change — no supersedes edge is written. |

**Write — capture the why**

| Tool | Args | Does |
|------|------|------|
| `remember`| `statement`, `why?`, `serves?`, `concerns?`, `governs?`, `rejected?`, `type?`, `grounding?`, `evidence?`, `rejected_valid_when?`, `rejected_invalidated_when?` | Persist a decision/rationale as a memory node; a `concerns` locus is anchored, so editing that code re-surfaces the decision. `governs` anchors a *usage policy* instead and never drifts. |
| `note_constraint` | `rule`, `concerns?`, `governs?`, `why?`, `serves?`, `rejected?`, `grounding?`, `evidence?`, `rejected_valid_when?`, `rejected_invalidated_when?` | Capture a constraint/rule governing code, flagged as a candidate to promote into an enforced check. |
| `propose` | `statement`, `from_`, `concerns?`, `rejected?`, `why?`, `serves?`, `type?`, `origin?`, `grounding?`, `evidence?`, … | Land a *candidate* belief from an outside source (a review, a doc, a spike) rather than asserting it yourself. |
| `supersede` | `old_id`, `statement`, `why?`, `serves?`, `concerns?`, `governs?`, `rejected?`, `type?`, `grounding?`, `evidence?`, … | Record a mind-change: a new node superseding an old one, never an edit in place. **Inherits** the old node's `concerns`/`governs`/`serves` unless you re-aim them. |

**Write — re-verify and endorse**

| Tool | Args | Does |
|------|------|------|
| `reaffirm` | `target`, `concerns?`, `grounding?`, `evidence?` | The honest counterpart to `supersede`: the belief is UNCHANGED, so re-stamp its anchor and clear the drift. Re-verify first — this verb is how rubber-stamping would happen. A locus (`sym:`/`file:`) instead of a `mem:` id reaffirms every live memory concerning it. |
| `attest`   | `target` | Record that the *principal* endorsed this belief — a sticky trust floor that holds any later agent `supersede` of it pending a human. Never use it to bless your own call. |
| `pin`      | `target`, `off?` | Inject this belief in full at every session start, for the few rules load-bearing on every task. Refused on a superseded node (it would inject nothing). |
| `supersede_intent` | `old_slug`, `new_slug`, `statement`, `why?`, `scenario?`, `design?`, `type?` | Reverse a spec whose premise turned out false: creates the replacement, archives the old, writes a real `int→int` supersedes edge. |

Read tools run **in-process** (warm graph + model across calls); write tools shell out to the matching
CLI verb, so they reuse its dedup guard, anchoring, and exit-0 "did you mean" guidance unchanged — a bad
locator comes back as guidance text, not an error.

Two tools exit non-zero on purpose, mirroring the CLI so CI can gate on them: `conflicts` when conflicts
stand, and the underlying `drift`. The report is on stdout either way, so a non-zero result is the
answer, not a failure.

## Prerequisites

```bash
yigraf init && yigraf build     # the repo needs a built graph
```

The MCP SDK ships as a core dependency, so there's nothing extra to install — `yigraf install` wires
the pull channel by default.

The server picks its repo from (in order): the tool call's `repo` arg › `$YIGRAF_REPO` › the process
cwd. Pin a repo with `--repo /abs/path` or `YIGRAF_REPO`. If `yigraf` isn't on the host's PATH, use an
absolute path (`/abs/.venv/bin/yigraf`) or `command` = your interpreter + `args` `["-m","yigraf",…]`.

## Per-host configuration

### OpenAI Codex CLI — `~/.codex/config.toml` (or project `.codex/config.toml`)

```toml
[mcp_servers.yigraf]
command = "yigraf"
args = ["mcp", "--repo", "/abs/path/to/repo"]
```

Or via the CLI: `codex mcp add yigraf -- yigraf mcp --repo /abs/path/to/repo`.
(Codex also has native hooks — see `docs/hosts.md` for the push-channel option there.)

### Google Antigravity — `mcp_config.json`

Path differs by build — `~/.gemini/antigravity/mcp_config.json` *or* `~/.gemini/config/mcp_config.json`
(check yours; the in-app **Agent panel → MCP Servers → View raw config** is the reliable editor). stdio
servers use `command`/`args` (remote servers would use `serverUrl`, not `url`):

```json
{
  "mcpServers": {
    "yigraf": {
      "command": "yigraf",
      "args": ["mcp", "--repo", "/abs/path/to/repo"]
    }
  }
}
```

Notes: Antigravity's IDE has **no hook system**, so MCP (plus a written `.agents/rules` / `SKILL.md`) is
the integration path there. Env-var substitution in this file is unreliable — prefer the `--repo` arg
with an absolute path. The IDE caps total MCP tools at 100 (yigraf adds 15).

### Cursor / Windsurf — `~/.cursor/mcp.json` (or `.cursor/mcp.json`); Windsurf `~/.codeium/windsurf/mcp_config.json`

```json
{ "mcpServers": { "yigraf": { "command": "yigraf", "args": ["mcp"] } } }
```

### Claude Code

```bash
claude mcp add yigraf -- yigraf mcp --repo /abs/path/to/repo
```

Optional here — the `PostToolUse`/`SessionStart` hooks (`yigraf install-claude-hooks`) are the stronger,
push-based channel. Add the MCP server only if you also want the agent to pull `context`/`status` on demand.

## Verifying

```bash
yigraf mcp --repo .      # should block, serving on stdio (Ctrl-C to stop)
```

A quick wire check:

```python
import asyncio, sys, os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    p = StdioServerParameters(command=sys.executable, args=["-m","yigraf","mcp","--repo",os.getcwd()])
    async with stdio_client(p) as (r,w):
        async with ClientSession(r,w) as s:
            await s.initialize()
            print([t.name for t in (await s.list_tools()).tools])     # context, status, link, remember, …
            print((await s.call_tool("status", {})).content[0].text)

asyncio.run(main())
```

## Design notes

- **In-process, not a per-call subprocess.** The server holds the structure graph + embedding model
  warm across tool calls within a session, so a second `context` query doesn't re-pay the cold build /
  model load.
- **Stdio only writes the protocol to stdout.** Diagnostics (HF download notice, model-load progress)
  go to stderr — anything on stdout would corrupt the MCP stream.
- **Core dependency, always available.** The MCP SDK ships with yigraf and `yigraf install` wires the
  pull channel by default — full power out of the box. A missing workspace returns guidance text, not an
  error. (Semantic recall is core too — the fastembed backend is bundled, no torch — see `mem:005`; only
  the opt-in `[embeddings-torch]` backend pulls torch.)
