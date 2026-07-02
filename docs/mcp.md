# yigraf MCP server — the host-agnostic pull channel

`int:mcp-server` — `yigraf mcp` runs yigraf as an [MCP](https://modelcontextprotocol.io) server over
stdio, exposing the graph as tools. **One adapter reaches every MCP host** (Codex, Antigravity, Cursor,
Windsurf, Claude Code). It's the *pull* channel: the agent calls a tool to fetch the slice, instead of
a hook pushing it. On hosts with no lifecycle hook (e.g. the Antigravity IDE) this is how yigraf works
at all; on Claude Code the push hooks are still preferred (and this is optional/complementary).

## Tools

The full agent loop — **read** the governing slice, then **write** back links and the *why* — over MCP,
so a host with no lifecycle hook (e.g. the Antigravity IDE) still gets the whole of yigraf.

| Tool | Args | Does |
|------|------|------|
| `context` | `query`, `repo?`, `family?`, `budget?` | Pull the token-budgeted slice: governing intents, plan, implementing signatures, prior decisions + *why*, drift. Call BEFORE changing code. |
| `status`  | `repo?` | The compact status line: counts, drift, freshness, semantic-index size. |
| `link`    | `task`, `target`, `repo?` | Bind a finished task to the `sym:` it implements (or the `int:` it tracks), anchored to current content. |
| `remember`| `statement`, `why?`, `serves?`, `concerns?`, `rejected?`, `type?`, `repo?` | Persist a decision/rationale as a memory node; a `concerns` symbol is anchored (drift re-surfaces it). |
| `note_constraint` | `rule`, `concerns?`, `why?`, `serves?`, `repo?` | Capture a constraint/rule governing code. |
| `supersede` | `old_id`, `statement`, `why?`, `serves?`, `concerns?`, `rejected?`, `type?`, `repo?` | Record a mind-change: a new node superseding an old one. |

Read tools run **in-process** (warm graph + model across calls); write tools shell out to the matching
CLI verb, so they reuse its dedup guard, anchoring, and exit-0 "did you mean" guidance unchanged — a bad
locator comes back as guidance text, not an error.

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
with an absolute path. The IDE caps total MCP tools at 100 (yigraf adds 2).

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
  error. (Only the heavy embeddings backend stays opt-in — `mem:005` — since it pulls ~1GB of torch.)
