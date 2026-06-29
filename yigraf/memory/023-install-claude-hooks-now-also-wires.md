---
concerns:
- anchor: 75830fd993be4186a548fa13670acf7cdf57058c7019cc0d825505e873be67a8
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/hooks.py#_ensure_statusline
family: memory
id: mem:023
maturity: working
provenance:
  source: cli
serves:
- int:status-surface
status: active
supersedes: []
type: decision
---
## install-claude-hooks now also wires Claude Code's statusLine to 'yigraf status --color' so the [Yigraf] graph-health bar is always visible, not opt-in

**Why:** the hooks speak into the agent's context, but the [Yigraf] brand + graph health is the human's ambient surface and was previously never wired by any install path, so a README install never saw it; wiring it on install makes it always-on. Non-clobbering: a foreign statusLine is kept (kept-foreign), only an absent or yigraf-owned one is set/refreshed — same abs-interpreter-in-settings.local.json approach as the hooks (mem:010)

**Rejected:** Clobbering any existing statusLine to force the bar — hostile to a user's own status bar; or leaving it opt-in via docs — a README install would never show the brand we just built
