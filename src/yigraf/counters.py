"""Counters, maturity, and GC — v0 keeps ``graph.json`` **fully recomputable** (DESIGN R1/R2/R3).

The relevance/GC engine without any *accumulated, committed* state:

- **maturity** (``working``/``settled``) is **git-derived** (R2): a memory is ``settled`` once its
  artifact has lived ``≥ K`` commits on the branch un-superseded — recomputed at build time from
  ``git log`` + supersede edges, so it's deterministic, branch-cadence-independent, and identical on
  every clone/CI run. No per-session ``survival`` counter is stored or merged.
- **telemetry** (``usage``/``last_seen``) is a **gitignored sidecar** (R1) — ``yigraf/.local/
  telemetry.json``, machine-local and best-effort, a soft recency/popularity nudge in ranking only.
  It is *never* written to the committed ``graph.json``, so a query never dirties git.
- **GC** (R3) **archives, never deletes, and never gates on ``usage``**: superseded churn
  (``superseded_in>0 ∧ refs_in=0``) is moved to an ``archive/`` folder; a still-referenced
  predecessor is left in place.

Because ``graph.json`` holds only recomputable state, branches reconcile by *rebuilding*; the
``merge_node_link`` union driver just avoids spurious line-level conflicts in the meantime.

> The *shared, committed, merge-reconciled* counter model (accumulated ``survival``/``usage`` in
> ``graph.json`` with a counter-reconciling merge driver) is **v1 / Enterprise** future work — it
> belongs to the cloud service where teams share artifacts and specs through an API
> (``docs/DESIGN.md`` "Counter models", ``docs/graph-design.md`` §3). v0 is deliberately local.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import networkx as nx

from yigraf.memory import DEFAULT_MATURITY, MEMORY_FAMILY, landing_maturity

#: Families that carry the telemetry nudge — the durable "why"/spec nodes whose recurrence across
#: sessions is what recency/popularity should reward (structure is ranked by refs_in/proximity).
COUNTED_FAMILIES = frozenset({MEMORY_FAMILY, "intent"})

#: Incoming edges that count as a node being "referenced" (importance) — shared with retrieval.
SEMANTIC_RELATIONS = frozenset({"implements", "tracks", "serves", "concerns", "references"})


# --------------------------------------------------------------------------------------------------
# git-derived maturity (R2) — recomputed each build, never stored as an accumulating counter
# --------------------------------------------------------------------------------------------------


def _git(root: Path, *args: str) -> str | None:
    """Run a read-only git command under ``root``; ``None`` if git is unavailable or errors (fail-open)."""
    try:
        out = subprocess.run(["git", "-C", str(root), *args],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def _head_sha(root: Path) -> str | None:
    """The current ``HEAD`` commit (cache key for survival), or ``None`` without git/commits."""
    out = _git(root, "rev-parse", "HEAD")
    return out.strip() if out and out.strip() else None


def _intro_commits(root: Path, paths: list[str]) -> dict[str, str]:
    """The *introducing* (oldest add) commit for each path, in one history traversal.

    One ``git log --diff-filter=A --name-status`` over all paths replaces the per-path ``log`` of the
    old fan-out. ``git log`` is newest-first, so re-assigning per add-event leaves the oldest add (the
    true introduction, mirroring the original ``splitlines()[-1]``) as the final value.
    """
    out = _git(root, "log", "--diff-filter=A", "--name-status", "--format=%x00%H", "--", *paths)
    if not out:
        return {}
    want = set(paths)
    intro: dict[str, str] = {}
    current: str | None = None
    for line in out.split("\n"):
        if line.startswith("\x00"):
            current = line[1:].strip()
        elif line.startswith("A\t") and current:
            path = line[2:]
            if path in want:
                intro[path] = current
    return intro


def _survival_map(root: Path, repo_relpaths: list[str]) -> dict[str, int]:
    """Survival (the R2 maturity clock) for many paths in a flat *two* git calls, regardless of count.

    One ``git log`` gives the HEAD-rooted commit order (index ``0`` = tip); one batched
    :func:`_intro_commits` gives each path's introducing commit. Survival is that commit's distance
    from ``HEAD``. ``0`` when there's no git, no such file, or it was added in the tip commit. On a
    branchy history the topo-order distance under-counts merged side branches, so a node matures no
    *faster* than the strict ``intro..HEAD`` count — conservative, and exact on linear history.
    """
    paths = sorted(set(repo_relpaths))
    if not paths:
        return {}
    order = _git(root, "log", "--topo-order", "--format=%H")
    if not order or not order.strip():
        return {p: 0 for p in paths}
    position = {h: i for i, h in enumerate(order.split())}
    intro = _intro_commits(root, paths)
    return {p: position.get(intro.get(p, ""), 0) for p in paths}


def survival_of(root: Path, repo_relpath: str) -> int:
    """Commits the branch has accrued since ``repo_relpath`` was introduced (single-path R2 clock).

    A thin wrapper over :func:`_survival_map`; builds batch every memory path through that helper in a
    flat number of git calls (see :func:`apply_maturity`). ``0`` when there's no git, no such file, or
    it was added in the tip commit — so a freshly-captured memory starts at ``0`` and matures as the
    branch moves on past it.
    """
    return _survival_map(root, [repo_relpath]).get(repo_relpath, 0)


def _survival_for(root: Path, repo_relpaths: list[str], cache) -> dict[str, int]:
    """Survival for ``repo_relpaths``, served from the HEAD-keyed structure cache when it can be.

    An edit never moves ``HEAD``, so on the hot ``PostToolUse`` path this is a single ``rev-parse``
    and zero history walks — survival can only change when a commit lands. Paths absent from a cached
    map are necessarily uncommitted-since-that-build, so they score ``0`` (their git survival too).
    """
    head = _head_sha(root) if cache is not None else None
    if head is not None:
        cached = cache.maturity_survival(head)
        if cached is not None:
            return {p: cached.get(p, 0) for p in repo_relpaths}
    survival = _survival_map(root, repo_relpaths)
    if head is not None:
        cache.set_maturity_survival(head, survival)
    return survival


def apply_maturity(graph: nx.DiGraph, root: Path, config: dict, cache=None) -> None:
    """Stamp git-derived ``survival`` + the provenance-derived *landed* tier on every memory node.

    Promotion is no longer git-derived (mem:033 — commit-age treats un-touched code as validated, the
    "silence is not evidence" fallacy). ``settled`` is a **read-time verdict** from survived
    review-encounters in the telemetry sidecar (:func:`apply_maturity_verdict`), so *promotion* never
    touches the committed ``graph.json``. This build pass keeps only recomputable state: ``survival``
    (git — an optional durability floor + informational) and the **landed tier** — ``proposed`` for a
    mined/review candidate, ``working`` otherwise — derived from the committed ``provenance`` so it is
    itself recomputable (:func:`yigraf.memory.landing_maturity`, task #1).

    Survival is derived in a flat number of git calls — batched across all memory paths and, given a
    ``cache`` (the build path), memoized by ``HEAD`` so an edit-triggered rebuild that hasn't committed
    re-uses the prior survival instead of re-walking history (caveats.md M9 / DESIGN R2).
    """
    paths = sorted({
        f"yigraf/{attrs['source_file']}"
        for _, attrs in graph.nodes(data=True)
        if attrs.get("family") == MEMORY_FAMILY and attrs.get("source_file")
    })
    survival = _survival_for(root, paths, cache)
    for _, attrs in graph.nodes(data=True):
        if attrs.get("family") != MEMORY_FAMILY:
            continue
        source = attrs.get("source_file")
        attrs["survival"] = survival.get(f"yigraf/{source}", 0) if source else 0
        # The landed base (promotion above it is the read-time verdict; build stays recomputable).
        attrs["maturity"] = landing_maturity(attrs.get("provenance"))


# --------------------------------------------------------------------------------------------------
# Telemetry sidecar (R1) — machine-local usage/last_seen, never committed
# --------------------------------------------------------------------------------------------------


def telemetry_path(root: Path) -> Path:
    return Path(root) / "yigraf" / ".local" / "telemetry.json"


def load_telemetry(root: Path) -> dict[str, dict]:
    """Read the gitignored ``{node_id: {usage, last_seen}}`` sidecar (``{}`` if absent/corrupt)."""
    path = telemetry_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def apply_telemetry(graph: nx.DiGraph, telemetry: dict[str, dict]) -> None:
    """Stamp sidecar ``usage``/``last_seen`` onto the in-memory graph for ranking (read paths only).

    Never called on the ``build`` write path, so the telemetry never reaches the committed
    ``graph.json`` — it's a query-time overlay that keeps ``graph.json`` recomputable.
    """
    for node_id, entry in telemetry.items():
        if node_id not in graph:
            continue
        if "usage" in entry:
            graph.nodes[node_id]["usage"] = entry["usage"]
        if "last_seen" in entry:
            graph.nodes[node_id]["last_seen"] = entry["last_seen"]
        if "upholds" in entry:  # accumulated survived-encounter weight → the read-time maturity verdict
            graph.nodes[node_id]["upholds"] = entry["upholds"]


def record_injection(root: Path, graph: nx.DiGraph, node_ids: list[str],
                     now: float | None = None) -> list[str]:
    """Record that ``node_ids`` were surfaced: bump ``usage``/``last_seen`` in the sidecar (R1).

    Scoped to the counted families (memory+intent). Machine-local and best-effort — a surfacing is a
    soft ranking signal, not committed state. Returns the ids actually bumped.
    """
    stamp = int(now if now is not None else time.time())
    telemetry = load_telemetry(root)
    bumped: list[str] = []
    for node_id in node_ids:
        attrs = graph.nodes.get(node_id) if node_id in graph else None
        if attrs is None or attrs.get("family") not in COUNTED_FAMILIES:
            continue
        entry = telemetry.setdefault(node_id, {})
        entry["usage"] = int(entry.get("usage", 0)) + 1
        entry["last_seen"] = stamp
        bumped.append(node_id)
    if bumped:
        path = telemetry_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(telemetry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return bumped


def record_uphold(root: Path, graph: nx.DiGraph, node_ids: list[str], weight: float) -> list[str]:
    """Record a *survived review-encounter*: accumulate ``weight`` into each node's ``upholds`` (mem:033).

    An uphold is a POSITIVE maturity event — a review/edit of a locus that produced no violation or
    supersede. ``reaffirm`` books a strong uphold (an explicit re-verification); the edit hook books a
    weak one (silent survival — the code was touched and the governing decision did not drift). It's a
    machine-local sidecar accumulator, never committed (graph.json stays recomputable), and best-effort.
    Scoped to memory nodes. Returns the ids actually credited.
    """
    if weight <= 0:
        return []
    telemetry = load_telemetry(root)
    credited: list[str] = []
    for node_id in node_ids:
        attrs = graph.nodes.get(node_id) if node_id in graph else None
        if attrs is None or attrs.get("family") != MEMORY_FAMILY:
            continue
        entry = telemetry.setdefault(node_id, {})
        entry["upholds"] = round(float(entry.get("upholds", 0.0)) + weight, 4)
        credited.append(node_id)
    if credited:
        path = telemetry_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(telemetry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return credited


def recency(last_seen: int | None, now: float, half_life_days: float) -> float:
    """Exp-decayed recency in ``[0, 1]``: ``1`` just-surfaced, halving every ``half_life_days``."""
    if not last_seen:
        return 0.0
    age_days = max(0.0, (now - last_seen)) / 86400.0
    return 0.5 ** (age_days / max(half_life_days, 1e-9))


def apply_maturity_verdict(graph: nx.DiGraph, config: dict) -> None:
    """The read-time maturity verdict (mem:033, task #1): promote a node above its *landed* tier from
    survived-encounter upholds.

    Reads the landed tier stamped by :func:`apply_maturity` (``proposed`` for a mined/review candidate,
    else ``working``) and the sidecar-overlaid ``upholds`` stamped by :func:`apply_telemetry`, so it must
    run on read paths *after* that overlay — never at build time (that would leak machine-local state into
    the committed graph). Idempotent; safe to call twice.

    - A ``proposed`` candidate stays ``proposed`` until ``upholds ≥ maturity_confirm`` — its first real
      encounter *confirms* it up to ``working`` (int:knowledge-mining: near-zero weight until confirmed).
    - ``settled`` iff ``upholds ≥ maturity_k`` (behaviorally validated) AND not superseded (deterministic
      demotion via the committed edge) AND ``survival ≥ maturity_survival_floor`` (optional git gate,
      default ``0`` ⇒ off).
    - otherwise ``working``.
    """
    k = float(config.get("maturity_k", 3))
    confirm = float(config.get("maturity_confirm", 1.0))
    floor = int(config.get("maturity_survival_floor", 0))
    for _, attrs in graph.nodes(data=True):
        if attrs.get("family") != MEMORY_FAMILY:
            continue
        upholds = float(attrs.get("upholds", 0.0))
        if attrs.get("maturity") == "proposed" and upholds < confirm:
            continue  # an un-confirmed candidate — leave it at the proposed landing tier
        settled = (upholds >= k
                   and not attrs.get("superseded_in", 0)
                   and int(attrs.get("survival", 0)) >= floor)
        attrs["maturity"] = "settled" if settled else "working"


def maturity_weight(attrs: dict) -> float:
    """The maturity BONUS to relevance: ``+1`` for a settled memory, ``0`` otherwise.

    A ``proposed`` candidate is docked separately in the relevance prior (a near-zero-weight penalty,
    mirroring the superseded dock) — this function only carries the positive settled signal, so a
    ``working`` node and an un-earned candidate don't both read as a flat ``0`` here."""
    return 1.0 if attrs.get("maturity") == "settled" else 0.0


# --------------------------------------------------------------------------------------------------
# Garbage collection (R3) — archive churn, never delete, never gate on usage
# --------------------------------------------------------------------------------------------------


def refs_in(graph: nx.DiGraph, node_id: str) -> int:
    """Count incoming *semantic* edges — whether anything still points at this node."""
    return sum(1 for _, _, a in graph.in_edges(node_id, data=True)
               if a.get("relation") in SEMANTIC_RELATIONS)


def classify_gc(graph: nx.DiGraph, config: dict | None = None) -> dict[str, str]:
    """Map each collectable memory node to its GC *reason* (both reasons ⇒ archived, never deleted; R3).

    Two disjoint reasons, both moved to ``memory/archive/`` (out of the active graph, kept auditable):

    - ``superseded-churn``: ``superseded_in>0 ∧ refs_in=0`` — a mind-change nobody else points at. This
      is the **deterministic** archive (mem:008): keyed on committed supersede edges, never on telemetry,
      so it's identical on every clone. A superseded node still referenced is left as a rejected alt.
    - ``abandoned-proposed`` (task #7): a candidate that landed ``proposed`` (mined/review), was never
      confirmed by a real encounter, and has aged past ``proposed_ttl`` commits un-referenced. This one
      is **behavioral**: it reads the read-time maturity verdict (a confirmed candidate has already
      graduated to ``working`` and is skipped), so callers must overlay telemetry + run
      :func:`apply_maturity_verdict` first. It expires speculation by silence — which is safe *only*
      because the proposed tier is quarantine (near-zero weight, mem:050); it NEVER touches a genuine
      ``working``/``settled`` decision (silence is not evidence there — mem:033). Git-survival is the
      staleness clock (recomputable), so a no-git repo never expires a candidate (survival stays 0).
    """
    ttl = int((config or {}).get("proposed_ttl", 30))
    actions: dict[str, str] = {}
    for node_id, attrs in graph.nodes(data=True):
        if attrs.get("family") != MEMORY_FAMILY:
            continue
        if attrs.get("superseded_in", 0) and refs_in(graph, node_id) == 0:
            actions[node_id] = "superseded-churn"
        elif (attrs.get("maturity") == "proposed"
              and int(attrs.get("survival", 0)) >= ttl
              and refs_in(graph, node_id) == 0):
            actions[node_id] = "abandoned-proposed"
    return actions


# --------------------------------------------------------------------------------------------------
# Union-merge driver — graph.json is recomputable, so this just avoids spurious conflicts
# --------------------------------------------------------------------------------------------------


def merge_node_link(ours: dict, theirs: dict, edges_key: str = "links") -> dict:
    """Union-merge two ``graph.json`` node-link dicts (no counter reconciliation — that's v1).

    ``graph.json`` holds only recomputable state in v0, so the post-merge build re-projects it
    exactly; this driver exists only so a concurrent two-branch edit doesn't throw a line-level JSON
    conflict in the meantime. Nodes/edges are unioned; ``ours`` wins a content tie (the build heals it).
    """
    nodes = {n["id"]: n for n in theirs.get("nodes", [])}
    nodes.update({n["id"]: n for n in ours.get("nodes", [])})

    edges: dict[tuple, dict] = {}
    for edge in theirs.get(edges_key, []) + ours.get(edges_key, []):
        edges[(edge["source"], edge["target"], edge.get("relation", ""))] = edge

    out = dict(ours)
    out["nodes"] = [nodes[k] for k in sorted(nodes)]
    out[edges_key] = sorted(edges.values(),
                            key=lambda e: (e["source"], e["target"], e.get("relation", "")))
    return out
