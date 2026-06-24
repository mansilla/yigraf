# yigraf — M5 Implementation Notes (Claude Code hooks + skill)

> Pins the **verified** Claude Code hook contract (R8 said: confirm `additionalContext` shapes
> against current docs before coding — done 2026-06-24 via the claude-code-guide agent, fetched from
> `code.claude.com/docs/en/hooks`) and the M5 wiring. The injection content reuses M4 retrieval
> (`context_for_locus` / `session_context`); this milestone is the host glue.

## 1. Verified hook contract (current Claude Code)

- **PostToolUse** — stdin carries `tool_name`, `tool_input`, `cwd`, `hook_event_name`. To inject,
  print **only** this to stdout and exit 0:
  ```json
  {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "…"}}
  ```
  `additionalContext` *is* added to the model's next turn (confirmed — not only UserPromptSubmit/
  SessionStart). Exit 0 = fail-open (never blocks the edit; the tool already ran).
- **SessionStart** — stdin carries `source` ∈ `startup|resume|clear|compact` + `cwd`. Same stdout
  shape with `"hookEventName": "SessionStart"`. `clear|compact` is the "memory survives /clear"
  mechanism (R8).
- **settings.json** — `hooks.<Event>` is an array of `{matcher, hooks:[{type:"command", command, timeout}]}`.
  `matcher` is **pipe-separated literals, not regex**: `Edit|Write` (tool names), `clear|compact`
  (sources). `timeout` is in **seconds**. `${CLAUDE_PROJECT_DIR}` is available.

## 2. The two entry points (`yigraf hook …`)

- `yigraf hook post-tool-use` (matcher `Edit|Write`): reads the event, resolves `tool_input.file_path`
  (or `.path`) relative to `cwd`, and if it's a `.py` file under a yigraf workspace, runs
  `context_for_locus`. **Silent-unless** the locus is governed (an `implements`/`tracks`/`concerns`
  edge points at one of its symbols) or has drift — so routine edits inject nothing.
- `yigraf hook session-start` (matcher `startup|resume|clear|compact`): runs `session_context` —
  re-injects the active plan + governing intents + drift, so a flow survives `/clear`.
- Both are **fail-open**: any parse/build error → exit 0, no output (a hook must never break the
  session). The graph is rebuilt per invocation but the SHA cache means only the touched file
  re-parses.

## 3. Installer — `yigraf install-claude-hooks`

Merges the two hook entries into `.claude/settings.json` (idempotent, keyed by the `hook <verb>`
command; never clobbers foreign hooks or other keys), writes `.claude/skills/yigraf/SKILL.md` (the
context-first + link-on-task-done ritual), and maintains a marked block in `AGENTS.md`. Commands bake
in the absolute interpreter (`"<python>" -m yigraf hook …`) so they run regardless of `PATH`; the
hook reads the repo root from the event's `cwd` (no path baked in). See the portability caveat below.

## 4. Done-test (manual — requires a real Claude Code session)

The unit tests drive the entry points via stdin JSON; the BUILD-PLAN's done-test is a live session:
editing a linked+drifted symbol surfaces the reconcile message unprompted; editing unrelated code
stays silent; after `/clear`, the active plan reappears. Verify once during M6 dogfood.

## 5. Out of scope for M5

- **UserPromptSubmit / PreCompact** wiring, the full three-boundary capture taxonomy (D8) → post-v0.
- **Memory re-injection** at SessionStart (only plan+intent for now) → memory milestone.
- **Auto-invocation reliability of the skill** is model-driven; the hooks are the guaranteed net.
