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
| `● fresh` / `○ behind` / `○ none` | the gitignored SQLite view (`.local/graph.db`) vs the rebuilt graph (green/yellow/dim) |
| `⚠ N conflict` | open knowledge-conflicts awaiting a principal; **shown only when `N>0`**. List them with `yigraf conflicts` |
| `⚠ N stale`    | done tasks whose implementing symbol drifted — the completion is unverified, not false; **only when `N>0`**. List with `yigraf drift --stale` |
| `⚠ N diverged` | loci another principal's log revision differs on; **only when `N>0`**. `yigraf sync` reconciles |
| `✦ sem N`      | a semantic index of `N` memory+intent nodes is present (dim = the index is on) |
| `ctx ▰▰▱▱ NN%` | context fill against the usable budget (`status.ctx_soft_limit`, default **250k** = 100%, whatever the host window; `0` gauges the raw window), **only if a host supplied it**; green <50, yellow <80, red ≥80 |

**`behind` is not `stale`.** They are different dimensions and the words are kept apart deliberately:
`○ behind` means the materialized view hasn't caught up with the source and *any read rebuilds it* — an
unindexed-artifact marker, not a health problem. `⚠ N stale` means N shipped completions lost their
evidence and need a human decision. The three `⚠` segments are silent at zero (design law #4), so their
absence is a real all-clear rather than a missing field.

Color is auto-on for a TTY (honoring `NO_COLOR`) and forced with `--color`. The **non-TTY pipe is the
statusline's case**, so the adapter passes `--color`; yigraf keeps `click` from stripping the ANSI.

## Wiring it into Claude Code

`yigraf install-claude-hooks` sets Claude Code's `statusLine` to **`yigraf statusline`**. That
adapter reads the session JSON on stdin, computes context % from the transcript itself (no `jq`, no
shell), and renders the bar. The context % is the one host-specific datum, and it stays in the adapter
(`mem:013`). An existing statusLine that isn't yigraf's is left alone. A previous yigraf wiring (the
old `yigraf-statusline.sh` script or a bare `yigraf status`) is upgraded in place.

**Use `yigraf statusline`, not `yigraf status`, for the bar.** The host refreshes the bar on every
message. `statusline` reads the materialized view the hooks keep current (a stat walk, plus a rebuild
only when something changed). `status` re-extracts the whole graph on every call so it can compare
the view against a fresh build — that is its job, and on a large tree it costs seconds each time.
Before 1.16 the statusline did the same rebuild. `doctor` never saw that load, because the statusline
is not a hook.

Launched in a subdirectory below the store root, the bar shows `⚠ no store here · store at <root>`
for the whole session instead of going blank. An ordinary repo with no store above it still gets an
empty bar.

## Other hosts

The contract is just `yigraf status` (text) / `yigraf status --json` (data). Any host with an ambient
region wires its own adapter the same way; the context-% computation is the only host-specific part,
and it stays in that adapter. yigraf's core never learns which host it runs under.
