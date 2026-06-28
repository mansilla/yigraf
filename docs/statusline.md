# yigraf status surface & statusline adapter

`int:status-surface` — a **host-agnostic** summary of the graph for the *human principal*, delivered on
an ambient UI channel (a statusline) so it informs the user **without spending the agent's context
budget**. This is the one yigraf surface aimed at the human, not the agent; see `mem:012` for why it
must never ride the hook injection (color codes + vanity stats would be wasted tokens in the agent's
context, and would violate design law #2/#4).

## The command — `yigraf status`

The agnostic backbone. Pure over the graph + on-disk artifacts; it never reads a transcript or any
host API.

```
yigraf status                 # plain one-liner (pipes/scripts) — byte-stable
yigraf status --color         # ANSI + shape glyphs + spinner brand icon (force on a non-TTY pipe)
yigraf status --json          # the full StatusSummary as JSON, for a host that renders it itself
yigraf status --ctx-used N --ctx-limit M    # host-supplied context-window occupancy (optional)
```

Plain output:

```
yigraf 677 sym · 9 int · 17 task/6 open · 14 dec · no drift · fresh · sem 23
```

Pretty output (what a statusline shows):

```
◞ 677 sym · 9 int · 17 task/6 open · 14 dec · ✓ clear · ● fresh · ✦ sem 23 · ctx ▰▱▱▱ 19%
```

### Legend

| Segment        | Meaning                                                                       |
|----------------|-------------------------------------------------------------------------------|
| `◜◝◞◟`         | yigraf brand — a "spinning empty ring"; the frame advances each refresh        |
| `N sym/int/dec`| symbols · intents · active decisions in the graph                              |
| `N task/M open`| total tasks · open (non-done) tasks; the `/M open` is yellow when `M>0`        |
| `✓ clear` / `⚠ N drift` | green when no implements/concerns link has drifted; yellow with a count otherwise |
| `● fresh` / `○ stale` / `○ none` | committed `graph.json` vs the rebuilt graph (green/yellow/dim) |
| `✦ sem N`      | a semantic index of `N` memory+intent nodes is present (dim = the index is on) |
| `ctx ▰▰▱▱ NN%` | context-window fill, **only if a host supplied it**; green <50, yellow <80, red ≥80 |

Color is auto-on for a TTY (honoring `NO_COLOR`) and forced with `--color`. The **non-TTY pipe is the
statusline's case**, so the adapter passes `--color`; yigraf keeps `click` from stripping the ANSI.

## Wiring it into Claude Code

The statusline is a per-host *adapter* — a thin shim around `yigraf status`. The one non-agnostic
datum (context %) is computed in the **adapter**, by reading the transcript Claude Code hands it; it
never leaks into yigraf's core (`mem:013`).

1. Drop an adapter script in your repo (or `.claude/`), e.g. `.claude/yigraf-statusline.sh`:

   ```bash
   #!/usr/bin/env bash
   set -eo pipefail
   YIGRAF="$(command -v yigraf)"        # or an absolute venv path: /path/.venv/bin/yigraf
   in=$(cat)
   cwd=$(printf '%s' "$in" | jq -r '.workspace.current_dir // .cwd // "."')
   tx=$(printf '%s' "$in" | jq -r '.transcript_path // empty')
   limit=$(printf '%s' "$in" | jq -r 'if ((.model.id // "") | test("1m";"i")) then 1000000 else 200000 end')
   ctx=()
   if [ -n "$tx" ] && [ -f "$tx" ]; then
     used=$(jq -rs '[.[] | .message?.usage? // empty] | last
                    | (.input_tokens + .cache_read_input_tokens + .cache_creation_input_tokens) // empty' "$tx" 2>/dev/null || true)
     [ -n "${used:-}" ] && ctx=(--ctx-used "$used" --ctx-limit "$limit")
   fi
   "$YIGRAF" status --repo "$cwd" --color "${ctx[@]}" 2>/dev/null || true
   ```

   `chmod +x` it. (Needs `jq` for the context %; without `jq` the line still renders, just no `ctx`.)

2. Register it in `.claude/settings.local.json` — the **per-machine** file, not the committed
   `settings.json` (same convention as `install-claude-hooks`, so an absolute path never reaches a
   commit; see the M5 caveat):

   ```json
   {
     "statusLine": { "type": "command", "command": "/abs/path/.claude/yigraf-statusline.sh" }
   }
   ```

### Minimal (no context %)

If you don't want the transcript read, skip the script entirely:

```json
{ "statusLine": { "type": "command", "command": "yigraf status --color --repo \"$CLAUDE_PROJECT_DIR\"" } }
```

## Other hosts

The contract is just `yigraf status` (text) / `yigraf status --json` (data). Any host with an ambient
region wires its own adapter the same way; the context-% computation is the only host-specific part,
and it stays in that adapter. yigraf's core never learns which host it runs under.
