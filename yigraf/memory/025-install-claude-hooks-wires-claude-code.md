---
concerns:
- anchor: c2ccf9296e8b36f1250f03901a9f79c1ef1bf153be03d1ee49bf55c55719bb1d
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/cli.py#statusline_cmd
- anchor: 0a791e94b09fba66067ef629363c2176ddc84a8be781d9c37e91e1dd6304951d
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/cli.py#_claude_ctx
- anchor: 59982f9b71548591d00f6c6e9bd2461aefeac1ef6be8fd45e6dff3caf742cf33
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/hooks.py#_ensure_statusline
family: memory
id: mem:025
maturity: working
provenance:
  source: cli
serves:
- int:status-surface
status: active
supersedes:
- mem:024
type: decision
---
## install-claude-hooks wires Claude Code's statusLine to a dependency-free Python adapter command (yigraf statusline) that renders the [Yigraf] bar + context-window gauge — no jq, no bash, cross-platform

**Why:** the bash+jq adapter only showed the ctx gauge where jq was installed and never ran on Windows; since yigraf is already a Python program, the adapter command parses Claude Code's stdin event + transcript with stdlib json (zero deps) so the gauge is universal. mem:013 is still honored: the transcript parse lives in this host-specific command (_claude_ctx), never in the agnostic compute_status core. Ownership recognizes the old bash 'yigraf-statusline' and plain 'yigraf status' wiring so an upgrade refreshes in place and deletes the retired .sh; a foreign statusLine is still kept

**Rejected:** Keep the bash+jq adapter (jq-optional) — the ctx gauge then only appears where jq is present and never on Windows, so it is not 'available for every user'; or read the transcript inside compute_status — violates mem:013 (the agnostic core must never read a host transcript)
