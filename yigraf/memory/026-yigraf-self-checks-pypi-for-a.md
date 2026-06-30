---
concerns:
- anchor: 011a806d0ea0c909c17d97ccf3f36bfbdd2d835f5ad25efe3f7e3481e61fa31c
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/update.py#refresh
- anchor: 83f255232b206b3b9e0bdebdc2157e27819be47ebddca27dc2dfaf5751e376ca
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/update.py#available
family: memory
id: mem:026
maturity: working
provenance:
  source: cli
serves:
- int:status-surface
status: active
supersedes: []
type: decision
---
## yigraf self-checks PyPI for a newer release at most once a day, caches it in the gitignored .local sidecar, and surfaces an ⬆<version> marker on the statusline (+ a one-line update notice in a TTY) — the network fetch lives in update.refresh(), never in compute_status

**Why:** the user wanted a daily update check that asks before updating; with no cloud environment a scheduled Routine had nothing to fire into, so the check is built into yigraf on-use: refresh() is throttled to 1x/day and fail-open (offline/slow PyPI never blocks the statusline), and stamps checked_at even on failure so it won't re-hit the network every refresh. It rides the human ambient surface (statusline), not a hook injection — an update is the human's concern, not the agent's (design law #4). compute_status only does a pure .local read (update.available); the network call is isolated in refresh() and invoked solely by the human-facing status/statusline commands, so mem:013's 'core reads no host API' still holds (the sidecar is an on-disk artifact like the embedding index)

**Rejected:** A cloud-scheduled Routine (create_trigger) — no CCR environment exists to fire a session into; or a macOS LaunchAgent / ~/.zshrc check — a system-level change outside yigraf when the tool already runs constantly and has a human ambient surface (the statusline) to carry the nudge; or checking PyPI on every statusline refresh — would hammer the network and add latency, hence the 1x/day .local-cached throttle
