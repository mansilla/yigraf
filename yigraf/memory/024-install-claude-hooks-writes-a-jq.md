---
concerns:
- anchor: 59982f9b71548591d00f6c6e9bd2461aefeac1ef6be8fd45e6dff3caf742cf33
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/hooks.py#_ensure_statusline
- anchor: 273b929aad7552e4970fc24d88c2a7629ccb3d3e80f79e606a2b0bbbc744cfcf
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/hooks.py#_write_statusline_adapter
family: memory
id: mem:024
maturity: working
provenance:
  source: cli
serves:
- int:status-surface
status: active
supersedes:
- mem:023
type: decision
---
## install-claude-hooks writes a jq-optional bash adapter (.claude/yigraf-statusline.sh) and points Claude Code's statusLine at it, so every user gets the [Yigraf] bar — plus the ctx gauge when jq is present, and the bar alone when it isn't

**Why:** shipping the adapter (not just 'yigraf status --color') means the context-window gauge is available to everyone, not only on a machine with a hand-written adapter. jq is made optional so a missing jq degrades to the bar-without-gauge instead of breaking the statusline (fail-open). The script bakes this clone's interpreter path (like the hooks) so it's gitignored and per-machine; ownership is recognized by 'yigraf-statusline' OR the old 'yigraf status' string so an upgrade refreshes in place; a foreign statusLine is still kept

**Rejected:** A bash+jq HARD dependency — breaks the bar where jq is absent; or a Python 'yigraf statusline' command reading the transcript in-core — would violate mem:013 (the agnostic core never reads a transcript); the adapter is the host-specific layer where that parse belongs
