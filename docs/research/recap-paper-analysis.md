# ReCAP — Analysis (NeurIPS 2025)

> "ReCAP: Recursive Context-Aware Reasoning and Planning for Large Language Model Agents,"
> Zhenyu Zhang, Tianyi Chen, Weiran Xu (equal), Alex Pentland, Jiaxin Pei. Stanford CS / Stanford
> HAI / MIT Media Lab. OpenReview `r2ykUnzuGt`. Read from the full PDF (10pp main body).
> Feeds the memory-node design in `docs/memory-model.md`.

## 1. Problem

Long-horizon tasks break two ways: **sequential** prompting (ReAct/Reflexion) suffers *context
drift* — early high-level goals scroll out of the window → goal loss and recurrent failure cycles;
**hierarchical** prompting (ADaPT/THREAD) runs subtasks in *isolated local contexts* → loses
cross-level continuity, or pays heavy runtime overhead. The need: commit to a plan while staying
flexible to feedback and coherent across levels of reasoning.

## 2. Method — three mechanisms over a shared "context tree"

ReCAP frames execution as a recursive process inside **one shared LLM context** that unfolds into a
context tree. Each node holds a **thought `T`** and an **ordered subtask list `S = ⟨s₀…sₘ₋₁⟩`**.

1. **Plan-ahead decomposition.** A planning fn `π(C) → (T, S)` emits the *full* ordered subtask list
   in one pass; the agent executes only the head `S[0]`, keeps the rest for later. Avoids myopic,
   one-subtask-at-a-time drift.
2. **Consistent multi-level context via structured (re-)injection.** When `S[0]` is composite, recurse
   on `C ∥ ⟨T, S, S[0]⟩`. On return from a subgoal, **re-inject the parent's remaining plan**
   `C ← C ∥ ⟨T, S[1:]⟩`, then refine via `ρ(C) → (T', S')`. This keeps high-level intent *proximal to
   the current decision point* instead of letting it scroll away. Backtracking = returning to the
   parent and re-injecting its state.
3. **Memory-efficient scalability.** The active prompt is a **sliding window of K≈64 rounds**; older
   rounds drop out of the active prompt but critical planning info is *reintroduced by injection*, so
   truncation never loses high-level intent. Few-shot examples placed once at init (not re-injected
   per call). Active prompt and external tree both scale `O(d·L̄)` with tree depth `d`, not with total
   trajectory length.

Algorithm 1 (essence):
```
(T,S) ← π(C)
while S not empty:
  if S[0] primitive:  O ← E(S[0]); C ← C ∥ ⟨T,S,S[0],O⟩      # act, append observation
  else:               C ← ReCAP(C ∥ ⟨T,S,S[0]⟩)              # recurse
  C ← C ∥ ⟨T, S[1:]⟩                                          # re-inject parent remaining plan
  (T,S) ← ρ(C)                                                # refine the rest
return C
```

## 3. Results

pass@1 (strict, single trajectory, GPT-4o; GPT-4.1 for SWE-bench): ALFWorld **91** (ReAct 84);
Robotouille sync **70** (ReAct 38, **+32**); async **53** (ReAct 24, **+29**); FEVER 63.5 (tie);
SWE-bench Verified **44.8** (ReAct/mini-SWE 39.6). Holds across Qwen2.5-32B/72B, LLaMA-4-400B,
DeepSeek-V3 — ReCAP > ReAct on every model, no tuning. **Ablations:** removing reasoning traces
(no_think 60, name_only 55) and restricting recursion depth (level_2 → **0**, level_3 → 10) collapse
performance; passing *more* think history (think_many 70) and tighter context windows don't hurt.
⇒ the **explicit reasoning trace per node and the recursive depth are what carry the gains**, not
verbosity.

## 4. Why it matters for yigraf (and the honest caveat)

**Caveat first:** ReCAP's "memory" is *intra-task working memory* — how to organize and re-inject the
*active* reasoning context within a single long-horizon run. It is **not** persistent, cross-session,
episodic/semantic memory (the thing yigraf's "memory dimension" originally meant). Don't conflate them.

But the connection is real and deep, in three ways:

1. **A node model.** ReCAP's node `(T, S)` = (reasoning, plan). yigraf *splits* these into its
   **memory** dimension (`T` — the thoughts/decisions/why) and its **plan** dimension (`S` — the
   ordered tasks). The "decision log" field already in `docs/yigraf-v0.md` is precisely a *persisted
   `T`*. ReCAP gives the unit; yigraf persists and links it.
2. **Re-injection = our hook, generalized.** ReCAP's "structured injection keeps high-level intent
   proximal to the decision point" *within a task*. yigraf's fail-open context-injecting hook does the
   same thing **across `/clear` and across sessions** — re-injecting the relevant intent/memory at the
   moment the agent acts. ReCAP solves the intra-session version of yigraf's exact problem.
3. **Their future work literally describes yigraf.** Discussion §5: *"Future work may explore
   structuring memory as an executable graph, enabling more targeted retrieval and … memory-aware
   routing … improving how context is organized and used, rather than how much is stored."* And the
   closing line: **"how we organize and reinject context can matter as much as how much context we
   have."** That is yigraf's thesis, validated by a NeurIPS paper.

**The reframe to adopt:** memory is not a pile of stored facts — it is **organized, linked, and
re-injectable context**. The win is in *organization + re-injection at the decision point*, not in
volume. This directly shapes the memory model: capture the reasoning that's already being produced,
link it, and re-inject it — don't build a write-everything log.

**Limitations to inherit awareness of:** ReCAP delegates *all* decomposition/validation to the LLM
(no external grounding) and is sensitive to model quality. yigraf's graph + drift check is exactly
the *external grounding* ReCAP lacks — a complementary fit.
