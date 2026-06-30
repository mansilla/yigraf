---
concerns:
- anchor: 5920a067bd0b0b0e36cab4758abb72b7c8a76e05784e4a96ac8300941fa40263
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/hooks.py#install_claude_hooks
family: memory
id: mem:010
maturity: working
provenance:
  source: cli
serves:
- int:hook-surfacing
status: active
supersedes: []
type: decision
---
## Claude hooks write the abs-interpreter wiring to settings.local.json, not the committed settings.json

**Why:** the interpreter path is per-machine; settings.local.json is Claude Code's designated per-machine file and a self-contained .claude/.gitignore keeps it out of git — symmetric with the post-commit git hook, which already bakes the abs path into the never-committed .git/hooks/. This keeps the run-without-the-venv-on-PATH property while never committing a machine path.

**Rejected:** a PATH-portable command (yigraf/uv run yigraf) in the committed settings.json — a Claude Code hook shell often lacks the project venv on PATH, which is the exact reason the abs path was used; portability there would silently fail-open
