---
family: intent
id: int:status-surface
status: satisfied
type: requirement
---
## Requirement
yigraf SHALL expose a host-agnostic status summary of the graph — scale, drift, freshness, semantic-index, and (only when a host supplies it) context-window occupancy — as a compact line a thin per-host ambient surface can render without spending the agent's context budget.

## Scenarios
- Given a repo with a yigraf workspace, When `yigraf status` runs, Then it prints a one-line summary (symbols, intents, tasks/open, decisions, drift count, freshness, semantic index) computed without reading any host API or transcript.
- Given a host that can supply context-window usage, When it passes --ctx-used/--ctx-limit, Then the line includes context occupancy; Given a host that cannot, Then that segment is omitted and the rest still renders.

## Design (how)
Core computes a StatusSummary value object (pure: no host coupling, no transcript read); a `yigraf status` command renders it as a line or --json. The one non-agnostic datum (context occupancy) is an injected optional input a per-host adapter fills (e.g. a Claude Code statusLine command running `yigraf status --line --ctx-used …`) — mirroring mem:005 (a host doesn't hand a hook its token usage). Human-facing ambient stats ride a separate UI channel (the statusline), never folded into the agent's hook injection, honoring silence-as-feature.
