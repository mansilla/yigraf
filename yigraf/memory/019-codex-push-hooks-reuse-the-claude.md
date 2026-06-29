---
concerns:
- anchor: ec6194bfc717e9c39d91d649db7212c247a86cbe47e16a44f114db025ee402bf
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/cli.py#_edited_file
family: memory
id: mem:019
maturity: working
provenance:
  source: cli
serves:
- int:multi-host
status: active
supersedes: []
type: decision
---
## Codex push hooks reuse the Claude Code handlers verbatim; only the install target differs (.codex/hooks.json). apply_patch path is parsed from the patch, best-effort + fail-open

**Why:** Codex's hook contract mirrors Claude Code's (same tool_name/tool_input/cwd in, hookSpecificOutput.additionalContext out), so generalizing _edited_file to also parse apply_patch's '*** Update File:' line is the only new logic — the handlers and output envelope are shared. The exact edit-tool name + hooks.json schema are version-sensitive, so PostToolUse stays best-effort and silent on a mismatch (R8 fail-open); SessionStart is the reliable win. Codex paths are repo-relative, so they're anchored to root before resolving.

**Rejected:** a separate Codex-specific handler — needless duplication when the contract already matches; or a broad '.*' PostToolUse matcher — fires yigraf on every tool call (Read/Bash), wasteful
