# Harness Engineering (OpenAI) — Notes for yigraf

> Source: OpenAI, "Harness engineering: leveraging Codex in an agent-first world," Ryan Lopopolo,
> **11 Feb 2026** — read from the **primary text** (full article). Earlier draft of these notes was
> reconstructed from secondary write-ups and imported several claims that are NOT in this post; see
> §4 for the corrections. Relates to `docs/yigraf-vision.md`, `docs/yigraf-v0.md`,
> `docs/research/openspec-analysis.md`, `docs/research/graphify-analysis.md`.

## 1. What THIS post actually says

A 3-engineer (now 7) team shipped an internal beta product — ~1M lines, ~1,500 merged PRs, 3.5
PRs/engineer/day, ~1/10th the time — with **zero hand-written code**; every line (app, tests, CI,
docs, tooling, dashboards) written by Codex. Humans steer, agents execute. The lessons:

- **The engineer's job shifts** from writing code to *designing environments, specifying intent,
  and building feedback loops*. When the agent fails, the question is never "try harder" — it's
  **"what capability is missing, and how do we make it both *legible* and *enforceable* for the
  agent?"** (This legible+enforceable pairing is the spine of everything below.)
- **"Anything it can't access in-context while running effectively doesn't exist."** Knowledge in
  Google Docs, Slack, or people's heads is invisible to the agent. The Slack thread that aligned the
  team on an architecture is, to the agent, as unknown as it would be to a new hire three months
  later — *unless it's encoded into repo-local, versioned artifacts* (code, markdown, schemas,
  plans). They continuously pushed more context into the repo.
- **Repository knowledge as the system of record — "a map, not a 1,000-page manual."** The "one big
  AGENTS.md" failed predictably: (a) context is scarce — a huge file crowds out the task; (b) too
  much guidance becomes non-guidance ("when everything is important, nothing is"); (c) it rots into
  stale rules; (d) a single blob can't be mechanically verified. Fix: a ~100-line AGENTS.md that is
  a **table of contents**, pointing into a structured `docs/` tree (design-docs, exec-plans,
  product-specs, references, generated). **Progressive disclosure**: small stable entry point, the
  agent is taught where to look next.
- **Plans are first-class, versioned artifacts.** Lightweight ephemeral plans for small changes;
  **execution plans with progress *and decision logs* checked into the repo** for complex work.
  Active / completed / tech-debt plans are co-located and versioned so agents need no external
  context. *(This decision-log idea is the strongest primary-source grounding for our memory
  dimension — see §3.)*
- **Mechanical enforcement, not documentation.** Rigid layered architecture per domain
  (`Types → Config → Repo → Service → Runtime → UI`; cross-cutting concerns enter only via a single
  `Providers` interface), enforced by **custom linters + structural tests**, not prose. *"Enforce
  invariants, not micromanage implementations"* — enforce boundaries centrally, allow autonomy
  locally. Key line: **"Because the lints are custom, we write the error messages to inject
  remediation instructions into agent context."**
- **The escalation ladder for taste:** review comment → documentation → code. *"When documentation
  falls short, we promote the rule into code."* Human taste is captured once, then enforced
  continuously.
- **Entropy / garbage collection.** Agents replicate existing patterns, including bad ones → drift.
  Manual cleanup ("every Friday, 20% of the week, on AI slop") didn't scale. Fix: encode "golden
  principles" + **background Codex tasks** that scan for deviations, update quality grades, and open
  small auto-mergeable refactoring PRs. Plus a recurring **doc-gardening agent** for stale docs.
- **Agent legibility is the goal.** Optimize the repo for the *agent's* legibility, not human style.
  Favor "boring"/composable tech (stable APIs, well-represented in training data); sometimes
  reimplement a subset rather than depend on opaque upstream behavior (e.g. their own
  map-with-concurrency helper instead of `p-limit`, 100% covered).
- **Runtime legibility too:** the app is bootable per git worktree; Chrome DevTools Protocol +
  an ephemeral observability stack (LogQL/PromQL/TraceQL) are wired into the agent so it can
  reproduce bugs, validate fixes, and reason about UI/perf ("startup < 800ms" becomes tractable).
- **Throughput changes merge philosophy:** minimal blocking gates, short-lived PRs, flakes get a
  re-run not a block — "corrections are cheap, waiting is expensive." Review is pushed agent↔agent
  (a "Ralph Wiggum Loop" of self-review until reviewers are satisfied).
- **Honest unknowns:** they don't yet know how architectural coherence holds over *years* of fully
  agent-generated code, or how it evolves as models improve. The durable claim: *"discipline shows
  up more in the scaffolding than in the code."*

## 2. The reframe for yigraf: **legible + enforceable, retrofit onto brownfield**

The post's whole frame — *make the missing capability legible AND enforceable* — is exactly
yigraf's two jobs:

- **Legible** = the graph + the scoped-subgraph retrieval surface (structure + intent + plan +
  memory), serving "a map, not a manual."
- **Enforceable** = the intent↔code drift check whose output is a **remediation instruction injected
  into agent context** — the precise mechanism the post credits for keeping a 1M-line agent codebase
  coherent.

Crucial difference in our favor: OpenAI built **greenfield**, with total control to restructure the
repo and docs for agent legibility from commit one. yigraf must make **existing, brownfield** repos
legible **without** asking the user to restructure — by deriving the graph (Graphify's extraction)
and layering plans/intent on top (OpenSpec's model). **yigraf retrofits the legibility layer the
post says you need.** That is the product wedge, stated in their own terms.

Scope clarity from the post: legibility has a *static* axis (structure/plan/memory — **yigraf's
lane**) and a *runtime* axis (logs/metrics/UI driving — **not yigraf's lane**; that's the harness
owner's). Don't scope-creep into runtime legibility.

## 3. Principles → our five dimensions (only what's actually in the post)

| Post principle | Implication for yigraf | Dimension |
| --- | --- | --- |
| "Can't access in-context ⇒ doesn't exist." | Runtime **injection timing is co-primary with graph quality**. A graph nobody reads at the decision moment is worth zero → fail-open hooks are core, not optional. | all / token-eff |
| "A map, not a 1,000-page manual"; progressive disclosure. | Serve **scoped subgraphs within a token budget**, never dumps. Validates the OpenSpec CLI-as-context-API + Graphify token-budgeted retriever synthesis. | token-eff |
| Custom lints **inject remediation into context**. | The intent↔code link is an **active, context-injecting drift check** with the fix in the message — not a passive marker. This is the bridge neither parent has. | semantics / plan / structure |
| "When docs fall short, promote the rule into code" (review → doc → code). | A captured constraint/decision should be **promotable** from a passive memory node → an enforced drift check. Design the ladder in. | memory → enforcement |
| Plans = first-class versioned artifacts **with decision logs**. | Strong primary grounding for **both** the plan dimension (versioned tasks/state) **and** memory (the decision log = "why we chose X / rejected Y," encoded in-repo so it survives the agent's context). | plan / memory |
| "Boring, composable, in-repo-reasonable" tech. | yigraf should be inspectable and in-repo (plain artifacts, no opaque service) so the agent can reason about *it* too. | (meta) |
| Background GC agents + doc-gardening. | Reuse Graphify's detached-git-hook pattern to run **drift/staleness scans in the background** and open reconcile tasks. | structure / plan |
| Enforce invariants, not implementations. | The drift check enforces the *boundary* (does code still satisfy intent), never *how* it's written. | semantics |

## 4. Corrections — claims my earlier notes wrongly attributed to this post

These were imported from secondary write-ups and are **NOT** in the OpenAI article:

- **"Context anxiety / capacity masking / compaction / context reset + handoff artifacts."** Not
  here. The post treats context management as "give a map, push knowledge into the repo" — no
  anxiety/masking taxonomy. *(Our memory-as-durable-state argument still holds, but now rests on the
  post's actual "can't-see-it-doesn't-exist" + "decision logs in repo" lines, not on "context
  reset.")*
- **GAN-style Generator/Evaluator separation + the Anthropic $9-vs-$200 experiment.** Not here. The
  post does describe **agent↔agent review** (self-review + additional agent reviewers in a loop),
  but not the GAN/self-eval-bias framing.
- **Hashline / line-hash edit format (6.7%→68.3%, −20% tokens).** Not here. Separate work.
- **MCP selectivity ("tool defs cost tokens, connect only needed servers").** Not stated here.
- **"Every component is waiting to be made redundant — that's the goal."** Not here. The post's
  actual stance on the future is *humbler/uncertain* ("we don't know how this evolves as models
  improve").
- **Dual-query / semantic-vs-exact retrieval / hybrid vector DB.** **Not in the post at all** — that
  was the vector-DB vendor's framing. ⇒ **The post gives zero guidance on semantic search.** Our
  retrieval/embeddings decision is entirely ours to make — that's the next discussion, tracked in
  `docs/yigraf-v0.md` §"Next milestone."

## 5. Net effect

The primary *tightens* yigraf rather than redirecting it: it confirms legible+enforceable, the
"doesn't exist if not in context" law, mechanical enforcement with remediation-in-the-error, and
plans+decision-logs as versioned artifacts — and it removes the imported scaffolding we didn't need.
The concrete consequence is the revised v0 in `docs/yigraf-v0.md`: **ship the enforcement+injection,
not just the store.**
