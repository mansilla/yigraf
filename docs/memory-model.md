# yigraf — Memory Model (the memory node + capture)

> Answers: *what is a memory node, and how is it captured?* Synthesizes ReCAP
> (`docs/research/recap-paper-analysis.md`), the harness post
> (`docs/research/harness-engineering-notes.md`), and the two parents. Retrieval decision below is
> **scoped hybrid** (decided 2026-06-17 — see §4).

## 0. The reframe (from ReCAP)

> **Memory is not a pile of stored facts — it is organized, linked, re-injectable context.**
> "How we organize and reinject context can matter as much as how much context we have." (ReCAP)

So the memory dimension is *not* a transcript log. It is: capture the **reasoning that's already
being produced** at decision points, **link** it into the graph, and **re-inject** it at the next
decision point. The value is organization + timing, not volume.

ReCAP's node is `(T, S)` = (thought, plan). yigraf splits it: the **plan** dimension owns `S`; the
**memory** dimension owns `T` — the *why*. A yigraf memory node is a **persisted, linked `T`**.

## 1. What a memory node IS

A durable, versioned record of a **reasoning event** captured during work — a decision, constraint,
rejected alternative, or learned fact — linked to the intent it serves and the code it concerns.

**Fields**
| field | meaning |
| --- | --- |
| `id` | stable id |
| `type` | `decision` \| `constraint` \| `rationale` \| `rejected-alternative` \| `learned-fact` \| `preference` |
| `statement` | the claim in one line ("session refresh uses optimistic locking") |
| `why` | the reasoning (ReCAP's `T`) — the thing chat history loses on `/clear` |
| `alternatives` | optional: what was rejected and why (the highest-value, most-perishable content) |
| `provenance` | source (session/turn/PR/commit), `confidence` (`EXTRACTED` if explicit, `INFERRED` if distilled), anchor commit/timestamp |
| `status` | `active` \| `superseded` \| `archived` + last-referenced (for salience/decay) |

Plus **maintained counters** (`refs_in`, `superseded_in`, `usage`, `survival`, …) that drive
relevance, GC, and the `working → settled` maturity promotion — full spec in `docs/graph-design.md`
§3. Counters are bumped incrementally on edge mutation so relevance is an O(1) read, not a traversal.

**Edges (the differentiator — cross-family, à la the vision doc)**
- `serves` / `decided-for` → an **intent/plan** node
- `concerns` / `constrains` → a **structure** (code) node
- `supersedes` / `refines` / `contradicts` → another **memory** node (delta-style evolution)

A memory node with no edges is noise. The point is the links: they let the structural retriever pull
a decision in *because the agent touched the code it concerns*, and let drift checks fire when
`concerns`-linked code changes.

## 2. How it gets captured (layered; lead choice is the open decision)

Philosophy from the harness post: capture must be **low-friction** and happen **at the moment of
decision or correction** ("when the agent struggles, identify what's missing and feed it back";
"promote the rule into code"). From ReCAP: the reasoning `T` is *already generated* at each
plan/refine step — so capture = **persist the `T` that already exists**, not run a separate
write-everything pass.

1. **Decision-point capture (primary, ReCAP-aligned).** When the agent makes a non-obvious choice, a
   skill instructs it to call e.g. `yigraf remember --type decision --serves <intent> --concerns
   <symbol> --why "<reasoning>" "<statement>"`. `EXTRACTED`, cheap, high-signal. This is the
   memory-dimension analog of v0's agent-asserted `implements` edge.
2. **Correction/feedback capture (high value).** When the user corrects the agent or a review comment
   lands, capture it as a `constraint` node — and, per the post's review→doc→code ladder, flag it as a
   candidate to **promote into an enforced drift check**. Corrections are the richest, most reusable
   memories.
3. **Pre-`/clear` distillation (backstop).** A Stop-style hook runs a distillation pass at task end /
   before context reset: "extract decisions, constraints, rejected approaches not already captured."
   Non-deterministic and pricier → safety net, not primary. (This is the durable analog of ReCAP's
   structured handoff.)
4. **Mining existing artifacts (bootstrap).** Graphify-style extraction of rationale from code
   comments (`# WHY/# HACK`), commit messages, PR descriptions, design.md → seed memory from what the
   repo already holds.

**Recommended lead: #1 + #2** (agent-asserted at decision/correction time), with #3 as backstop and
#4 for bootstrap. Rationale: highest signal-to-noise, deterministic, `EXTRACTED` confidence, and it
mirrors the v0 pattern we already trust. **Open decision → §5.**

## 3. Re-injection (memory's payoff)

Memory nodes are re-injected by the **same fail-open hook as v0**: when the agent acts on code, the
hook surfaces `concerns`-linked constraints/decisions and any drift. This generalizes ReCAP's
intra-task structured injection to **across sessions / across `/clear`**. A captured memory the agent
never sees again is worthless ("can't see it ⇒ doesn't exist").

## 4. Retrieval — scoped hybrid (decided)

- **Structure + plan:** Graphify's IDF + hub-aware, token-budgeted graph traversal. No embeddings.
- **Memory + intent:** add a **lightweight embedding index over `statement` + `why` text** for
  semantic recall ("what did we decide about sessions, and why?"), **fused** with graph-proximity
  (memories whose `concerns`/`serves` neighbors are in the current scope rank up).
- Embeddings live *only* over the memory/intent node families — we don't pay vector cost for code
  queries Graphify already nails. Fusion = reciprocal-rank-style merge of (semantic score,
  graph-proximity score).

## 5. Capture mechanism — decided + shipped (M7)

**Which capture mechanism leads, and how heavy is the distillation backstop?**
- (A) Agent-asserted only (#1+#2) — cheapest, deterministic, but misses what the agent doesn't think
  to record.
- (B) Agent-asserted + always-on pre-`/clear` distillation (#1+#2+#3) — better recall, higher cost,
  some noise.
- (C) Distillation-first — capture mostly by end-of-session mining; least friction during work, most
  drift from ground truth.

**Resolved (2026-06-24): (A) for the first memory milestone**, shipped in **M7** as
`remember`/`note-constraint`/`supersede` (`docs/m7-notes.md`). (B) — the pre-`/clear` distillation
backstop — and the boundary-A/B nudges remain deferred until agent-asserted capture proves
insufficient (caveats M7).

Embedding engine — local `bge-small-en-v1.5` default, plain-file index + brute-force cosine, pluggable
backends, graceful fallback to lexical-only — **shipped in M8** (`docs/m8-notes.md`); spec:
`docs/retrieval-design.md` §10. §4's scoped-hybrid fusion (semantic seeder unioned with the lexical
seeder, fused into ranking) is live there too.
