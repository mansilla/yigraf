# yigraf — M6 Notes (dogfood on itself + measurement)

> yigraf indexing yigraf. This is the forcing function from `docs/BUILD-PLAN.md` M6 and the proof of
> `docs/yigraf-v0.md`'s three success criteria. Run 2026-06-24 after M1–M5.

## 1. Setup (committed into this repo)

- `yigraf init .` → the `yigraf/` workspace at repo root (src-layout keeps it from colliding with the
  `src/yigraf/` package). `yigraf build .` → **284 nodes, 511 edges across 26 files**.
- **5 intents** for yigraf's own behavioral contracts: `structure-index`, `enforceable-link`,
  `drift-detection`, `token-cheap-context`, `hook-surfacing` (each with SHALL + Given/When/Then).
- **1 plan** `yigraf-v0` with 5 tasks, each `tracks` its intent and `implements` the real symbols that
  realize it (e.g. `task:yigraf-v0/3 → drift.py#compute_drift, drift.py#resolve_renames`). `yigraf drift`
  is clean after linking.
- Hooks installed: the git `post-commit` rebuild, and the Claude Code `PostToolUse`/`SessionStart`
  hooks + `.claude/skills/yigraf/SKILL.md` + the `AGENTS.md` block. (`.claude/` is under this
  machine's global gitignore, and `.claude/settings.json` is also in the repo `.gitignore` since it
  bakes a machine-specific interpreter path — caveats M5; regenerate with `yigraf install-claude-hooks`.
  `AGENTS.md`, which carries the always-on guidance, *is* committed.)

## 2. Success criteria (`docs/yigraf-v0.md`) — met on yigraf's own repo

1. **Unprompted governing intent + drift while editing.** `yigraf hook post-tool-use` on
   `src/yigraf/drift.py` (governed) injects the governing intent + task + (if any) drift; on
   `tests/test_drift.py` (ungoverned) it is silent. ✓
2. **Measured token win.** `yigraf context "drift detection"` ≈ **505 tokens** vs **~1278 tokens** to
   read just `src/yigraf/drift.py` (**2.5× cheaper**) — and the context *also* returns the governing
   intent, the plan/tasks, the implementing signatures, and drift status, none of which the raw file
   gives. The real-world gap is larger: without the graph an agent greps and reads *several* files
   and still doesn't get the intent/drift. ✓
3. **Edges survive.** Links live in committed plan frontmatter + `graph.json` (survive crash); the
   `SessionStart(clear)` hook re-injects the active plan after `/clear`; an unrelated-file edit leaves
   the hook silent and the anchors untouched. ✓

## 3. Findings from dogfooding (see `docs/caveats.md`)

- **Plan-node fan-out.** A query about one task pulls in *all* sibling tasks via the shared `plan`
  node (1 hop), so `context` lists the whole plan. Useful as orientation, verbose for a narrow query —
  logged as a caveat; candidate fixes: treat `plan` as a soft hub, or down-weight siblings.
- **`file:`/`module:` nodes still surface** alongside the matched symbol (noted in M4 caveats) — real
  here too.
- The numbers above are the operational record for v0 success-criterion #2.

## 4. Status

v0 spine (M0–M6) is complete and self-hosted. The live, interactive Claude Code done-test (editing a
governed symbol in a real session and watching the injection appear; `/clear` and watching the plan
reappear) is the one remaining manual check — the hook *commands* are verified to produce the right
payloads on this repo, so the only unverified link is Claude Code actually consuming `additionalContext`
on `PostToolUse` (logged as a caveat to confirm live).
