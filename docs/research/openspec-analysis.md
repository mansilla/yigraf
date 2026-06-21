# OpenSpec — Analysis

> Source: `origins/openspec` (Fission-AI/OpenSpec, `@fission-ai/openspec@1.4.1`).
> TypeScript ESM CLI distributed on npm. No daemon, no MCP — pure generated files + a queryable CLI.

## 1. The problem it solves

AI coding agents are unpredictable **when requirements live only in chat history**. When intent
is ephemeral:

- Human and agent never explicitly agree on *what* to build before code is written.
- Context evaporates on `/clear` or compaction — no durable record of intent, scope, approach.
- The "plan" can't be reviewed, versioned, or diffed.

OpenSpec inserts a **lightweight, durable, file-based spec layer** between human and agent.
Philosophy: *brownfield-first*, *iterative not waterfall*, *editor-agnostic*, *ceremony-light*
(its stated edge over Spec Kit and Kiro). Core principle: **specs describe externally-observable
behavior; implementation detail belongs in design.md/tasks.md** — so specs stay stable as the
source of truth while implementation churns.

## 2. How it works

### Integration — generated static files + a CLI that acts as the runtime API
No MCP, no daemon. Three layers:

1. **Tool adapters** (`src/core/command-generation/adapters/*.ts`) — ~32 of them. Each adapter
   knows only *where* its files go and *how* to format frontmatter. Adding a new agent = a path +
   a frontmatter formatter. The command/skill *body* is tool-agnostic and shared.
2. **Two delivery formats** from the same workflow body strings (`src/core/templates/workflows/*.ts`):
   **Skills** (`skills/openspec-*/SKILL.md`, auto-detected) and **slash commands** (`/opsx:*`).
3. **The CLI is the context API** — the cleverest piece. Generated bodies do **not** hardcode file
   layout. They tell the agent to shell out and parse JSON:
   - `openspec new change "<name>"` — scaffold the change dir
   - `openspec status --change "<name>" --json` — artifact-graph state
   - `openspec instructions <artifact-id> --change "<name>" --json` — template + per-artifact
     instructions + exact dependency paths to read
   The agent loops: read deps → write one artifact → re-query status → repeat until done.

### Data model on disk (all Markdown; config/schemas YAML)
```
openspec/
├── specs/<capability>/spec.md          # SOURCE OF TRUTH — current behavior
├── changes/<change>/
│   ├── proposal.md  design.md  tasks.md
│   ├── .openspec.yaml                   # change metadata
│   └── specs/<capability>/spec.md       # DELTA spec (ADDED/MODIFIED/REMOVED/RENAMED)
│   └── archive/YYYY-MM-DD-<name>/        # completed
└── config.yaml                          # project context + per-artifact rules + schema
```
Specs use a strict structure: `## Purpose`, `### Requirement:` (must contain SHALL/MUST),
`#### Scenario:` (WHEN/THEN, exactly 4 hashtags or it fails silently).

### Artifact-graph engine (the heart, "opsx")
Schemas (`schemas/spec-driven/schema.yaml`) declare artifacts with `id`, `generates`, `template`,
`instruction`, `requires` — forming a **DAG**.
- `ArtifactGraph` topo-sorts via Kahn's algorithm (`artifact-graph/graph.ts`).
- **State is derived purely from the filesystem** — no state file. `done` = the artifact's file
  exists; `ready` = all deps done; `blocked` otherwise (`state.ts`).
- `generateInstructions` assembles the agent payload: template + dependency paths/status +
  `unlocks` + project `context` + per-artifact `rules`, kept as *separate fields* (not prepended)
  with repeated "do NOT copy into the file" warnings.

### Lifecycle
Core profile: `propose → apply → sync → archive`. **apply** returns exact `contextFiles` to read +
parses `tasks.md` checkboxes for progress. **archive** merges delta specs into `specs/` then moves
the change to `archive/<date>-<name>/`. The **delta merge** (`specs-apply.ts`) is the most rigorous
code: parses ADDED/MODIFIED/REMOVED/RENAMED, pre-validates conflicts, applies in fixed order, and
stages writes atomically (all-or-nothing).

## 3. Ideas worth stealing

1. **Filesystem-as-state** — completion = "does the file exist." Zero drift; survives agent
   crashes, manual edits, git ops.
2. **CLI-as-context-API** — agent *queries* for exactly the paths/template it needs instead of
   ingesting a giant prompt. Deliberate token-efficiency / context-hygiene strategy.
3. **DAG where dependencies enable rather than gate** — same data model supports strict linear and
   fluid edit-anything flows.
4. **Delta specs as a typed patch language** — ADDED/MODIFIED/REMOVED/RENAMED with conflict
   detection and atomic apply. Clean brownfield spec evolution; reviewers see only the change.
5. **Schema/template externalization** — prompts live in editable YAML/MD, not compiled code.
6. **One tool-agnostic body + thin per-tool adapters** — cheap breadth across 25+ agents.

## 4. What's lacking

- **Tracks plans, not code.** Zero codebase awareness — no AST, no symbol index, no link from a
  requirement to the files/functions implementing it. `/opsx:verify` is just another prompt.
- **No conversation/episodic memory.** Persists intent artifacts, not the reasoning trail. Rejected
  approaches survive only if the agent wrote them into design.md.
- **No semantic understanding or token accounting.** Completion is byte-existence; validation is
  regex/structural (checks for SHALL/MUST and `####`), not meaning. No token-budget management.
- **Brittle Markdown formatting** — delta merge matches by normalized header text; typos fail
  silently or throw.
- **Agent compliance unenforced** — everything depends on the agent following multi-step skill
  instructions; "works best with high-reasoning models."
- **Spec/code can silently diverge** after archive — the spec is an aspirational contract, not a
  verified one.

## 5. Tech stack
TypeScript ESM, Node ≥20.19, built with `tsc`. Deps: `commander`, `@inquirer/*`, `zod`, `yaml`,
`fast-glob`, `chalk`/`ora`, `posthog-node` (opt-out telemetry). Vitest tests. Distributed as
`@fission-ai/openspec` (single `openspec` bin). Releases via Changesets.
