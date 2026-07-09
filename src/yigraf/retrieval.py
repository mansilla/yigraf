"""Query-driven retrieval: a question → a scoped, token-budgeted subgraph (M4, retrieval-design.md).

The "legible" payoff. A pipeline of **seed → bounded traversal → fusion rank → token-budgeted
render → drift surfacing** (retrieval-design §1). v0 uses the **lexical/IDF seeder only** (no
embeddings — that's the memory milestone, §8) over structure + intent + plan, and renders structure
nodes as **locator + signature, not source** — the token-efficiency core.

Also computes the R9c reconcile signal: an intent marked ``satisfied`` but not ``verified`` (no live
``implements`` link, or a drifted one) surfaces a reconcile line, derived from the M3 drift signal.
"""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx

from yigraf import counters
from yigraf.drift import compute_drift

#: Edges that count toward a node's incoming "importance" (refs_in). Shared with the GC/relevance
#: engine so the two notions of "referenced" can't drift apart.
_SEMANTIC_RELATIONS = counters.SEMANTIC_RELATIONS

#: Seed-match precedence weights (exact > prefix > substring), retrieval-design §2.
_EXACT, _PREFIX, _SUBSTR = 1.0, 0.6, 0.3

_FAMILY_ORDER = ["intent", "plan", "structure", "memory"]
_FAMILY_HEADING = {
    "intent": "Intent",
    "plan": "Plan & tasks",
    "structure": "Code",
    "memory": "Decisions (why)",
}


# --------------------------------------------------------------------------------------------------
# Tokenization + corpus
# --------------------------------------------------------------------------------------------------

_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


def terms(text: str) -> list[str]:
    """Lowercased terms, splitting identifiers on case, ``_``, ``.``, ``/`` and other punctuation."""
    out: list[str] = []
    for chunk in re.split(r"[^A-Za-z0-9]+", text):
        out.extend(m.group(0).lower() for m in _CAMEL.finditer(chunk))
    return out


def _searchable(node_id: str, attrs: dict) -> str:
    """The text a node is matched against: its id plus family-specific content."""
    bits = [node_id, str(attrs.get("label", ""))]
    family = attrs.get("family")
    if family == "intent":
        bits.append(str(attrs.get("statement", "")))
        bits.extend(attrs.get("scenarios") or [])
        if attrs.get("design"):
            bits.append(str(attrs["design"]))
    if family == "memory":
        # Match a decision on its statement + the "why" (the words an agent would query for).
        bits.append(str(attrs.get("statement", "")))
        bits.append(str(attrs.get("why", "")))
        if attrs.get("alternatives"):
            bits.append(str(attrs["alternatives"]))
        bits.append(str(attrs.get("kind", "")))
    if attrs.get("signature"):
        bits.append(str(attrs["signature"]))
    return " ".join(bits)


@dataclass
class _Corpus:
    node_terms: dict[str, set[str]]
    idf: dict[str, float]


def _build_corpus(graph: nx.DiGraph) -> _Corpus:
    node_terms: dict[str, set[str]] = {}
    df: dict[str, int] = {}
    for node_id, attrs in graph.nodes(data=True):
        tset = set(terms(_searchable(node_id, attrs)))
        node_terms[node_id] = tset
        for t in tset:
            df[t] = df.get(t, 0) + 1
    n = max(len(node_terms), 1)
    idf = {t: math.log(1 + n / count) for t, count in df.items()}
    return _Corpus(node_terms=node_terms, idf=idf)


# --------------------------------------------------------------------------------------------------
# Seed → traverse → rank
# --------------------------------------------------------------------------------------------------


def _match_scores(corpus: _Corpus, query_terms: list[str]) -> dict[str, float]:
    """IDF-weighted, precedence-graded match of the query against every node (0 = no match)."""
    scores: dict[str, float] = {}
    for node_id, tset in corpus.node_terms.items():
        total = 0.0
        for q in query_terms:
            weight = corpus.idf.get(q, math.log(2))
            if q in tset:
                prec = _EXACT
            elif any(t.startswith(q) or q.startswith(t) for t in tset):
                prec = _PREFIX
            elif any(q in t for t in tset):
                prec = _SUBSTR
            else:
                continue
            total += weight * prec
        if total > 0:
            scores[node_id] = total
    return scores


def _seeds(match: dict[str, float], config: dict) -> list[str]:
    """Top seeds with a score-gap cutoff (stop at the first big drop), capped at ``seed_cap``."""
    r = config.get("retrieval", {})
    k, cap = r.get("seeds", 5), r.get("seed_cap", 6)
    ranked = sorted(match.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
    chosen: list[str] = []
    for i, (node_id, score) in enumerate(ranked):
        if i > 0 and score < 0.5 * ranked[i - 1][1]:  # >50% relative drop → stop
            break
        chosen.append(node_id)
        if len(chosen) >= cap:
            break
    return chosen


def _hubs(graph: nx.DiGraph, config: dict) -> set[str]:
    """Super-hub nodes — included but never traversed *through* (Graphify), so god-nodes don't explode."""
    r = config.get("retrieval", {})
    floor = r.get("hub_floor", 50)
    degrees = [d for _, d in graph.degree()]
    if not degrees:
        return set()
    cutoff = max(floor, _percentile(sorted(degrees), r.get("hub_percentile", 99)))
    return {n for n, d in graph.degree() if d >= cutoff}


def _percentile(sorted_vals: list[int], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, int(round((p / 100) * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def _traverse(graph: nx.DiGraph, seeds: list[str], config: dict) -> dict[str, int]:
    """Bounded, hub-aware BFS over the *undirected* edge set; returns ``{node_id: hops}``."""
    r = config.get("retrieval", {})
    max_hops, budget = r.get("max_hops", 2), r.get("node_budget", 60)
    hubs = _hubs(graph, config)

    hops = {s: 0 for s in seeds if s in graph}
    frontier = list(hops)
    depth = 0
    while frontier and depth < max_hops and len(hops) < budget:
        depth += 1
        nxt: list[str] = []
        for node in frontier:
            if node in hubs and depth > 1:
                continue  # include hubs, but don't expand through them
            neighbors = set(graph.successors(node)) | set(graph.predecessors(node))
            for neighbor in sorted(neighbors):
                if neighbor not in hops:
                    hops[neighbor] = depth
                    nxt.append(neighbor)
                    if len(hops) >= budget:
                        return hops
        frontier = nxt
    return hops


def _refs_in(graph: nx.DiGraph, node_id: str) -> int:
    return counters.refs_in(graph, node_id)


def _relevance(graph: nx.DiGraph, node_id: str, config: dict, now: float) -> float:
    """The relevance prior (graph-design §3), O(1) from the counters — no traversal:

    ``w1·log(1+refs_in) + w2·recency(last_seen) + w3·maturity − w4·[superseded_in>0]``.

    ``recency``/``maturity`` are the M9 runtime terms: a memory that's been surfaced lately or has
    earned ``settled`` ranks higher; a superseded one is docked. Nodes without runtime counters
    contribute ``0`` to those terms, so the prior reduces to the v0 form for un-aged structure.
    """
    w = config.get("relevance", {})
    attrs = graph.nodes[node_id]
    score = w.get("w1", 1.0) * math.log(1 + _refs_in(graph, node_id))
    half_life = config.get("relevance", {}).get("half_life_days", 14)
    score += w.get("w2", 1.0) * counters.recency(attrs.get("last_seen"), now, half_life)
    score += w.get("w3", 1.0) * counters.maturity_weight(attrs)
    if attrs.get("maturity") == "proposed":
        score -= w.get("w5", 3.0)  # a mined/review candidate: near-zero weight until an encounter confirms it
    if attrs.get("superseded_in", 0):
        score -= w.get("w4", 1.5)
    return score


def _normalize(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi - lo < 1e-12:
        return {k: 0.0 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def _rank(graph: nx.DiGraph, hops: dict[str, int], match: dict[str, float], config: dict,
          now: float | None = None) -> list[str]:
    r = config.get("retrieval", {}).get("ranking", {})
    alpha, beta, gamma = r.get("alpha", 0.5), r.get("beta", 0.3), r.get("gamma", 0.2)
    now = now if now is not None else time.time()

    match_n = _normalize({n: match.get(n, 0.0) for n in hops})
    prox_n = _normalize({n: 1.0 / (1 + hops[n]) for n in hops})
    rel_n = _normalize({n: _relevance(graph, n, config, now) for n in hops})

    final = {n: alpha * match_n[n] + beta * prox_n[n] + gamma * rel_n[n] for n in hops}
    return sorted(hops, key=lambda n: (-final[n], n))


# --------------------------------------------------------------------------------------------------
# Reconcile (R9c) + render
# --------------------------------------------------------------------------------------------------


@dataclass
class ContextResult:
    text: str
    token_estimate: int
    nodes_rendered: int
    nodes_total: int
    #: Ids of the nodes that made it into the render — the set an injection bumps usage on (M9).
    rendered: list[str] = field(default_factory=list)


def _drift_line(item) -> str:
    """A reconcile line for one drift item, worded for the relation that drifted (implements vs concerns)."""
    verb = "changed since anchored" if item.kind == "soft" else "no longer found"
    if item.relation == "concerns":
        tail = "re-verify this decision still holds, then re-`remember` or `supersede` it."
    else:
        tail = "re-verify or relink."
    return f"  ⚠ {item.task_id} → {item.locator} {verb} — {tail}"


def _verified_reconcile(graph: nx.DiGraph, drifted_edges: set[tuple[str, str]]) -> list[str]:
    """R9c: intents marked ``satisfied`` but lacking a live, undrifted implementing link."""
    lines: list[str] = []
    for node_id, attrs in graph.nodes(data=True):
        if attrs.get("family") != "intent" or attrs.get("status") != "satisfied":
            continue
        implementers = [t for t, _, a in graph.in_edges(node_id, data=True) if a.get("relation") == "tracks"]
        live = False
        for task in implementers:
            for _, sym, a in graph.out_edges(task, data=True):
                if a.get("relation") == "implements" and (task, sym) not in drifted_edges:
                    live = True
        if not live:
            lines.append(f"  ⚠ {node_id} is satisfied but not verified (no live implementing link, or it drifted)")
    return sorted(lines)


def _capture_gaps(graph: nx.DiGraph, scope: set[str] | None = None) -> list[str]:
    """Completed tasks that name no implementing symbol — the "work done, graph not told" signal.

    yigraf's read path is *push* (hooks inject context) but its write path is *pull* (``link`` /
    ``remember`` only run if the agent chooses to). An undisciplined agent finishing tasks without
    ``yigraf link`` silently starves the graph of the very edges drift and retrieval rely on. This
    makes that decay **legible** instead of silent: a ``done`` task with no ``implements`` edge is
    surfaced so the agent can close the link. Advisory only, like the R9c reconcile — never a hard gate
    (consistent with R8/R9c "surface, don't block"). ``scope`` (the retrieved hop-set) restricts it to
    a query's neighborhood; ``None`` reports every gap (the SessionStart orientation dashboard).
    """
    lines: list[str] = []
    for node_id, attrs in graph.nodes(data=True):
        if attrs.get("family") != "plan" or attrs.get("kind") != "task" or attrs.get("state") != "done":
            continue
        if scope is not None and node_id not in scope:
            continue
        linked = any(a.get("relation") == "implements" for _, _, a in graph.out_edges(node_id, data=True))
        if not linked:
            lines.append(f"  ⚠ {node_id} is done but names no implementing symbol — "
                         f"`yigraf link {node_id} sym:<path>#<name>`")
    return sorted(lines)


def _implemented_open_tasks(graph: nx.DiGraph, drifted_edges: set[tuple[str, str]],
                            scope: set[str] | None = None) -> list[str]:
    """Open tasks whose implementing symbols already exist and are current — the "done but not closed"
    signal, the mirror of :func:`_capture_gaps` (E#14, sibling of the mem:011 capture-gap).

    An agent that finishes a task and ``link``s its symbols but never checks the box leaves it seeding
    as active work on every SessionStart. Surfacing it lets the agent reconcile the plan. Host-agnostic
    and advisory — never a gate (R8/R9c "surface, don't block"), and mirroring open tasks into a host's
    native task list is left to a per-host adapter, never core (int:multi-host). We skip a task whose
    implements edge *drifted*: that's mid-change work, and drift already surfaces it — no double signal.
    """
    lines: list[str] = []
    for node_id, attrs in graph.nodes(data=True):
        if attrs.get("family") != "plan" or attrs.get("kind") != "task" or attrs.get("state") == "done":
            continue
        if scope is not None and node_id not in scope:
            continue
        impl = [d for _, d, a in graph.out_edges(node_id, data=True) if a.get("relation") == "implements"]
        if impl and not any((node_id, d) in drifted_edges for d in impl):
            lines.append(f"  ⚠ {node_id} is open but its implementing symbol(s) exist and are current "
                         f"({', '.join(sorted(impl))}) — if the work is done, check its box.")
    return sorted(lines)


def _pending_conflicts(graph: nx.DiGraph, scope: set[str] | None = None) -> list[str]:
    """Held-pending supersedes of human-attested nodes (int:memory-attestation) — surfaced, never silent.

    An agent's ``supersede`` of a human-attested decision is captured but NOT applied: the old node
    stays authoritative and the edge is marked ``pending``. This surfaces the conflict so a human can
    resolve it (attest the new node to apply, or discard) — the sticky trust floor made legible.
    """
    lines: list[str] = []
    for new_id, old_id, a in graph.edges(data=True):
        if a.get("relation") != "supersedes" or not a.get("pending"):
            continue
        if scope is not None and new_id not in scope and old_id not in scope:
            continue
        lines.append(f"  ⚠ {new_id} pending-supersedes human-attested {old_id} — {old_id} still holds; "
                     f"resolve by attesting {new_id} (human) to apply, or discard {new_id}.")
    return sorted(lines)


#: Structure kinds whose source is a meaningful slice (a whole file/module is not — skip those).
_SOURCE_KINDS = frozenset({"function", "method", "class", "type"})

#: Container kinds suppressed from the *render*: a bare ``file:``/``module:`` locator is noise that eats
#: the token budget and crowds out symbols + governing intent/drift (caveats M4/M6; the ranking fix that
#: gates ``source_for_seeds``). They still seed retrieval and bridge traversal — only the output drops them.
_RENDER_SKIP_KINDS = frozenset({"file", "module"})


def _source_block(graph: nx.DiGraph, node_id: str, root: Path, max_lines: int) -> str | None:
    """A header + verbatim, line-numbered source slice for a structure symbol (A3), or ``None``.

    The "sufficiency over token-thrift" render: the agent treats the returned source as already Read,
    so it doesn't re-open the file (the CodeGraph finding — insufficient output triggers a fallback
    Read that costs more end-to-end). Returns ``None`` for a non-sliceable node (file/module) or an
    unreadable file, so the caller falls back to the signature line — never a hard failure.
    """
    attrs = graph.nodes[node_id]
    if attrs.get("kind") not in _SOURCE_KINDS:
        return None
    src_file, rng = attrs.get("source_file"), attrs.get("source_range")
    if not src_file or not rng or root is None:
        return None
    try:
        lines = (Path(root) / src_file).read_text(encoding="utf-8", errors="surrogatepass").splitlines()
    except OSError:
        return None
    start_row, _, end_row, _ = rng  # 0-based rows from tree-sitter node_range (base.node_range)
    end_row = min(end_row, len(lines) - 1)
    if not 0 <= start_row <= end_row:
        return None
    body = lines[start_row:end_row + 1]
    truncated = max_lines and len(body) > max_lines
    if truncated:
        body = body[:max_lines]
    width = len(str(start_row + len(body)))
    numbered = [f"    {str(start_row + 1 + i).rjust(width)}\t{ln}" for i, ln in enumerate(body)]
    if truncated:
        numbered.append("    … (truncated — open the file for the rest)")
    return f"  {node_id}  ({src_file}:{start_row + 1})\n" + "\n".join(numbered)


def _render(graph: nx.DiGraph, ranked: list[str], query: str, drift_lines: list[str],
            reconcile_lines: list[str], budget_tokens: int, root: Path | None = None,
            config: dict | None = None, capture_lines: list[str] | None = None,
            relevance_note: str | None = None, scores: dict[str, float] | None = None,
            task_reconcile_lines: list[str] | None = None,
            conflict_lines: list[str] | None = None) -> ContextResult:
    capture_lines = capture_lines or []
    task_reconcile_lines = task_reconcile_lines or []
    conflict_lines = conflict_lines or []
    char_budget = budget_tokens * 3  # Graphify's ≈3:1 char:token estimate (retrieval-design §9)
    rcfg = (config or {}).get("retrieval", {})
    # A3: top-ranked symbols render as verbatim source when the knob is on AND we know the repo root.
    source_mode = rcfg.get("render", "signature_only") == "source_for_seeds" and root is not None
    max_src, max_src_lines = rcfg.get("source_max_symbols", 3), rcfg.get("source_max_lines", 40)
    reserved = "\n".join(drift_lines + reconcile_lines + capture_lines + task_reconcile_lines
                         + conflict_lines)
    out = [f'Context for "{query}":', ""]
    if relevance_note:  # C#8: a one-line honesty banner when nothing matched the query strongly
        out.extend([relevance_note, ""])
    used = len(reserved) + len(relevance_note or "")
    rendered = 0
    src_emitted = 0

    # Drop file:/module: containers before rendering — they only eat budget and bury intent/drift.
    renderable = [n for n in ranked if graph.nodes[n].get("kind") not in _RENDER_SKIP_KINDS]
    by_family: dict[str, list[str]] = {fam: [] for fam in _FAMILY_ORDER}
    rendered_ids: list[str] = []
    for node_id in renderable:
        fam = graph.nodes[node_id].get("family", "structure")
        line = None
        if source_mode and fam == "structure" and src_emitted < max_src:
            line = _source_block(graph, node_id, root, max_src_lines)
        used_source = line is not None
        if line is None:
            line = _node_line(graph, node_id)
        if scores is not None and node_id in scores and not used_source:  # C#8: --scores per-node cosine
            line += f"  [sim {scores[node_id]:.2f}]"
        if used + len(line) > char_budget:
            break
        by_family.setdefault(fam, []).append(line)
        rendered_ids.append(node_id)
        used += len(line) + 1
        rendered += 1
        if used_source:
            src_emitted += 1

    for fam in _FAMILY_ORDER:
        if by_family.get(fam):
            out.append(f"{_FAMILY_HEADING[fam]}:")
            out.extend(by_family[fam])
            out.append("")

    if conflict_lines:
        out.append("⚠ Conflict (pending — needs human):")
        out.extend(conflict_lines)
        out.append("")
    if drift_lines:
        out.append("⚠ Drift:")
        out.extend(drift_lines)
        out.append("")
    if reconcile_lines:
        out.append("⚠ Reconcile (R9c):")
        out.extend(reconcile_lines)
        out.append("")
    if capture_lines:
        out.append("⚠ Capture gaps:")
        out.extend(capture_lines)
        out.append("")
    if task_reconcile_lines:
        out.append("⚠ Task reconcile:")
        out.extend(task_reconcile_lines)
        out.append("")

    elided = len(renderable) - rendered
    if elided > 0:
        out.append(f"… {elided} more node(s) elided — narrow with `--family <f>` or a more specific query.")

    text = "\n".join(out).rstrip() + "\n"
    return ContextResult(text=text, token_estimate=len(text) // 3, nodes_rendered=rendered,
                         nodes_total=len(renderable), rendered=rendered_ids)


def _node_line(graph: nx.DiGraph, node_id: str) -> str:
    attrs = graph.nodes[node_id]
    fam, kind = attrs.get("family"), attrs.get("kind")
    if fam == "intent":
        tag = attrs.get("status", "?")
        if attrs.get("attestation") == "human":  # a human-endorsed spec — the trust floor, shown inline
            tag += "·human"
        return f"  {node_id} [{tag}]: {attrs.get('statement') or attrs.get('label', '')}"
    if fam == "plan" and kind == "task":
        box = "☑" if attrs.get("state") == "done" else "☐"
        suffix = _task_links(graph, node_id)
        return f"  {box} {node_id}: {attrs.get('label', '')}{suffix}"
    if fam == "plan":
        return f"  {node_id}: {attrs.get('label', '')}"
    if fam == "memory":
        return _memory_line(graph, node_id, attrs)
    sig = attrs.get("signature")
    return f"  {node_id}" + (f"  {sig}" if sig else "")


def _memory_line(graph: nx.DiGraph, node_id: str, attrs: dict) -> str:
    """A compact decision line: ``mem:001 [decision·inferred]: <statement> — why: <why> (serves …)``.

    The three certainty axes ride the tag so the agent sees a belief's status inline: grounding
    (``·inferred`` re-verify cue vs ``·empirical``, C#6), maturity (``·proposed`` = an unconfirmed
    mined/review candidate, ``·settled`` once it survived enough review-encounters, mem:033 —
    ``working`` is the unshown default), and attestation (``·human`` = human-endorsed trust floor,
    ``agent`` is the unshown default). ``·superseded`` last.
    """
    tag = attrs.get("kind", "memory")
    grounding = attrs.get("grounding")
    if grounding:
        tag += f"·{grounding}"
    if attrs.get("maturity") == "proposed":
        tag += "·proposed"
    elif attrs.get("maturity") == "settled":
        tag += "·settled"
    if attrs.get("attestation") == "human":
        tag += "·human"
    if attrs.get("superseded_in", 0):
        tag += "·superseded"
    line = f"  {node_id} [{tag}]: {attrs.get('statement') or attrs.get('label', '')}"
    if attrs.get("why"):
        line += f" — why: {attrs['why']}"
    if attrs.get("alternatives"):
        line += f" (rejected: {attrs['alternatives']})"
    links = _memory_links(graph, node_id)
    return line + links


def _memory_links(graph: nx.DiGraph, mem_id: str) -> str:
    serves = [d for _, d, a in graph.out_edges(mem_id, data=True) if a.get("relation") == "serves"]
    concerns = [d for _, d, a in graph.out_edges(mem_id, data=True) if a.get("relation") == "concerns"]
    supersedes = [d for _, d, a in graph.out_edges(mem_id, data=True) if a.get("relation") == "supersedes"]
    parts = []
    if serves:
        parts.append("serves " + ", ".join(sorted(serves)))
    if concerns:
        parts.append("concerns " + ", ".join(sorted(concerns)))
    if supersedes:
        parts.append("supersedes " + ", ".join(sorted(supersedes)))
    return f"  ({'; '.join(parts)})" if parts else ""


def _task_links(graph: nx.DiGraph, task_id: str) -> str:
    tracks = [d for _, d, a in graph.out_edges(task_id, data=True) if a.get("relation") == "tracks"]
    impl = [d for _, d, a in graph.out_edges(task_id, data=True) if a.get("relation") == "implements"]
    parts = []
    if tracks:
        parts.append("tracks " + ", ".join(sorted(tracks)))
    if impl:
        parts.append("implements " + ", ".join(sorted(impl)))
    return f"  ({'; '.join(parts)})" if parts else ""


# --------------------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------------------


def _file_structure_nodes(graph: nx.DiGraph, pid: str) -> list[str]:
    """The file/module/symbol nodes that belong to a casefolded relpath (the action-driven locus)."""
    ids = [nid for nid in (f"file:{pid}", f"module:{pid}") if nid in graph]
    prefix = f"sym:{pid}#"
    ids += sorted(n for n in graph.nodes if n.startswith(prefix))
    return ids


def context_for_locus(graph: nx.DiGraph, file_relpath: str, config: dict,
                      budget_tokens: int | None = None, root: Path | None = None) -> ContextResult | None:
    """Action-driven retrieval (retrieval-design §0): seed from a touched file, no NL query.

    Returns ``None`` — **silent** — unless the locus is actually governed (an ``implements``/
    ``tracks``/``concerns`` edge points at one of its symbols) or has drift, so the hook never nags on
    routine edits. Ranks on proximity + relevance (``match ≈ 0``) and renders in the tight hook budget.
    """
    from pathlib import PurePosixPath

    pid = PurePosixPath(file_relpath).as_posix().casefold()
    seeds = _file_structure_nodes(graph, pid)
    if not seeds:
        return None

    budget = budget_tokens or config.get("retrieval", {}).get("hook_token_budget", 800)
    hops = _traverse(graph, seeds, config)
    seedset = set(seeds)

    governing = any(
        a.get("relation") in ("implements", "tracks", "concerns")
        for s in seeds for _, _, a in graph.in_edges(s, data=True)
    )

    drift_lines: list[str] = []
    drifted_edges: set[tuple[str, str]] = set()
    has_drift = False
    for item in compute_drift(graph):
        if item.kind == "renamed":
            continue
        drifted_edges.add((item.task_id, item.locator))
        if item.task_id in hops or item.locator in seedset or item.locator in hops:
            has_drift = True
            drift_lines.append(_drift_line(item))

    if not governing and not has_drift:
        return None  # silent: no governing intent/task and no drift → nothing worth interrupting for

    ranked = _rank(graph, hops, {}, config)  # action-driven: no NL match
    reconcile = _verified_reconcile(graph, drifted_edges)
    return _render(graph, ranked, f"editing {file_relpath}", sorted(drift_lines), reconcile, budget,
                   root=root, config=config)


def _plan_has_open_work(graph: nx.DiGraph, plan_id: str) -> bool:
    """True when a plan still owns at least one un-checked (``todo``) task — the *derived* "active" test.

    A plan whose tasks are all ``done`` is finished work. Re-injecting it as "the active plan" on every
    ``/clear`` would spend the agent's context budget re-surfacing history it has already shipped — a
    design-law #4 violation ("silence is a feature"). Completion is derived from the checkboxes (files
    are truth, R6): checking the last box retires the plan from the SessionStart seed set with no manual
    move into ``completed/`` required. A plan with no tasks yet is likewise not "active work".
    """
    return any(
        graph.nodes[t].get("state") != "done"
        for _, t, e in graph.out_edges(plan_id, data=True)
        if e.get("relation") == "contains"
    )


def session_context(graph: nx.DiGraph, config: dict, budget_tokens: int | None = None,
                    root: Path | None = None) -> ContextResult | None:
    """SessionStart re-injection (R8): the active plan + governing intents + any drift.

    Seeds from every intent and **active** plan node, traverses to the implementing code, and renders
    so a flow interrupted by ``/clear`` resumes instead of restarting. ``None`` (silent) if there are
    no intents or active plans yet. "Active" is a plan not in the ``completed/`` phase **and** still
    holding open work (:func:`_plan_has_open_work`); a plan whose boxes are all checked drops out of the
    seed set so a finished milestone stops costing the agent context on every reset. Its tasks are not
    seeded directly — an active plan reaches them over its ``contains`` edges during traversal.
    """
    budget = budget_tokens or config.get("retrieval", {}).get("query_token_budget", 4000)
    seeds = sorted(
        n for n, a in graph.nodes(data=True)
        if a.get("family") == "intent"
        or (a.get("family") == "plan" and a.get("kind") == "plan"
            and a.get("phase") != "completed" and _plan_has_open_work(graph, n))
    )
    if not seeds:
        return None

    hops = _traverse(graph, seeds, config)
    ranked = _rank(graph, hops, {}, config)
    # Orient on what's *left*, not a ledger of shipped work: drop done tasks from the render so a
    # part-done plan shows only its open steps, and a done task pulled in via its (still-governing)
    # intent's `tracks` edge doesn't re-cost context (design law #4). Drift/capture-gap lines are
    # computed below over the full graph, so a done task that drifted or is unlinked still surfaces.
    ranked = [n for n in ranked
              if not (graph.nodes[n].get("kind") == "task" and graph.nodes[n].get("state") == "done")]

    drift_lines: list[str] = []
    drifted_edges: set[tuple[str, str]] = set()
    in_scope = set(hops)
    for item in compute_drift(graph):
        if item.kind == "renamed":
            continue
        drifted_edges.add((item.task_id, item.locator))
        if item.task_id in in_scope or item.locator in in_scope:
            drift_lines.append(_drift_line(item))

    reconcile = _verified_reconcile(graph, drifted_edges)
    capture = _capture_gaps(graph)  # global: SessionStart is the orientation dashboard for graph health
    task_reconcile = _implemented_open_tasks(graph, drifted_edges)
    conflicts = _pending_conflicts(graph)
    return _render(graph, ranked, "active plan & governing intents", sorted(drift_lines), reconcile,
                   budget, root=root, config=config, capture_lines=capture,
                   task_reconcile_lines=task_reconcile, conflict_lines=conflicts)


def _merge_seeds(lex_match: dict[str, float], sem_match: dict[str, float], config: dict) -> list[str]:
    """Union of the lexical and semantic seed sets (retrieval-design §2: union-of-top-k, not a mixed
    ranking — the two scorers are on different scales, so we cut each independently then merge)."""
    seeds = list(_seeds(lex_match, config))
    for s in _seeds(sem_match, config):
        if s not in seeds:
            seeds.append(s)
    return seeds


def _combine_match(lex_match: dict[str, float], sem_match: dict[str, float],
                   hops: dict[str, int]) -> dict[str, float]:
    """The ``match`` component for ranking: each seeder's scores normalized independently, then max'd.

    Normalizing per source before combining keeps a raw IDF score (~tens) from dominating a cosine
    (~0–1); ``_rank`` re-normalizes the result, so the absolute scale doesn't matter, only the merge.
    """
    lex_n = _normalize({n: lex_match[n] for n in hops if lex_match.get(n, 0.0) > 0})
    sem_n = _normalize({n: max(0.0, sem_match[n]) for n in hops if sem_match.get(n, 0.0) > 0})
    return {n: max(lex_n.get(n, 0.0), sem_n.get(n, 0.0)) for n in hops}


def _relevance_note(sem_match: dict[str, float], query: str, config: dict) -> str | None:
    """C#8 legibility banner: when a semantic backend ran but *nothing* cleared the relevance floor,
    say so — the returned slice is lexical/proximity-based, not a strong topical hit, so the agent
    treats it as a weak match instead of authoritative. ``None`` (silent) with no backend (can't judge
    confidence ⇒ don't cry wolf) or when something did match — design law #4.
    """
    if not sem_match:
        return None
    floor = config.get("embeddings", {}).get("relevance_floor", 0.4)
    best = max(sem_match.values())
    if best >= floor:
        return None
    return (f'  ⚠ low confidence — no memory/intent node strongly matches "{query}" '
            f"(best {best:.2f} < {floor}); showing lexical/proximity results.")


def context(graph: nx.DiGraph, query: str, config: dict, family: str | None = None,
            budget_tokens: int | None = None, semantic_match: dict[str, float] | None = None,
            root: Path | None = None, grounding: str | None = None,
            show_scores: bool = False) -> ContextResult:
    """Run the full query pipeline over an already-built ``graph`` and render within budget.

    ``semantic_match`` (``{node_id: cosine}`` from :mod:`yigraf.embeddings`, scoped to memory+intent)
    is the M8 semantic seeder, fused with the lexical/IDF seeder. ``None``/empty ⇒ pure lexical (= v0).
    ``grounding`` filters memory nodes to one epistemic tier (C#6); ``show_scores`` appends the per-node
    cosine (C#8) — both opt-in so the default render stays token-thrifty.
    """
    budget = budget_tokens or config.get("retrieval", {}).get("query_token_budget", 4000)
    sem_match = semantic_match or {}

    corpus = _build_corpus(graph)
    lex_match = _match_scores(corpus, terms(query))
    seeds = _merge_seeds(lex_match, sem_match, config)
    hops = _traverse(graph, seeds, config)

    if family:
        hops = {n: h for n, h in hops.items() if graph.nodes[n].get("family") == family}
    if grounding:  # C#6: restrict memory nodes to one grounding tier (leaves other families intact)
        hops = {n: h for n, h in hops.items()
                if graph.nodes[n].get("family") != "memory"
                or graph.nodes[n].get("grounding") == grounding}
    match = _combine_match(lex_match, sem_match, hops)
    ranked = _rank(graph, hops, match, config)

    drift_items = compute_drift(graph)
    in_scope = set(hops)
    drift_lines: list[str] = []
    drifted_edges: set[tuple[str, str]] = set()
    for item in drift_items:
        if item.kind == "renamed":
            continue
        drifted_edges.add((item.task_id, item.locator))
        if item.task_id in in_scope or item.locator in in_scope:
            drift_lines.append(_drift_line(item))

    reconcile_lines = _verified_reconcile(graph, drifted_edges)
    capture_lines = _capture_gaps(graph, scope=in_scope)  # scoped to the query's neighborhood, like drift
    task_reconcile = _implemented_open_tasks(graph, drifted_edges, scope=in_scope)
    conflicts = _pending_conflicts(graph, scope=in_scope)
    scores = {n: sem_match[n] for n in hops if n in sem_match} if show_scores else None
    return _render(graph, ranked, query, sorted(drift_lines), reconcile_lines, budget,
                   root=root, config=config, capture_lines=capture_lines,
                   relevance_note=_relevance_note(sem_match, query, config), scores=scores,
                   task_reconcile_lines=task_reconcile, conflict_lines=conflicts)
