"""The ``yigraf`` command-line interface.

M0 ships ``init`` only. Later milestones add the verbs the design names — ``intent`` / ``plan`` /
``link`` (M2), ``context`` (M4) — as sibling subcommands under this app.
"""
from __future__ import annotations

import datetime as _dt
import difflib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import NoReturn

import typer

from yigraf import (__version__, artifacts, counters, embeddings, graphdb, memory,
                    obligations, relations, resolution, retrieval, sectionfit, status, update)
from yigraf import show as show_mod  # aliased: the module and the `show` command share a name
from yigraf.astnorm import (ANCHOR_ALGO, DOC_SUFFIXES, locus_hash, parse_file_target,
                            parse_section_target, section_slug, section_slugs)
from yigraf.config import (DEFAULT_SESSION_PREAMBLE, PREAMBLE_COPY_CURRENT, TOKEN_ENV,
                          load_config, preamble_copy_class, refresh_preamble, replica_path)
from yigraf.drift import (compute_drift, is_reverifiable, is_stale_completion, is_surfaced,
                          stale_completions)
from yigraf.extract import build_graph, symbol_content_hash
from yigraf.graph import from_node_link, write_graph  # legacy graph.json union-merge driver only
from yigraf.languages import available_extractors, extension_map
from yigraf.hooks import (AMBIENT_HOSTS, HOST_FIDELITY, SUPPORTED_HOSTS, TIER_AMBIENT, TIER_EVENT,
                          _HOST_MARKERS, _write_agents_block, detect_hosts, install_ambient_rule,
                          install_antigravity, install_claude_hooks, install_codex_hooks,
                          install_post_commit_hook)
from yigraf.scaffold import WORKSPACE_DIRNAME, init_workspace

_TASK_ID = re.compile(r"^task:(.+)/(\d+)$")


def _guidance(message: str) -> NoReturn:
    """Decline a recoverable condition with agent-facing guidance, exiting 0 (never a hard error).

    An unresolved locator, a near-duplicate, or a name that already exists is *not* a tool failure: a
    non-zero exit trains an agent to stop calling the tool ("errors teach abandonment", the lesson
    imported from CodeGraph). So we print how to fix it and exit 0 — the agent reads the guidance and
    retries with a corrected argument. Genuine "stop" cases (no workspace, the CI ``drift`` gate) keep
    their non-zero exit.
    """
    typer.echo(message)
    raise typer.Exit(code=0)


#: What makes an argument path-shaped rather than slug-shaped: a separator, a bare ``.``/``..``, or a
#: ``~``. A slug names ONE artifact file, so none of these can ever resolve to one.
_PATH_SHAPED = re.compile(r"[/\\]|^\.+$|^~")


def _require_slug(value: str | None, kind: str, tail: str) -> None:
    """Refuse a path — or an empty string — where a slug belongs. The calling convention differs
    between neighbouring verbs, and both mistakes compose into a filename that names the wrong thing.

    ``yigraf drift .`` means *this repo*; ``yigraf tasks .`` meant *the plan named "."*, which answered
    ``No plan .. Known: …`` at exit 0 — a plausible "nothing outstanding" on the one surface an agent
    asks what is left, while ``yigraf status .`` refused loudly at exit 2 (feedback-v6 §8). Guessing the
    wrong convention must not look like an answer. On the *writing* verbs the same shape is worse than
    misleading: ``plan ../../x`` composed straight into ``workspace / "plans" / "active" / f"{slug}.md"``
    and landed outside the workspace. One wording for both, because it is one mistake.

    The **empty** slug is the same mistake one step further along, and it used to pass here twice over:
    ``not value`` short-circuited out, and ``_PATH_SHAPED`` does not match ``""`` either. ``yigraf plan
    ""`` — an unset ``$SLUG`` — then wrote the dotfile ``plans/active/.md`` and reported success, and a
    second one silently replaced it, title, tasks and stamped ``implements`` anchor alike (feedback-v7
    G#1). Refusing it here is the guard; ``plan``'s anti-clobber check is the seatbelt.

    ``None`` is not empty and must stay: ``tasks`` passes it to mean *every plan*, and refusing falsy
    values rather than the empty string breaks ``yigraf tasks`` with no argument.
    """
    if value is None:  # `tasks` with no argument — None means EVERY plan, not a bad name
        return
    if not value.strip():
        _guidance(f"An empty slug does not name {kind} — usually an unset shell variable. It composes "
                  f"to a bare `.md` dotfile that then answers to a name you never typed, so yigraf "
                  f"writes nothing. {tail}")
    if not _PATH_SHAPED.search(value):
        return
    _guidance(f"{value!r} is a path, not {kind} slug — a slug names one artifact file, so it never "
              f"contains a separator, and the repo root goes to `--repo`. {tail}")


def _section_suggestion(repo: Path | None, target: str) -> str:
    """A 'did you mean' tail for an unresolved ``file:<path>#<slug>`` locator, read off the file.

    The graph cannot answer this one: docs are deliberately not indexed, so the only section nodes in
    it are the ones some assertion already names (mem:a65f1ccad03b765e). The file itself is the index —
    which is also why this can list every *available* heading, the one thing that turns a missed guess
    into a single retry (design law #1).
    """
    relpath, slug = parse_section_target(target)
    if repo is None or slug is None:
        return ""
    slugs = section_slugs(repo, relpath)
    if not slugs:
        return f" {relpath} has no addressable headings (or is not there yet)."
    close = difflib.get_close_matches(slug, slugs, n=3, cutoff=0.6)
    if close:
        return " Did you mean: " + ", ".join(f"file:{relpath}#{c}" for c in close) + "?"
    shown = ", ".join(slugs[:8]) + (" …" if len(slugs) > 8 else "")
    return f" Headings in {relpath}: {shown}."


def _canonical_locus(repo: Path | None, target: str) -> str:
    """Canonicalize a typed ``file:<path>#<heading>`` onto the addressable slug, when that is what the
    caller plainly meant (feedback-v5 B).

    The slug rule is real and stays: a section's locator *is* its node id, so one spelling has to be
    canonical or a single heading splits into two identities. What changed is where that rule is
    enforced. It used to be enforced at the *user*, who had to know that ``## Turning Radius`` is
    addressed as ``#turning-radius`` — and the failure was a refusal indistinguishable from "sections
    are not indexed", because a heading typed with its own capitalisation and spaces resolves to
    nothing. Now it is enforced on the *input*: what the caller types is mapped onto the canonical
    spelling before it can become an id, so exactly one string is ever stored.

    Deliberately narrow, in both directions:

    * only when the typed fragment is **not** already addressable and its slugified form **is**. A slug
      that resolves is never touched, and a heading that exists in neither spelling falls through
      untouched to the normal guidance, which lists the file's real headings.
    * only ever ``section_slug`` — the same function that mints the slugs, so the mapping cannot
      disagree with the index it is matching against.

    This adds no ambiguity: two headings that slug identically are already refused by
    :func:`_guide_section_locus`, which is the check that owns that question, and it runs after this.
    """
    relpath, slug = parse_section_target(target)
    if repo is None or not slug:
        return target
    canonical = section_slug(slug)
    if canonical == slug:
        return target
    slugs = section_slugs(repo, relpath)
    if slug in slugs or canonical not in slugs:
        return target  # already addressable, or the correction wouldn't resolve either — say nothing
    return f"file:{relpath}#{canonical}"


def _covered_loci(target: str, carried: set[str]) -> set[str]:
    """Which of the loci a node ``carried`` the locus-form batch ``target`` covers.

    Exact match, plus one containment rule: a **whole-file** ``file:<path>`` covers every section
    anchor ``file:<path>#<slug>`` inside it (feedback-v5 D#4). Section anchors are the recommended cure
    for a prose document's false drift, so without this the cure and the batch-clear did not compose —
    ``reaffirm file:doc.md`` reported success on a document whose beliefs are all anchored to its
    sections and cleared none of them.

    Honest, not merely convenient: re-verifying a document is re-verifying the sections it is made of,
    and the re-stamp is a **no-op for every section that did not change** — that is what the section
    anchor bought. So the batch touches exactly the sections whose text moved, which is the same set
    the caller just read. A line range is deliberately NOT covered: it is a positional pin, and an edit
    anywhere above it moves what it points at without the file-level reader ever seeing the difference.
    Containment is one-way — naming a section never reaches the whole file, which would be a claim the
    caller did not make.
    """
    if not target.startswith("file:") or "#" in target or ":L" in target:
        return {c for c in carried if c == target}
    prefix = target + "#"
    return {c for c in carried if c == target or c.startswith(prefix)}


def _canonical_loci(repo: Path | None, targets: list[str] | None) -> list[str]:
    """:func:`_canonical_locus` over a repeatable option's values (``--concerns``, ``--evidence``, …)."""
    return [_canonical_locus(repo, t) for t in (targets or [])]


def _symbol_suggestion(graph, target: str, repo: Path | None = None) -> str:
    """A 'did you mean' tail for an unresolved locator, fuzzy-matched against the graph.

    ``repo`` is optional only because a ``sym:`` suggestion never needs it; a section locator does, and
    passing it is what lets one call site serve both locator families.
    """
    if parse_section_target(target)[1] is not None:
        return _section_suggestion(repo, target)
    candidates = [n for n in graph.nodes if str(n).startswith("sym:")]
    close = difflib.get_close_matches(target, candidates, n=3, cutoff=0.6)
    if close:
        return " Did you mean: " + ", ".join(close) + "?"
    name = target.split("#", 1)[-1]
    same_name = sorted(c for c in candidates if c.split("#", 1)[-1] == name)
    if same_name:
        return " A symbol named that exists at: " + ", ".join(same_name[:3]) + "."
    return f' Run `yigraf context "{name}"` to find its locator.'


def _locus_noun(target: str) -> tuple[str, str]:
    """``(what the locator names, what "it lands" means for it)`` — so a dangling-edge warning about a
    doc section neither calls it a symbol nor promises it governs "once the code lands".

    Small, but it is the difference between a message an agent can act on and one that sends it looking
    for a function in a markdown file (design law #1).
    """
    if parse_section_target(target)[1] is not None:
        return "section", "that section is written"
    if target.startswith("file:"):
        return "file", "that file lands"
    return "symbol", "the code lands"


def _refuse_bare_sym(graph, sym: str, flag: str) -> None:
    """Refuse a bare ``sym:<path>`` (no ``#name``) — never valid, so an error costs nothing (feedback-v3 #7).

    It can only ever land as a dangling edge that reports as PERMANENT hard drift no verb clears, and
    the capture "succeeding" with a scrolled-past warning is how the field filed it three times in one
    session. The candidates the old warning computed as advice are now the error's content.
    """
    in_file = sorted(n for n in graph.nodes if str(n).startswith(sym + "#"))
    if in_file:
        shown = ", ".join(in_file[:6]) + (" …" if len(in_file) > 6 else "")
        _guidance(f"{sym} names a file, not a symbol — {flag} takes sym:<path>#<name>. "
                  f"Symbols there: {shown}. For a claim about the whole file, use file:<path> "
                  f"(unindexed glue), a line range, or — in markdown — file:<path>#<section>.")
    _guidance(f"{sym} names a file, not a symbol — {flag} takes sym:<path>#<name>."
              + _symbol_suggestion(graph, sym))


def _anchor(repo: Path, config: dict, target: str, *, guide: bool = True) -> tuple[str | None, str | None]:
    """Resolve ``(anchor, algo)`` for a ``sym:``/``file:`` target, or ``(None, None)`` if it isn't in
    the source *yet* (a legitimate forward-reference — the caller decides whether that's fatal).

    Still hard-guides (exit 0) on the whole-file-on-indexed-code misuse: that's a design error, not a
    forward-reference — the anchor would collide with the extractor's own file node and never drift.
    A ``file:`` line-slice or an infra/glue file hashes bytes with ``FILE_ANCHOR_ALGO``; a markdown
    ``#<section>`` hashes that heading's normalized section under ``SECTION_ANCHOR_ALGO``; a ``sym:``
    keeps the astnorm anchor. The algo travels with the anchor so drift compares like against like.

    ``guide=False`` turns every hard guide off, for a locus this call is *re-resolving* rather than being
    handed. Those guides check a locator the caller **typed**; against a stored one they punish the wrong
    person. A supersede inherits the predecessor's loci, so someone else adding a second ``## Drift`` to a
    governed doc made ``#drift`` ambiguous and refused the supersede — losing a mind-change, with a
    message about heading titles, to a caller who touched no docs and cannot fix it without editing one.
    Unresolvable is the honest reading of a stored locus that no longer resolves: the capture lands, the
    edge dangles, and drift says so.
    """
    if target.startswith("file:"):
        relpath, start, _end = parse_file_target(target)
        slug = parse_section_target(target)[1]
        if not guide:
            return locus_hash(repo, target)  # re-resolving a stored locus: report, never refuse
        if slug is not None:
            _guide_section_locus(repo, config, relpath, slug)
        elif start is None and Path(relpath).suffix in extension_map(available_extractors(config)):
            _guidance(f"{relpath} is indexed as code, so a whole-file `file:` anchor would silently "
                      f"never drift. Anchor a symbol (sym:{relpath}#<name>) or a line range "
                      f"(file:{relpath}:L<a>-L<b>) instead. `file:` is for infra/glue with no symbols.")
        return locus_hash(repo, target)
    anchor = symbol_content_hash(repo, target, config)
    return (anchor, ANCHOR_ALGO) if anchor is not None else (None, None)


def _guide_section_locus(repo: Path, config: dict, relpath: str, slug: str) -> None:
    """Hard-guide (exit 0) the two ``file:<path>#<slug>`` errors that are design errors, not forward
    references: a path with no addressable headings, and a slug that names more than one.

    Everything else — a file that isn't written yet, a heading that isn't written yet — falls through
    to the normal dangling-concern path, because a decision legitimately governs a section about to be
    written (D#3), and :func:`_section_suggestion` lists the real headings in the warning.
    """
    if Path(relpath).suffix.casefold() not in DOC_SUFFIXES:
        if Path(relpath).suffix in extension_map(available_extractors(config)):
            _guidance(f"{relpath} is indexed as code, so `#{slug}` names a SYMBOL, not a heading — "
                      f"did you mean sym:{relpath}#{slug}?")
        _guidance(f"{relpath} is not markdown, so it has no addressable headings — "
                  f"file:<path>#<section> reads markdown headings ({', '.join(sorted(DOC_SUFFIXES))}). "
                  f"For a region of this file use file:{relpath}:L<a>-L<b>; for all of it, "
                  f"file:{relpath}.")
    slugs = section_slugs(repo, relpath)
    if slugs.count(slug) > 1:
        _guidance(f"#{slug} names {slugs.count(slug)} headings in {relpath}, so the locator cannot say "
                  f"which — anchoring it would pin the belief to whichever comes first and go quiet "
                  f"about the rest. Give one heading a distinct title (the slug is the title, "
                  f"case-folded, with each run of other characters as a single `-`), or pin the region "
                  f"positionally with file:{relpath}:L<a>-L<b>.")


def _anchor_or_guide(repo: Path, config: dict, target: str) -> tuple[str, str]:
    """Stamp the ``(anchor, algo)`` for a ``sym:``/``file:`` target; unresolved → guidance, exit 0.

    The hard-resolve used by ``link``: an implements edge must name code that exists (a task can't
    implement a symbol that isn't there yet). Memory ``concerns`` uses the soft :func:`_anchor` instead,
    because a decision legitimately governs code about to be written (D#3 — forward-refs never block).
    """
    anchor, algo = _anchor(repo, config, target)
    if anchor is not None:
        return anchor, algo
    if target.startswith("file:"):
        _guidance(f"Couldn't find the file for {target} — expected "
                  f"file:<path>[:L<a>-L<b>|#<section>] relative to the repo root. Check the path "
                  f"exists and is spelled relative to {repo}."
                  + _section_suggestion(repo, target))
    graph, _ = build_graph(repo, config)
    _guidance(f"Couldn't find {target} in the current source." + _symbol_suggestion(graph, target))


app = typer.Typer(
    help="yigraf — one connected graph over code, intent, plan, and memory.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"yigraf {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the yigraf version and exit.",
    ),
) -> None:
    """yigraf — a harness primitive for AI coding agents."""


@app.command()
def init(
    path: Path = typer.Argument(
        Path("."),
        help="Repo root to initialize (defaults to the current directory).",
    ),
) -> None:
    """Create the yigraf/ workspace in a repo (idempotent)."""
    result = init_workspace(path)
    if result.already_initialized:
        typer.echo(f"yigraf workspace already present at {result.workspace} — nothing to do.")
        raise typer.Exit()
    typer.echo(f"Initialized yigraf workspace at {result.workspace}")
    for rel in result.created:
        typer.echo(f"  + {rel}")
    if result.skipped:
        typer.echo(f"  ({len(result.skipped)} item(s) already existed, left untouched)")


@app.command()
def build(
    path: Path = typer.Argument(
        Path("."),
        help="Repo root to index (must contain a yigraf/ workspace from `yigraf init`).",
    ),
) -> None:
    """Extract the structure graph into the gitignored SQLite materialized view (yigraf/.local/graph.db)."""
    root = Path(path)
    workspace = root / WORKSPACE_DIRNAME
    if not workspace.is_dir():
        typer.echo(f"No yigraf workspace at {workspace} — run `yigraf init` first.", err=True)
        raise typer.Exit(code=1)

    config = load_config(workspace / "config.yaml")
    graph, stats = graphdb.rebuild(root, config)  # build + materialize the view (survival git-derived, R2)
    reindexed = embeddings.refresh_index(root, graph, config)  # scoped semantic index (M8; no-op if no backend)

    typer.echo(
        f"Indexed {stats.files} file(s): {stats.extracted} parsed, {stats.cached} cached."
    )
    typer.echo(f"  {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges.")
    if reindexed:
        typer.echo("  embedding index refreshed.")
    if int(config.get("maturity_survival_floor", 0)) > 0 and not counters.survival_floor_applies(graph):
        # Armed a gate the substrate can't measure: neither git nor a synced log can age these beliefs,
        # so the floor is being ignored rather than silently blocking every promotion (design law #5).
        typer.echo(
            "  ⚠ maturity_survival_floor is set, but neither survival clock can measure here — git "
            "tracks none of your memory artifacts and no shared log is synced. The floor is being "
            "IGNORED (it would otherwise stop anything from ever settling). Commit yigraf/memory/, "
            "connect a shared log, or set the floor back to 0.")
    if unwritable := graph.graph.get("view_unwritable"):
        # The index built fine and every count above is real — only the cache didn't stick. Last, so the
        # exit-0 guidance never swallows the report of the work that DID happen (design law #1).
        _guidance(f"  ⚠ {unwritable}")


def _require_workspace(root: Path) -> Path:
    workspace = root / WORKSPACE_DIRNAME
    if not workspace.is_dir():
        typer.echo(f"No yigraf workspace at {workspace} — run `yigraf init` first.", err=True)
        raise typer.Exit(code=1)
    return workspace


def _rebuild(root: Path):
    """Re-project the graph so the materialized view reflects a just-written artifact, and refresh the index.

    ``refresh_index`` re-embeds only memory/intent nodes whose text changed (a no-op — no model load —
    when nothing did), so a captured decision/intent becomes semantically searchable immediately.
    Returns the rebuilt graph, so a caller that needs to read what just landed doesn't build it twice.

    An unwritable view warns and continues — it never aborts the capture. By the time we get here the
    artifact is already on disk, and the markdown IS the truth (design law #6): failing now would report
    a write that fully succeeded as a crash. Warned rather than ``_guidance``-d for the same reason the
    soft ``--concerns`` warnings are: the caller still has its own result line to print.
    """
    config = load_config(root / WORKSPACE_DIRNAME / "config.yaml")
    graph, _ = graphdb.rebuild(root, config)  # build + re-materialize the gitignored view
    embeddings.refresh_index(root, graph, config)
    if unwritable := graph.graph.get("view_unwritable"):
        typer.echo(f"⚠ {unwritable}")
    return graph


def _ranked_with_telemetry(root: Path, graph, config: dict | None = None) -> None:
    """Overlay the machine-local usage/last_seen/upholds sidecar for ranking + the maturity verdict (R1).

    Read-path only: the materialized view stays recomputable — telemetry is never written back. After
    the overlay we resolve the read-time ``settled`` verdict from the accumulated ``upholds`` (mem:033);
    without ``config`` we still overlay telemetry but skip the verdict (callers that only need ranking).
    """
    counters.apply_telemetry(graph, counters.load_telemetry(root))
    if config is not None:
        counters.apply_maturity_verdict(graph, config)


def _record_injection(root: Path, graph, result) -> None:
    """Record a surfacing in the gitignored telemetry sidecar (R1): a soft recency/popularity nudge.

    Machine-local and best-effort — it never touches the materialized view, so a query/hook
    never dirties git. A failed write must never break a query or a hook.
    """
    try:
        counters.record_injection(root, graph, list(result.rendered))
    except OSError:
        pass


def _locator_relpath(locator: str) -> str | None:
    """The repo-relative path a ``sym:``/``file:`` concern locator points at (for edit-uphold matching)."""
    if locator.startswith("sym:"):
        return locator[len("sym:"):].split("#", 1)[0]
    if locator.startswith("file:"):
        return locator[len("file:"):].split(":L", 1)[0]
    return None


def _record_edit_upholds(root: Path, graph, config: dict, rel_posix: str) -> None:
    """A survived edit-encounter (mem:033): decisions governing the edited locus that did NOT drift earn
    a weak maturity uphold. Best-effort + fail-open — a sidecar hiccup must never break the hook.

    The edit hook only reaches here when the locus is governed (or drifting); we credit exactly the
    ``concerns`` edges onto *this* file whose anchor still matches (a drifted concern is a violation, not
    a survival, so it's excluded — and drift already asks the agent to re-verify it).
    """
    weight = float(config.get("maturity_uphold_edit", 0.25))
    if weight <= 0:
        return
    drifted = {(i.task_id, i.locator) for i in compute_drift(graph) if i.kind != "renamed"}
    upheld = {
        src for src, tgt, a in graph.edges(data=True)
        if a.get("relation") == "concerns"
        and graph.nodes.get(src, {}).get("family") == memory.MEMORY_FAMILY
        and _locator_relpath(tgt) == rel_posix
        and (src, tgt) not in drifted
    }
    if upheld:
        try:
            counters.record_uphold(root, graph, sorted(upheld), weight)
        except OSError:
            pass


def _record_reaffirm_uphold(repo: Path, config: dict, mem_ids: list[str]) -> None:
    """A reaffirm is an explicit re-verification → a strong maturity uphold (mem:033). Best-effort."""
    if not mem_ids:
        return
    try:
        graph, _ = build_graph(repo, config)
        counters.record_uphold(repo, graph, sorted(set(mem_ids)),
                               float(config.get("maturity_uphold_review", 1.0)))
    except OSError:
        pass


def _find_plan_file(workspace: Path, plan_slug_cf: str) -> Path | None:
    for sub in ("active", "completed"):
        for path in sorted((workspace / "plans" / sub).glob("*.md")):
            if path.stem.casefold() == plan_slug_cf:
                return path
    return None


def _known_plans(workspace: Path) -> list[str]:
    """Plan slugs across active/ and completed/ — for a 'did you mean' on an unknown plan."""
    out: list[str] = []
    for sub in ("active", "completed"):
        out += [p.stem for p in sorted((workspace / "plans" / sub).glob("*.md"))]
    return out


@app.command()
def intent(
    slug: str = typer.Argument(..., help="Slug for the intent file (intents/<slug>.md)."),
    statement: str = typer.Option(None, "--statement", "-s", help="One-line SHALL/MUST contract (required for a new intent)."),
    scenario: list[str] = typer.Option(None, "--scenario", help="A Given/When/Then example (repeatable)."),
    design: str = typer.Option(None, "--design", help="Optional approach / the 'how'."),
    type: str = typer.Option("requirement", "--type", help="requirement | goal | capability."),
    status: str = typer.Option(None, "--status", help="proposed | active | satisfied | archived (default proposed on create)."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Create an intent artifact — or, if it already exists, update its ``--status`` in place.

    An existing intent isn't clobbered: without ``--status`` we still refuse (the anti-clobber guard),
    but ``yigraf intent <slug> --status archived`` retires or re-activates it without a hand-edit —
    the one intent-evolution path that isn't a full reversal (friend-review #2). A *changed contract*
    is a reversal: use ``yigraf supersede-intent`` so the replacement links back to what it replaced.
    """
    if status is not None and status not in artifacts.INTENT_STATUSES:
        _guidance(f"--status must be one of {', '.join(artifacts.INTENT_STATUSES)} (got {status}).")
    workspace = _require_workspace(repo)
    _require_slug(slug, "an intent", 'Pick a plain name — `yigraf intent drift-detection -s "…"`.')
    dest = workspace / "intents" / f"{slug}.md"

    if dest.exists():
        if status is None:
            _guidance(f"Intent int:{slug.casefold()} already exists ({dest}). To retire/reactivate it, "
                      f"`yigraf intent {slug} --status archived`; to reverse its contract, "
                      f'`yigraf supersede-intent {slug} <new-slug> -s "<new contract>"`.')
        artifacts.update_intent_frontmatter(dest, status=status)
        _rebuild(repo)
        typer.echo(f"Updated intent int:{slug.casefold()} → status={status} ({dest})")
        return

    if not statement:
        _guidance(f"No intent int:{slug.casefold()} yet, so --statement is required to create it.")
    dest.parent.mkdir(parents=True, exist_ok=True)  # a bare workspace (subdir unscaffolded) passes _require_workspace
    dest.write_text(
        artifacts.render_intent(slug, statement, scenario or [], design, type=type,
                                status=status or "proposed"),
        encoding="utf-8",
    )
    _rebuild(repo)
    typer.echo(f"Created intent int:{slug.casefold()} ({dest})")


#: Shared help for ``--why-file``, on every verb that takes a ``--why``.
_WHY_FILE_HELP = ("Read --why from a file instead of the command line (mutually exclusive with it). "
                  "For a long reasoning: a refused command is re-sent for the cost of a path rather "
                  "than the whole argument, and nothing between you and the file expands `backticks`, "
                  "$vars or !history. Newlines collapse to spaces — **Why:** is one line.")

#: The separator repeated ``--rejected`` values are joined with. Not a parser token: it is the spelling
#: the store already used, typed by hand in 12 of yigraf's own memories before the flag could repeat.
_REJECTED_SEP = " || "


def _why_text(why: str | None, why_file: Path | None) -> str | None:
    """The reasoning from ``--why`` or ``--why-file`` — never both, ``None`` when neither was passed.

    A long ``--why`` is the most expensive argument yigraf takes and the most fragile. Expensive because
    a refusal costs the whole thing again: every capture guard exits 0 with guidance (design law #1), and
    the agent's next move is to re-transmit the argument it just composed — which is what made a late
    refusal on this path worth filing (feedback-v4 #15; the *ordering* half of that ask was already
    satisfied, the empirical/evidence combination is refused before any build). Fragile because a shell
    is a text transformer: backticks, ``$`` and ``!`` silently rewrite reasoning rather than failing,
    and a mangled ``--why`` is unrecoverable prose, not a syntax error. A file is immune to both.

    Collapsed to one line because ``**Why:**`` *is* one line (:func:`yigraf.memory._parse_body`), and a
    file is the one input that naturally arrives with newlines in it. Collapsing here rather than
    rejecting a multi-line file is the point of the flag — an agent writing a paragraph to a file must
    not have to also flatten it.
    """
    if why_file is None:
        return why or None
    if why:
        _guidance("pass --why or --why-file, not both — they fill the same field, and yigraf will not "
                  "guess which one you meant to win. Drop whichever is the leftover.")
    try:
        raw = Path(why_file).read_text(encoding="utf-8")
    except OSError as exc:
        _guidance(f"couldn't read --why-file {why_file}: {exc}. Nothing was captured — write the "
                  f"reasoning to that path and re-run the same command.")
    text = " ".join(raw.split())  # one line: **Why:** is a single line, and a file arrives with newlines
    if not text:
        _guidance(f"--why-file {why_file} is empty, so there is no reasoning to capture. Write it there "
                  f"and re-run, or drop the flag to capture the claim without a why.")
    return text


def _joined_rejected(rejected: list[str] | None) -> str | None:
    """Join repeated ``--rejected`` values with :data:`_REJECTED_SEP`; ``None`` when none were passed.

    ``--rejected`` was a single-value option, so a second one silently won and the first alternative was
    gone — no warning, at capture time, on the most perishable content in the node (found recording two
    ruled-out designs for one decision). Repeatable is the fix rather than a refusal: a decision often
    rejects more than one thing, the store already spelled that ``a || b`` by hand, and a refusal would
    make the caller do the joining that the flag can now do itself.
    """
    values = [r.strip() for r in (rejected or []) if r and r.strip()]
    return _REJECTED_SEP.join(values) or None


@app.command(name="supersede-intent")
def supersede_intent(
    old_slug: str = typer.Argument(..., help="The intent slug being reversed (its int:<slug> is archived)."),
    new_slug: str = typer.Argument(..., help="Slug for the replacement intent (intents/<new>.md)."),
    statement: str = typer.Option(..., "--statement", "-s", help="The replacement's one-line SHALL/MUST contract."),
    scenario: list[str] = typer.Option(None, "--scenario", help="A Given/When/Then example (repeatable)."),
    design: str = typer.Option(None, "--design", help="Optional approach / the 'how'."),
    type: str = typer.Option("requirement", "--type", help="requirement | goal | capability."),
    why: str = typer.Option("", "--why", help="Why the premise changed — captured as a memory serving the new intent."),
    why_file: Path = typer.Option(None, "--why-file", help=_WHY_FILE_HELP),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Reverse an intent: create the replacement, archive the old, and write a real int→int supersedes edge.

    The most important decision class — a reversal — was the one the graph couldn't represent
    structurally (``supersede`` took ``mem:`` only; ``superseded_by:`` frontmatter produced 0 edges).
    This creates ``int:<new>`` with a ``supersedes: [int:<old>]`` field (the traversable edge), flips
    ``int:<old>`` to ``archived`` (stamping ``superseded_by`` for legibility), and — given ``--why`` —
    captures the reversal's rationale as a memory serving the new intent (the perishable *why*).
    """
    if type not in artifacts.INTENT_TYPES:
        _guidance(f"--type must be one of {', '.join(artifacts.INTENT_TYPES)} (got {type}).")
    workspace = _require_workspace(repo)
    for value in (old_slug, new_slug):
        _require_slug(value, "an intent", 'Pick a plain name — `yigraf supersede-intent old new -s "…"`.')
    old_id, new_id = f"int:{old_slug.casefold()}", f"int:{new_slug.casefold()}"
    old_dest = workspace / "intents" / f"{old_slug}.md"
    new_dest = workspace / "intents" / f"{new_slug}.md"

    if not old_dest.exists():
        _guidance(f"No intent {old_id} to supersede ({old_dest} not found). "
                  f'Find it with `yigraf context "<topic>" --family intent`.')
    if new_dest.exists():
        _guidance(f"Intent {new_id} already exists ({new_dest}). Pick a different new slug.")

    new_dest.parent.mkdir(parents=True, exist_ok=True)  # a bare workspace (subdir unscaffolded) passes _require_workspace
    new_dest.write_text(
        artifacts.render_intent(new_slug, statement, scenario or [], design, type=type,
                                status="active", supersedes=[old_id]),
        encoding="utf-8",
    )
    artifacts.update_intent_frontmatter(old_dest, status="archived", superseded_by=new_id)
    _rebuild(repo)
    typer.echo(f"Superseded {old_id} → {new_id} (old archived; {new_id} —supersedes→ {old_id})")

    if why:
        node = _capture_memory(repo, workspace, statement=f"{new_id} supersedes {old_id}", type_="decision",
                               why=_why_text(why, why_file) or "", serves=[new_id],
                               concern_syms=[], rejected=None,
                               supersedes=[], promotable=False, force_new=True)
        _report_capture(node, repo, load_config(workspace / "config.yaml"))


@app.command()
def plan(
    slug: str = typer.Argument(..., help="Slug for the plan file (plans/active/<slug>.md)."),
    title: str = typer.Option(None, "--title", "-t", help="Plan title (required to create)."),
    task: list[str] = typer.Option(None, "--task", help="A task description (repeatable)."),
    append_task: list[str] = typer.Option(None, "--append-task", help="Add a task to an EXISTING plan (repeatable) — numbers continue past the highest, never reused."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Create a plan artifact with todo tasks — or, with ``--append-task``, extend a live one.

    Appending exists because the CLI could not add to a plan at all: a campaign that ran 125 cells
    across four stages created ZERO tasks, partly because ``plan <existing-slug> --task`` refuses with
    "already exists … Edit it directly", so the graph held that campaign's decisions and none of its
    work (feedback-v4 #1). Task numbers continue past the highest and are never reused, so an id
    already recorded on a ``link`` edge cannot come to mean a different task.
    """
    workspace = _require_workspace(repo)
    _require_slug(slug, "a plan", 'Pick a plain name — `yigraf plan auth-rewrite -t "…"`.')
    dest = workspace / "plans" / "active" / f"{slug}.md"
    # Keyed on the RESOLVED path as well as the slug glob, because those two can disagree and the
    # disagreement is a silent overwrite (feedback-v7 G#1). `_find_plan_file` compares a glob's
    # `path.stem`, and `Path(".md").stem` is `".md"`, not `""` — so the empty slug wrote
    # `plans/active/.md`, failed to find itself, and the second call replaced a live plan's title,
    # tasks and stamped `implements` anchor while printing "Created". `_require_slug` now refuses the
    # empty string one line up; this is the check that does not depend on guessing every shape that
    # can round-trip badly. `intent` and `supersede-intent` were never exposed because they test the
    # resolved `dest.exists()` — this is them.
    existing = _find_plan_file(workspace, slug.casefold()) or (dest if dest.exists() else None)

    if append_task:
        if existing is None:
            known = _known_plans(workspace)
            _guidance(f"No plan plan:{slug.casefold()} to append to." +
                      (f" Known plans: {', '.join(known)}." if known else "") +
                      f' Create it with `yigraf plan {slug} -t "<title>" --task "…"`.')
        assigned = artifacts.append_tasks(existing, list(append_task))
        _rebuild(repo)
        for num, desc in zip(assigned, append_task):
            typer.echo(f"Added task:{slug.casefold()}/{num}: {desc}")
        typer.echo(f"Anchor them as you land them — `yigraf link task:{slug.casefold()}/{assigned[0]} "
                   f"sym:<path>#<name>` — then `yigraf close` when done.")
        return

    if existing is not None:
        _guidance(f"Plan plan:{slug.casefold()} already exists ({existing}). To add work to it, "
                  f'`yigraf plan {slug} --append-task "<description>"`; to close a task, '
                  f"`yigraf close task:{slug.casefold()}/<n>`; to list what's open, "
                  f"`yigraf tasks {slug} --open`. Or pick a new slug for a separate plan.")
    if not title:
        _guidance(f'No plan plan:{slug.casefold()} yet, so --title is required to create it.')
    dest.parent.mkdir(parents=True, exist_ok=True)  # a bare workspace (subdir unscaffolded) passes _require_workspace
    dest.write_text(artifacts.render_plan(slug, title, task or []), encoding="utf-8")
    _rebuild(repo)
    typer.echo(f"Created plan plan:{slug.casefold()} with {len(task or [])} task(s) ({dest})")


def _resolve_task(workspace: Path, task_id: str):
    """``(plan_file, task)`` for a task locator, guiding on every way it can miss. Shared by the state
    verbs and ``link``, so one wrong id gets one wording."""
    match = _TASK_ID.match(task_id)
    if match is None:
        _guidance(f"{task_id} isn't a task locator (expected task:<plan>/<n>, e.g. task:auth/1). "
                  f"List them with `yigraf tasks`.")
    plan_file = _find_plan_file(workspace, match.group(1).casefold())
    if plan_file is None:
        known = _known_plans(workspace)
        _guidance(f"No plan found for {task_id}." +
                  (f" Known plans: {', '.join(known)}." if known else " Create one with `yigraf plan`."))
    tasks = artifacts.read_plan(plan_file).tasks
    task = next((t for t in tasks if t.id == task_id), None)
    if task is None:
        ids = ", ".join(t.id for t in tasks) or "(none)"
        _guidance(f"{task_id} is not a task in {plan_file.name}. Tasks there: {ids}.")
    return plan_file, task


@app.command()
def close(
    task_id: str = typer.Argument(..., help="Task locator, e.g. task:<plan>/1."),
    reopen: bool = typer.Option(False, "--reopen", help="Re-open a done task instead of closing it."),
    force: bool = typer.Option(False, "--force", help="Close even with no implements link; records that the task shipped no symbol, so it stops being a capture gap (a later `link` retires the record)."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Mark a task done (or, with ``--reopen``, not done) by writing its checkbox in the plan file.

    The checkbox has always BEEN the interface — ``plan``'s refusal and a ⚠ in ``context`` were the only
    two places that said so, and no prose doc did — but nothing wrote it, so the one family whose truth
    is a committed markdown file had no verb for its mutable state while its sibling (``intent <slug>
    --status``) did. An agent that had internalised "never hand-edit an artifact" therefore could not
    close a task at all, and open counts drifted until the number stopped being read (feedback-v4 #1).

    R6 is untouched: the file is still truth, this verb just writes it — nothing about done-ness is
    stored in the graph, which goes on deriving ``state`` from the checkbox on every build.

    Closing refuses a task with no ``implements`` edge unless ``--force``, so "done" and "anchored" land
    together. That is not bookkeeping: a completion with no anchor can never go STALE, so the whole
    drift-as-stale mechanism silently does not apply to it.

    ``--force`` *records* that choice in the plan (``unanchored:``) rather than only moving the
    checkbox. Without the record the capture-gap ⚠ — whose own guidance offers ``--force`` as the exit
    for work that shipped no symbol — went on firing every session with nothing able to clear it, which
    is the shape of warning an agent learns to scroll past. Because the warning fires on a task that is
    already done, ``--force`` is reachable there too, as a repair.
    """
    workspace = _require_workspace(repo)
    plan_file, task = _resolve_task(workspace, task_id)
    if reopen:
        if not artifacts.set_task_state(plan_file, task.num, done=False):
            _guidance(f"{task_id} is already open — nothing to reopen.")
        _rebuild(repo)
        typer.echo(f"Reopened {task_id} — [ ] in {plan_file.name}. Its implements anchors are untouched; "
                   f"if the work regressed, the symbols it named are where to look.")
        return
    if task.state == "done":
        # The repair path for a completion closed before --force recorded anything: the capture-gap
        # warning names this exact command, so it has to be reachable on a task that is already done —
        # otherwise the guidance sends the reader to a verb that answers "already done" and the ⚠ it
        # was raised by fires again next session, forever.
        if force and not task.implements and artifacts.mark_task_unanchored(plan_file, task_id):
            _rebuild(repo)
            typer.echo(f"Recorded {task_id} as implementing nothing, on purpose — [x] was already "
                       f"written; what was missing was the reason it names no symbol.")
            typer.echo("It stops being reported as a capture gap. While it names no symbol it can "
                       "never go STALE: if the work later grows one, `yigraf link` re-earns that and "
                       "retires this record.")
            return
        _guidance(f"{task_id} is already done. To re-open it, `yigraf close {task_id} --reopen`.")
    if not task.implements and not force:
        _guidance(f"{task_id} implements nothing, so closing it would record a completion with no "
                  f"evidence — it could never go STALE when the code changes, which is the whole "
                  f"point of marking it done. Name what it built first: "
                  f"`yigraf link {task_id} sym:<path>#<name>`. If it genuinely shipped no symbol "
                  f"(a doc, a config, a decision), `yigraf close {task_id} --force`.")
    if not task.implements:  # --force: record WHY there is no anchor, not just the moved checkbox
        artifacts.mark_task_unanchored(plan_file, task_id)
    artifacts.set_task_state(plan_file, task.num, done=True)
    _rebuild(repo)
    anchored = ", ".join(i.sym for i in task.implements) or "nothing (forced)"
    typer.echo(f"Closed {task_id} — [x] in {plan_file.name}, implementing {anchored}.")
    if not task.implements:
        typer.echo("Recorded as unanchored, so it is not reported as a capture gap. While it names no "
                   "symbol it can never go STALE either — that is the price of the anchor it does not "
                   "have, and `yigraf link` re-earns both.")
        return
    typer.echo("Its anchors now carry the completion: if they drift, it surfaces as a STALE completion "
               "(`yigraf drift --stale`), cleared by re-`link` once re-verified.")


@app.command()
def tasks(
    plan_slug: str = typer.Argument(None, help="Only this plan's tasks (default: every plan)."),
    open_only: bool = typer.Option(False, "--open", help="Only tasks whose box is unchecked."),
    done_only: bool = typer.Option(False, "--done", help="Only tasks whose box is checked."),
    stale: bool = typer.Option(False, "--stale", help="Only done tasks whose implementing symbol drifted."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Enumerate tasks and their state — the answer to "what is outstanding" that does not depend on a
    query matching.

    ``context`` already renders tasks with ``☑``/``☐``, but its seeder is semantic even under
    ``--family plan``, so the literal question missed: ``context "what is outstanding" --family plan``
    returned 0 nodes. ``status`` gave a bare count, ``show plan:<slug>`` listed ids without state, and
    ``drift --stale`` listed only done-and-drifted ones. The surface existed and could not be addressed
    deliberately (feedback-v4 #1).
    """
    workspace = _require_workspace(repo)
    config = load_config(workspace / "config.yaml")
    if open_only and done_only:
        _guidance("--open and --done select disjoint sets — pass one, or neither for both.")
    # No "Known: …" tail here, unlike the unknown-slug case below: the mistake is the convention, not
    # the name, so listing every plan would spend the agent's budget answering a question it isn't asking.
    _require_slug(plan_slug, "a plan",
                  "For every plan's tasks run `yigraf tasks --repo <path>`; for one plan's, "
                  "`yigraf tasks <slug>`.")
    graph, _ = build_graph(repo, config)
    stale_ids = {i.task_id for i in stale_completions(graph)}

    plans = []
    for sub in ("active", "completed"):
        for path in sorted((workspace / "plans" / sub).glob("*.md")):
            if plan_slug and path.stem.casefold() != plan_slug.casefold():
                continue
            plans.append(artifacts.read_plan(path))
    if plan_slug and not plans:
        known = _known_plans(workspace)
        _guidance(f"No plan {plan_slug}." + (f" Known: {', '.join(known)}." if known else ""))

    shown = 0
    for plan in plans:
        rows = []
        for t in plan.tasks:
            if open_only and t.state == "done":
                continue
            if done_only and t.state != "done":
                continue
            if stale and t.id not in stale_ids:
                continue
            mark = "⚠" if t.id in stale_ids else ("☑" if t.state == "done" else "☐")
            impl = f"  ({', '.join(i.sym for i in t.implements)})" if t.implements else ""
            rows.append(f"  {mark} {t.id}: {t.description}{impl}")
        if rows:
            typer.echo(f"{plan.id} — {plan.title}")
            typer.echo("\n".join(rows))
            typer.echo("")
            shown += len(rows)
    if not shown:
        which = ("stale completions" if stale else "open tasks" if open_only
                 else "done tasks" if done_only else "tasks")
        typer.echo(f"No {which}.")
        return
    # The legend explains a mark; print it only when a mark is on screen (design law #4).
    typer.echo(f"{shown} task(s)."
               + (" ⚠ = done but its implementing symbol drifted — re-`link` once re-verified, or "
                  "`yigraf close <task> --reopen` if the change undid the work." if stale_ids else ""))


@app.command()
def link(
    task_id: str = typer.Argument(..., help="Task locator, e.g. task:<plan>/1."),
    target: str = typer.Argument(..., help="A symbol (sym:<path>#<name>) → implements, or an intent (int:<slug>) → tracks."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Declare an implements (→ symbol) or tracks (→ intent) edge from a task; stamps the anchor."""
    workspace = _require_workspace(repo)
    plan_file, task = _resolve_task(workspace, task_id)

    if target.startswith("sym:") or target.startswith("file:"):
        config = load_config(workspace / "config.yaml")
        anchor, algo = _anchor_or_guide(repo, config, target)
        moved_from = _renamed_predecessor(repo, config, task, target, anchor)
        artifacts.add_edge_to_plan(plan_file, task_id, "implements", target, anchor=anchor,
                                   anchor_algo=algo, stamped_at=counters._head_sha(repo),
                                   replaces=moved_from)
        # The task now names a symbol, so the `unanchored:` marker it may carry — "this completion
        # implements nothing, on purpose" — has stopped being true, and `_capture_gaps` reads it in the
        # PRESENT tense: what it needs to know is whether the task names a symbol NOW (feedback-v9 H#2).
        # Nothing else cleared it, and `close --force`'s own output sends the reader straight here
        # ("if the work later grows a symbol, `yigraf link` re-earns that"), so the marker outlived the
        # assertion in two ways. It let this verb mint a state `close` refuses to write — marked
        # unanchored AND carrying an implements edge, where the promised "can never go STALE" is simply
        # false — and, once a later `unlink` retired that edge, the surviving marker exempted a
        # genuinely gap-shaped task from the detector for good. Clearing here closes both: the first
        # state can no longer exist, and the second decays to an honest unmarked gap.
        # Only this branch. `link <task> int:<slug>` declares that the task TRACKS an intent, which
        # asserts nothing about whether it implements a symbol — clearing there would re-open the nag
        # on work that genuinely shipped none.
        unmarked = artifacts.mark_task_unanchored(plan_file, task_id, False)
        typer.echo(f"Linked {task_id} —implements→ {target} (anchored {anchor[:12]})"
                   + (f" — settled the rename from {moved_from}, which the graph had re-anchored by "
                      f"content hash and this artifact had not." if moved_from else ""))
        if unmarked:
            typer.echo(f"{task_id} is no longer recorded as unanchored: it names a symbol now, so it "
                       f"can go STALE when that symbol drifts — and it is an ordinary capture gap "
                       f"again if you retire this edge.")
    elif target.startswith("int:"):
        artifacts.add_edge_to_plan(plan_file, task_id, "tracks", target)
        typer.echo(f"Linked {task_id} —tracks→ {target}")
    else:
        _guidance("Target must be a symbol (sym:<path>#<name>) or file (file:<path>[:L<a>-L<b>|#<section>]) → "
                  f"implements, or an intent (int:<slug>) → tracks. Got: {target}")

    _rebuild(repo)


def _renamed_predecessor(repo: Path, config: dict, task, target: str, anchor: str) -> str | None:
    """The locator ``target`` is a RENAME of, among the ones ``task`` already declares — or ``None``.

    ``link`` keys ``implements`` by the exact locator string, so a moved symbol is a different string
    and re-linking appends: the task ends up declaring both, and the one the subject LEFT becomes hard
    drift the moment its body changes. :func:`yigraf.artifacts.remove_edge_from_plan` refused to fold
    an auto-replace into ``link`` for a sound reason — a task may legitimately implement several
    symbols, so replacing on a guess would silently delete a real edge.

    This does not guess. It asks :func:`yigraf.drift.resolve_renames`, through ``compute_drift``, which
    already carries every false-positive guard the rescue needs (a unique hit, scoped per
    mem:e7b656321265b8d6, empty-body hashes excluded) — so a replacement happens only where the engine
    has already *proved* the move, and every other link appends exactly as before.

    The graph is built only when the cheap test passes: a rename is a content-hash MATCH, so an entry
    the subject moved off carries the identical anchor. No matching anchor on the task, no build — which
    is every ordinary ``link``, the most-used write verb in the loop.
    """
    candidates = {i.sym for i in task.implements if i.anchor == anchor and i.sym != target}
    if not candidates:
        return None
    graph, _ = build_graph(repo, config)
    for item in compute_drift(graph):
        if (item.kind == "renamed" and item.task_id == task.id and item.new_locator == target
                and item.locator in candidates):
            return item.locator
    return None


@app.command()
def unlink(
    source: str = typer.Argument(..., help="Task locator (task:<plan>/<n>) or memory id (mem:<id> → retire a concerns or grounded_by ref)."),
    target: str = typer.Argument(..., help="The edge to retire, exactly as it appears on the node: a symbol/file/intent on a task, or a concerns/grounded_by ref on a memory."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Retire a declared edge — the way out of drift on a declaration that is simply no longer true.

    ``link`` keys ``implements`` by the exact locator, so a symbol that MOVES is a new string; it
    replaces the old entry only where ``resolve_renames`` has *proved* the move
    (:func:`_renamed_predecessor`), and appends otherwise. A move *plus* an edit is past that proof —
    hard drift on a locator that will never resolve again, unclearable by any other verb, because
    ``reaffirm`` re-anchors and ``supersede`` restates a *belief*, and this is neither: the declaration
    is simply no longer true. (Settle a rename BEFORE editing the body — `yigraf gc --apply` — and this
    verb is never needed for it.)

    This is a graph edit, not a mind-change, so it leaves no supersedes trail — retiring a link asserts
    "this task never implemented that, or no longer does", which is exactly what a wrong or stale
    declaration deserves. Use ``link`` (not ``unlink`` + ``link``) when the work merely moved and you
    want the edge re-anchored to the new locus.

    ``mem:<id>`` dispatches to the same operation on a memory's ``grounded_by`` and ``concerns`` refs —
    prefix dispatch over the locator idiom, as ``reaffirm`` already does (mem:039), because it is the
    identical assertion about a different family: this observation does not ground that belief, or
    this belief never governed that locus. (A locus that MOVED is ``reanchor``, not unlink+re-add.)
    """
    workspace = _require_workspace(repo)
    if source.startswith("mem:"):
        _unlink_memory_ref(repo, source, target)
        return
    task_id = source
    match = _TASK_ID.match(task_id)
    if match is None:
        _guidance(f"{task_id} isn't a task locator (expected task:<plan>/<n>, e.g. task:auth/1). "
                  f'Find tasks with `yigraf context "<plan>"`.')
    plan_file = _find_plan_file(workspace, match.group(1).casefold())
    if plan_file is None:
        known = _known_plans(workspace)
        _guidance(f"No plan found for {task_id}." +
                  (f" Known plans: {', '.join(known)}." if known else " Create one with `yigraf plan`."))

    removed = artifacts.remove_edge_from_plan(plan_file, task_id, target)
    if removed is None:
        # Name what the task actually declares: the usual cause is a locator that reads right but isn't
        # the string on disk (a moved path, a guessed symbol name), and the fix is to copy one of these.
        tasks = artifacts.read_plan(plan_file).tasks
        task = next((t for t in tasks if t.id == task_id), None)
        if task is None:
            ids = ", ".join(t.id for t in tasks) or "(none)"
            _guidance(f"{task_id} is not a task in {plan_file.name}. Tasks there: {ids}.")
        declared = ([task.tracks] if task.tracks else []) + [i.sym for i in task.implements]
        _guidance(f"{task_id} doesn't declare {target}, so there's nothing to retire. "
                  + (f"It declares: {', '.join(declared)}." if declared
                     else "It declares no edges at all."))
    _rebuild(repo)
    typer.echo(f"Unlinked {task_id} —{removed}→ {target}")


def _unlink_memory_ref(repo: Path, mem_id: str, target: str) -> None:
    """Retire a ref a memory carries — a dead ``grounded_by`` observation, or a mis-declared
    ``concerns`` anchor.

    ``--evidence`` *upserts*: it re-anchors a ref whose target changed, or appends a new one. Neither
    reaches a ref whose target was DELETED — the ref drifts forever and the belief carries a citation
    to something that no longer exists. Removing it is a graph edit, not a mind-change.

    ``concerns`` is retirable here too (supersedes the earlier not-retirable stance; feedback-v3 #2):
    the real case is a MIS-CAPTURE — a belief anchored at capture to a locus it never governed, whose
    only repair was hand-editing frontmatter while this refusal read as "no such anchor". Retiring a
    concern asserts "this belief never governed that locus". A locus that *moved* is ``reanchor``; a
    claim whose subject genuinely changed is ``supersede``.
    """
    path = memory.find_memory(repo, mem_id)
    if path is None:
        _guidance(f"No memory node with id {mem_id}. "
                  f'Find the decision you mean with `yigraf context "<topic>"`.')
    node = memory.read_memory(path)
    in_evidence = target in {e.ref for e in node.evidence}
    in_concerns = target in {c.sym for c in node.concerns}
    if not in_evidence and not in_concerns:
        # Name every anchor the node DOES carry (feedback-v3 #2: the old wording was true of
        # grounded_by and read as "this memory has no such anchor" while `show` listed the concern
        # two lines later). The usual cause is a ref that reads right but isn't the string on disk.
        _guidance(f"{mem_id} doesn't carry {target} on any anchor list, so there's nothing to retire. "
                  + _carried_anchors(node))
    if in_evidence and node.grounding == "empirical" and len(node.evidence) == 1:
        # Never let a retirement silently strand an ·empirical claim with nothing behind it — that is
        # the loophole the capture/reaffirm gate closes, and reopening it here would make `unlink` the
        # quiet way to keep a tier you can no longer justify.
        _guidance(f"Retiring {target} would leave {mem_id} ·empirical with nothing grounding it. Name "
                  f"what replaces it first — `yigraf reaffirm {mem_id} --grounding empirical --evidence "
                  f"<fresh>` — or downgrade honestly, `yigraf reaffirm {mem_id} --grounding inferred`, "
                  f"and then retire this ref.")
    retired = []
    if in_evidence:
        node.evidence = [e for e in node.evidence if e.ref != target]
        retired.append("grounded_by")
    if in_concerns:
        node.concerns = [c for c in node.concerns if c.sym != target]
        retired.append("concerns")
    path.write_text(memory.render_memory(node), encoding="utf-8")
    _rebuild(repo)
    for relation in retired:
        typer.echo(f"Unlinked {mem_id} —{relation}→ {target}")
    if "concerns" in retired and not node.concerns:
        typer.echo(f"⚠ {mem_id} now concerns nothing — it stays retrievable by meaning but will never "
                   f"surface at an edit hook. If it should govern a locus, supersede it with "
                   f"--concerns <locus>.")


def _carried_anchors(node: memory.Memory) -> str:
    """One sentence naming every anchor a memory carries, for a refusal that must not read as 'none'."""
    carried = []
    if node.concerns:
        carried.append("concerns " + ", ".join(c.sym for c in node.concerns))
    if node.evidence:
        carried.append("grounded by " + ", ".join(e.ref for e in node.evidence))
    return f"It carries: {'; '.join(carried)}." if carried else "It carries no anchors at all."


@app.command()
def reanchor(
    target: str = typer.Argument(..., help="The memory id (mem:NNN) whose anchor moved."),
    old: str = typer.Argument(..., help="The anchor to move, exactly as the node carries it (concerns or grounded_by)."),
    new: str = typer.Argument(..., help="Where the subject now lives: sym:<path>#<name>, file:<path>[:L<a>-L<b>] or — in markdown — file:<path>#<section>."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Move ONE anchor to the locus its subject moved to — a locus repair, not a mind-change.

    The missing verb the field paid for four times (feedback-v3 #2): re-pointing a moved anchor had to
    route through `supersede`, which files a mind-change nobody had — four nodes whose entire body
    reads "LOCUS REPAIR ONLY — see the node this supersedes for the argument", each a false entry in
    the supersedes trail, the most valuable structure in the graph. `reanchor` writes no supersedes
    edge: the claim, its why, and its history are untouched; only where it anchors moves.

    One meaning per verb: the belief holds and its locus MOVED → `reanchor`. The belief holds and its
    unchanged locus drifted → `reaffirm` (re-verify first). Your mind changed → `supersede`. The
    anchor never belonged at all → `unlink`. Re-verify that the new locus really carries the subject
    before moving — re-stamping the wrong region is the one outcome the drift design exists to prevent.
    """
    workspace = _require_workspace(repo)
    config = load_config(workspace / "config.yaml")
    if not target.startswith("mem:"):
        _guidance(f"reanchor takes a memory id (mem:NNN), got: {target}. A task's implements edge is "
                  f"re-anchored by re-linking: `yigraf link <task> <sym>`.")
    path = memory.find_memory(repo, target)
    if path is None:
        _guidance(f"No memory node with id {target}. "
                  f'Find the decision you mean with `yigraf context "<topic>"` or `yigraf show <id>`.')
    node = memory.read_memory(path)
    # Both ends canonicalize (feedback-v5 B): `old` so a heading typed as written still MATCHES the
    # slug the node stores, `new` so the repair lands on the addressable spelling.
    old, new = _canonical_locus(repo, old), _canonical_locus(repo, new)
    in_concerns = old in {c.sym for c in node.concerns}
    in_evidence = old in {e.ref for e in node.evidence}
    if not in_concerns and not in_evidence:
        _guidance(f"{target} doesn't carry {old} on any anchor list, so there's nothing to move. "
                  + _carried_anchors(node))
    if not (new.startswith("sym:") or new.startswith("file:")):
        _guidance(f"the new locus must be sym:<path>#<name>, file:<path>[:L<a>-L<b>] or, in markdown, "
                  f"file:<path>#<section>, got: {new}")
    graph, _ = build_graph(repo, config)
    if new.startswith("sym:") and "#" not in new:
        _refuse_bare_sym(graph, new, "reanchor")
    # A POLICY anchor keeps its kind across the move (feedback-v4 #5): `_anchor` would stamp a content
    # hash, silently turning "this belief governs how p.md is used" into "this belief depends on q.md's
    # bytes" — reintroducing the recurring never-real ⚠ that `--governs` exists to prevent, while the
    # success line says "the claim and its history are unchanged" (true of the claim, false of what the
    # anchor MEANS). GOVERNS_ALGO's docstring named `reaffirm` as the only re-stamper that must leave it
    # alone; `reanchor` is the second. The new locus is validated as a policy locus, not merely resolved.
    governs_move = in_concerns and any(
        c.sym == old and (c.anchor_algo or "") == memory.GOVERNS_ALGO for c in node.concerns)
    # Evidence is never a policy anchor (grounding cites contents, not use), so a ref carried on BOTH
    # lists resolves twice — the policy kind for the concern, a content hash for the evidence.
    content_anchor = None
    if governs_move:
        _resolve_governs(repo, config, graph, [new])  # validates it IS a policy locus: exists, no line range
    if in_evidence or not governs_move:
        content_anchor = _anchor(repo, config, new)
        if content_anchor[0] is None:
            # Unlike capture, no forward-reference here: a repair points at code that exists — a dangling
            # "repair" would just trade hard drift on the old locus for hard drift on the new one.
            _guidance(f"{new} doesn't resolve in the current source — a locus repair points at code that "
                      f"exists (capture allows a forward-reference; a repair does not)."
                      # `repo` is what lets the tail serve a SECTION locator too (feedback-v5 B). Every
                      # capture-path call site passed it; this one did not, so the one refusal a
                      # returning user meets first — `mdsec-v1` is the newest anchor kind — was also the
                      # only one that dropped the "did you mean" and read as "sections aren't indexed".
                      + _symbol_suggestion(graph, new, repo))
    # Two outcomes per list, and the success line has to tell them apart (feedback-v7 G#3). When the
    # destination is ALREADY carried there is nothing to move onto it, so `old` is dropped — the end
    # state `unlink` produces, which the docstring above names as a different verb for a different
    # meaning. Printing that as `old ⇒ new` said an anchor moved while the count went 2 → 1, silently
    # and at exit 0, on a node no verb can add a `concerns` anchor back to. The root is one this
    # function already writes down one branch over (the `--governs` comment above): a success line
    # printed after a branch with more than one outcome.
    moved: list[str] = []
    dropped: list[str] = []
    if in_concerns:
        anchor, algo = (None, memory.GOVERNS_ALGO) if governs_move else content_anchor
        label = "governs" if governs_move else "concerns"
        if any(c.sym == new for c in node.concerns):
            node.concerns = [c for c in node.concerns if c.sym != old]  # already anchored there — drop the old
            dropped.append(label)
        else:
            node.concerns = [memory.Concern(sym=new, anchor=anchor, anchor_algo=algo)
                             if c.sym == old else c for c in node.concerns]
            moved.append(label)
    if in_evidence:
        if any(e.ref == new for e in node.evidence):
            node.evidence = [e for e in node.evidence if e.ref != old]
            dropped.append("grounded_by")
        else:
            node.evidence = [memory.Evidence(ref=new, anchor=content_anchor[0], anchor_algo=content_anchor[1])
                             if e.ref == old else e for e in node.evidence]
            moved.append("grounded_by")
    path.write_text(memory.render_memory(node), encoding="utf-8")
    _rebuild(repo)
    lines = []
    if moved:
        lines.append(f"Reanchored {target} ({' + '.join(moved)}): {old} ⇒ {new}."
                     + (" It stays a policy anchor (governs — never drifts)." if governs_move else ""))
    if dropped:
        lines.append(f"⚠ Dropped {old} from {target} ({' + '.join(dropped)}) — {new} was already there, "
                     f"so this REMOVED an anchor rather than moving one, exactly as "
                     f"`yigraf unlink {target} {old}` would have. That is one fewer locus watched for "
                     f"drift, and no verb adds a `concerns` anchor back: recovering both needs an edit "
                     f"to {path.name}.")
    lines.append("The claim and its history are unchanged — no supersede recorded.")
    typer.echo(" ".join(lines))


#: Frontmatter fields that can name a memory id and BLOCK a re-key. ``supersedes`` (memory) and
#: ``left``/``right`` (resolution) are the *cascading* ones — inside their own node's id payload, so
#: re-keying a node would re-key them too. ``pending_supersedes`` and the rejection premises do not
#: cascade but still block: a human is mid-decision about that node, or another belief's rejection hangs
#: on its liveness. ``equivalent_to`` needs no entry — a reconcile verdict always also writes the
#: resolution artifact that names the pair, which is cascading and catches it.
_MEMORY_BLOCKING_FIELDS = ("supersedes", "pending_supersedes",
                           "rejected_valid_when", "rejected_invalidated_when")
_RESOLUTION_REF_FIELDS = ("left", "right")


def _amend_referrers(repo: Path, mem_id: str) -> tuple[list[str], list[Path]]:
    """``(blockers, back_refs)`` for ``mem_id``: what forbids a re-key, and what merely needs re-pointing.

    ``amend`` re-keys the node, unavoidably: the id is a content hash over exactly the statement / why /
    rejected it repairs (``memid-v1``), and a test pins the on-disk id to that payload. So a referrer is
    usually not a bookkeeping chore but a **cascade** — a successor's id hashes its own ``supersedes``
    list and a resolution's hashes the pair it reconciles, so re-keying one node would re-key its
    referrers, and theirs, each losing the telemetry and history that hung off the old id. Those refuse:
    a belief something has already built on is corrected additively, by ``supersede``.

    ``superseded_by`` is the one exception, and excluding it is not a convenience — it is the difference
    between the verb working and not. A ``supersede`` takes a ``--why`` of its own, so the node most
    likely to need repair is the successor that was just written, whose only referrer is the predecessor
    pointing forward at it. That back-pointer is a stamp rather than an identity: it is absent from the
    id payload (unlike ``supersedes``, its mirror), so re-pointing it costs nothing and cascades nowhere.
    ``render_memory`` is lossless, so the predecessor is rewritten with only that field moved.
    """
    blockers: list[str] = []
    back_refs: list[Path] = []
    for path in sorted(memory.memory_dir(repo).glob("*.md")) if memory.memory_dir(repo).is_dir() else []:
        meta, _ = memory._split_frontmatter(path.read_text(encoding="utf-8"))
        if meta.get("id") == mem_id:
            continue  # its own id is not a reference to itself
        for field in _MEMORY_BLOCKING_FIELDS:
            value = meta.get(field)
            names = value if isinstance(value, list) else [value] if value else []
            if mem_id in names:
                blockers.append(f"{meta.get('id', path.name)} ({field})")
        if meta.get("superseded_by") == mem_id:
            back_refs.append(path)
    res_dir = resolution.resolutions_dir(repo)
    for path in sorted(res_dir.glob("*.md")) if res_dir.is_dir() else []:
        meta, _ = memory._split_frontmatter(path.read_text(encoding="utf-8"))
        if any(meta.get(f) == mem_id for f in _RESOLUTION_REF_FIELDS):
            blockers.append(f"{meta.get('id', path.name)} ({meta.get('kind', 'resolution')})")
    return blockers, back_refs


def _pushed_ids(repo: Path, config: dict) -> set[str] | None:
    """Assertion ids this workspace's shared log already holds — or ``None`` when that is unknowable.

    ``None`` is the honest third answer and the reason this returns a tri-state: offline (no
    ``online.project``) there is no shared log to contradict, and an unreadable replica means yigraf
    cannot tell. Both must read as "no positive evidence it was pushed", so a caller can refuse only on
    a *known* push and never on a broken cache (design law #5) — the same shape
    ``counters.survival_floor_applies`` uses for a measurement it could not take.
    """
    project = (config.get("online") or {}).get("project")
    path = replica_path(repo, config)
    if not project or path is None or not path.exists():
        return None
    try:
        from yigraf.onlinelog import SqliteAssertionStore

        store = SqliteAssertionStore(path)
        try:
            return store.known_ids(project)
        finally:
            store.close()
    except Exception:  # noqa: BLE001 - a broken replica must not block a local record repair
        return None


@app.command()
def amend(
    target: str = typer.Argument(..., help="The memory id (mem:...) whose RECORD is wrong."),
    statement: str = typer.Option(None, "--statement", help="Replace the one-line claim (the H2 heading)."),
    why: str = typer.Option(None, "--why", help="Replace the reasoning."),
    why_file: Path = typer.Option(None, "--why-file", help=_WHY_FILE_HELP),
    rejected: list[str] = typer.Option(None, "--rejected", help="Replace the rejected alternative (repeatable — joined with \' || \')."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Repair a botched RECORD — a shell-mangled --why, a typo in the claim — filing no mind-change.

    The verb :func:`yigraf.memory._render_body` has been naming in its own refusal, for the gap the
    field kept paying: a `--why` that a shell rewrote (backticks, `$`, `!`) is unrecoverable prose, and
    the only exits were to delete the artifact by hand or to `supersede` — which files a mind-change
    nobody had and leaves the mangled text standing as the "superseded" belief, in the trail that is the
    most valuable structure in the graph. `reanchor` is the same argument for a moved locus, and this is
    its sibling: the belief, its anchors, its grounding, its maturity and its history are untouched, and
    no supersedes edge is written.

    One meaning per verb. The claim is wrong → `supersede`. The locus moved → `reanchor`. The locus
    drifted → `reaffirm`. **What you WROTE about an unchanged belief is wrong → `amend`.** If your mind
    changed at all, this is the wrong verb: it rewrites the record rather than preserving both readings.

    It re-keys the node, because it must: the id is a content hash over exactly the fields it repairs
    (``memid-v1``), so the new record gets the new id, the old file is removed, and the accumulated
    telemetry moves across (same belief, so its earned survival is not forfeited). That is also why it
    refuses on a node anything else names, or one already pushed to a shared log — see
    :func:`_amend_referrers` and the append-only note below.
    """
    workspace = _require_workspace(repo)
    config = load_config(workspace / "config.yaml")
    if not target.startswith("mem:"):
        _guidance(f"amend repairs a memory record and takes a memory id (mem:...), got: {target}. "
                  f"An intent's statement is revised with `yigraf supersede-intent`; a task's text is "
                  f"the checkbox line in the plan file.")
    path = memory.find_memory(repo, target)
    if path is None:
        _guidance(f"No memory node with id {target}. "
                  f'Find the one you mean with `yigraf context "<topic>"` or `yigraf show <id>`.')
    node = memory.read_memory(path)

    new_why = _why_text(why, why_file)
    new_rejected = _joined_rejected(rejected)
    fields = {"statement": statement if statement is not None else node.statement,
              "why": new_why if new_why is not None else node.why,
              "alternatives": new_rejected if new_rejected is not None else node.alternatives}
    if (fields["statement"], fields["why"], fields["alternatives"]) == (
            node.statement, node.why, node.alternatives):
        _guidance(f"nothing to amend on {target} — pass --statement, --why/--why-file or --rejected "
                  f"with the corrected text. To see what it currently says: `yigraf show {target}`.")

    # A retired belief's record is not worth re-keying: its successor carries the live claim, and the
    # supersedes edge pointing here is exactly the cascading reference below.
    if node.status == "superseded" or node.superseded_by:
        _guidance(f"{target} is superseded — its record is history now, and the live claim is "
                  f"{node.superseded_by or 'its successor'}. Amend that one instead; repairing a "
                  f"retired node would re-key it and break the trail that explains why it was retired.")

    blockers, back_refs = _amend_referrers(repo, target)
    if blockers:
        _guidance(f"{target} is named by {', '.join(blockers)}, so its record can't be repaired in "
                  f"place: amend re-keys the node (the id hashes the statement/why/rejected it would "
                  f"fix), and a referrer's own id hashes what it points at — the re-key would cascade "
                  f"through every one of them. Something has already built on this belief, so correct "
                  f"it additively: `yigraf supersede {target} \"<the claim, stated right>\"` keeps both "
                  f"readings and leaves those references intact.")

    # Append-only means never retractable: a pushed assertion is on other machines, and re-keying here
    # would mint a SECOND live node saying almost the same thing — which for a content-addressed family
    # arrives as a knowledge conflict, not a correction (extract._fold_replica). Only a KNOWN push
    # refuses; unknown or offline proceeds, since then no shared log can be contradicted.
    pushed = _pushed_ids(repo, config)
    if pushed is not None and target in pushed:
        _guidance(f"{target} has already been pushed to the shared log, and an append-only log has no "
                  f"retraction — amending it locally would mint a second node while teammates keep the "
                  f"one they pulled, surfacing as a knowledge conflict rather than a fix. Say it again "
                  f"properly instead: `yigraf supersede {target} \"<the claim, stated right>\"`.")

    # `amend` is the verb the hollow-why refusal recommends, so it is the one place a hollow --why must
    # not arrive through the back door. Last of the refusals on purpose: the three above say amend is
    # the wrong VERB here, and sending someone off to rewrite a --why for a node they cannot amend
    # would be guidance that does not lead anywhere.
    if new_why is not None:
        _hollow_why_guard(repo, config, new_why, list(node.supersedes) + list(node.pending_supersedes))

    new_id = memory.memory_id(
        node.type, fields["statement"], fields["why"], fields["alternatives"], list(node.serves),
        [c.sym for c in node.concerns], [e.ref for e in node.evidence], list(node.supersedes),
        rejected_valid_when=list(node.rejected_valid_when),
        rejected_invalidated_when=list(node.rejected_invalidated_when))
    changed = [name for name, value in
               (("statement", statement), ("why", new_why), ("rejected", new_rejected))
               if value is not None]

    # Splice rather than re-render: the body may carry hand-written prose the three markers do not
    # describe, and re-deriving it from the fields would delete that (memory._render_body refuses to).
    node.body = memory.splice_body(node.body or "", statement=statement, why=new_why,
                                   alternatives=new_rejected)
    node.statement, node.why, node.alternatives = (
        fields["statement"], fields["why"], fields["alternatives"])
    node.id = new_id
    node.slug = memory.slugify(fields["statement"])
    dest = memory.hashed_memory_path(repo, node.slug, new_id)
    node.source_file = f"memory/{dest.name}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(memory.render_memory(node), encoding="utf-8")
    if dest.resolve() != path.resolve():
        path.unlink()  # one record, one file: the old id is not a second live belief
    for ref in back_refs:  # the predecessor's forward stamp, re-pointed (never an identity — see above)
        predecessor = memory.read_memory(ref)
        predecessor.superseded_by = new_id
        ref.write_text(memory.render_memory(predecessor), encoding="utf-8")

    # The belief is the same one, so it keeps what it earned — upholds/usage are keyed by id and would
    # otherwise silently reset to zero, demoting a settled node for a typo fix (counters.apply_maturity).
    try:
        telemetry = counters.load_telemetry(repo)
        if target in telemetry:
            telemetry[new_id] = telemetry.pop(target)
            counters.telemetry_path(repo).write_text(json.dumps(telemetry, indent=2), encoding="utf-8")
    except (OSError, ValueError):
        pass  # a machine-local sidecar must never fail a write that already landed (design law #5)

    _rebuild(repo)
    typer.echo(f"Amended {target} ({' + '.join(changed)}) — now {new_id}. The belief, its anchors and "
               f"its history are unchanged, and no supersede was recorded; the id moved because it is "
               f"a hash of the text that was repaired."
               + (f" Re-pointed the superseded_by stamp on {len(back_refs)} predecessor(s)."
                  if back_refs else ""))


def _resolve_concerns(repo: Path, config: dict, graph, syms: list[str],
                      was_anchored: set[str] | None = None,
                      *, typed: bool = True) -> tuple[list[memory.Concern], list[str]]:
    """Resolve each ``--concerns`` locator to a :class:`Concern`, soft-warning on a forward-reference.

    A malformed locator (not ``sym:``/``file:``) is still a hard guide — that's a wrong *form*, not a
    forward-reference. But a well-formed locator that doesn't resolve in the current source is a
    legitimate forward-reference (a decision governing code about to be written), so we create a
    *dangling* concern (anchor ``None``) and return a warning instead of blocking (D#3). The edge is
    live and traversable now; ``reaffirm`` stamps its anchor once the code lands.

    ``was_anchored`` names the loci that were ALREADY anchored on the node this capture inherits from
    (``supersede``), and it selects a different warning — because the two states are opposite and the
    verbs that resolve them are disjoint (feedback-v4 #4). An unresolvable locus that was *never*
    anchored is a forward reference and ``reaffirm`` stamps it when the code lands. One that *was*
    anchored means the locus DIED between the two captures, and ``reaffirm`` is precisely the verb
    ``drift_tail`` already rules out there ("the locus is gone, so `reaffirm` can't re-anchor it").
    Sending the caller to it makes ``supersede`` a closed loop: the successor inherits the dead anchor,
    the hard-drift count stays at 1 and walks to the newest node, and every pass adds a false entry to
    the ``supersedes`` chain — the LOCUS-REPAIR-ONLY node ``reanchor`` was built to stop producing.
    """
    concerns: list[memory.Concern] = []
    warnings: list[str] = []
    was_anchored = was_anchored or set()
    for sym in syms:
        sym = _canonical_locus(repo, sym)  # `#Turning Radius` → `#turning-radius` (feedback-v5 B)
        if not (sym.startswith("sym:") or sym.startswith("file:")):
            _guidance(f"--concerns must be a symbol (sym:<path>#<name>), a file "
                      f"(file:<path>[:L<a>-L<b>], for infra/glue with no symbol) or a markdown "
                      f"section (file:<path>#<section>), got: {sym}")
        if sym.startswith("sym:") and "#" not in sym:
            _refuse_bare_sym(graph, sym, "--concerns")
        anchor, algo = _anchor(repo, config, sym, guide=typed)
        concerns.append(memory.Concern(sym=sym, anchor=anchor, anchor_algo=algo))
        if anchor is None and sym in was_anchored:
            warnings.append(f"⚠ {sym} was anchored on the belief this replaces and no longer resolves — "
                            f"the locus DIED, so the successor inherits hard drift and `reaffirm` "
                            f"cannot re-anchor it. Move it instead: `yigraf reanchor <this mem-id> "
                            f"{sym} <where it lives now>`." + _symbol_suggestion(graph, sym, repo))
        elif anchor is None:
            noun, lands = _locus_noun(sym)
            warnings.append(f"⚠ no such {noun} {sym} in the current source — creating a dangling "
                            f"concerns edge (it governs once {lands}; `reaffirm <mem-id>` to "
                            f"anchor it)." + _symbol_suggestion(graph, sym, repo))
    return concerns, warnings


def _resolve_evidence(repo: Path, config: dict, graph, refs: list[str]) -> tuple[list[memory.Evidence], list[str]]:
    """Resolve each ``--evidence`` ref to an :class:`Evidence` (int:memory-grounding).

    A ``sym:``/``file:`` ref is a *live repo locus* → stamp its drift anchor (like a concern), so the
    evidence changing surfaces as ``grounded_by`` drift; an unresolved one is a forward-reference
    (evidence about to land) → dangling anchor + a soft warning, exactly as ``--concerns`` does. Any
    other ref (``commit:<sha>``, a URL, free text) is *opaque*: recorded verbatim with no anchor — it
    never drifts (nothing in-repo to hash; a commit sha is immutable), so no warning either.
    """
    evidence: list[memory.Evidence] = []
    warnings: list[str] = []
    for ref in refs:
        ref = _canonical_locus(repo, ref)  # a typed heading canonicalizes to its slug (feedback-v5 B)
        if ref.startswith("sym:") or ref.startswith("file:"):
            if ref.startswith("sym:") and "#" not in ref:
                _refuse_bare_sym(graph, ref, "--evidence")
            anchor, algo = _anchor(repo, config, ref)
            evidence.append(memory.Evidence(ref=ref, anchor=anchor, anchor_algo=algo))
            if anchor is None:
                warnings.append(f"⚠ no such locus {ref} in the current source — creating a dangling "
                                f"grounded_by edge (it anchors once the evidence lands; "
                                f"`reaffirm <mem-id> --grounding empirical --evidence {ref}`)."
                                + _symbol_suggestion(graph, ref, repo))
        else:
            evidence.append(memory.Evidence(ref=ref))  # opaque (commit:/url/text) — no anchor, no drift
            warnings += _commit_evidence_note(repo, ref)
    return evidence, warnings


def _commit_evidence_note(repo: Path, ref: str) -> list[str]:
    """Say what a ``commit:<sha>`` citation actually resolves to — or that it resolves to nothing.

    ``commit:`` is deliberately *opaque* evidence: immutable, so it never drifts, so nothing downstream
    ever re-examines it. That is exactly why it was the one grounding ref accepted with no feedback at
    all, and the field's report is the consequence: a claim about what a human observed on one date was
    grounded in a record produced the day after, "accepted silently… it makes an unrelated artifact look
    like the basis for a claim" (feedback-v4 #16).

    yigraf cannot judge that — the observation's date lives in the prose, not in the graph — so it does
    the one thing that lets the *author* judge it while the capture is still cheap to redo: resolve the
    sha and show its date and subject. A wrong citation is usually obvious the moment its subject line
    is read next to the claim. An unresolvable sha is a stronger signal and gets its own line: a typo,
    or a sha from another clone. Both are warnings, never refusals — a commit may legitimately not be
    fetched yet, and evidence is captured as asserted (the ``--concerns`` forward-reference rule).
    """
    sha = ref[len("commit:"):].strip() if ref.startswith("commit:") else ""
    if not sha:
        return []
    # %cs is the committer date as YYYY-MM-DD — the field a plausibility question is actually asked in.
    shown = counters._git(repo, "show", "-s", "--format=%h %cs %s", f"{sha}^{{commit}}")
    if not shown or not shown.strip():
        return [f"⚠ --evidence {ref} doesn't resolve to a commit in this repo — a typo, an abbreviation "
                f"that no longer disambiguates, or a sha from another clone. It is captured as you "
                f"wrote it and will never drift or be re-checked, so nothing else will catch it."]
    return [f"↳ --evidence {ref} is {shown.strip()} — confirm that dates and reads like the observation "
            f"this claim rests on; a commit that merely mentions the topic is not evidence for it."]


def _resolve_governs(repo: Path, config: dict, graph, refs: list[str],
                     *, typed: bool = True) -> list[memory.Concern]:
    """Resolve each ``--governs`` locus to a POLICY concern (feedback-v3 #5): surfaces at the edit hook
    exactly like ``--concerns``, but carries no content hash and never drifts — for a belief about how
    a locus is *used* ("status.md holds only status"), where a content anchor rubber-stamps forever.

    The locus must exist NOW, unlike a concern's forward-reference: an unresolvable governs ref would
    land as dangling hard drift — the opposite of never-drifts — and a policy about nothing is a
    mis-capture. A line range is refused for the same reason a policy has no hash: it governs use, not
    a region's contents.
    """
    out: list[memory.Concern] = []
    for ref in refs:
        if not typed:
            # An INHERITED policy locus, not one this caller typed. A policy carries no hash either way,
            # so the guards below can only ever *block* — and a governed locus that has since died is
            # drift, not a mis-capture, so refusing the supersede that reacts to it is backwards. The
            # missing node makes the edge dangle and hard drift says it (see `_anchor`'s ``guide``).
            out.append(memory.Concern(sym=ref, anchor=None, anchor_algo=memory.GOVERNS_ALGO))
            continue
        ref = _canonical_locus(repo, ref)  # a typed heading canonicalizes to its slug (feedback-v5 B)
        if not (ref.startswith("sym:") or ref.startswith("file:")):
            _guidance(f"--governs must be sym:<path>#<name>, file:<path> or file:<path>#<section>, got: {ref}")
        if ref.startswith("sym:"):
            if "#" not in ref:
                _refuse_bare_sym(graph, ref, "--governs")
            if symbol_content_hash(repo, ref, config) is None:
                _guidance(f"no such symbol {ref} in the current source — a policy governs a locus "
                          f"that exists." + _symbol_suggestion(graph, ref, repo))
        else:
            relpath, start, _end = parse_file_target(ref)
            slug = parse_section_target(ref)[1]
            if start is not None:
                _guidance(f"--governs takes a whole file or a #<section>, not a line range (got {ref}) "
                          f"— a policy governs how a locus is used, so there is no region to pin.")
            if not (Path(repo) / relpath).is_file():
                _guidance(f"no such file {relpath} — a policy governs a locus that exists.")
            if slug is not None:
                # A named section IS a locus a policy can govern ("this section holds only status"),
                # unlike a line range: it is addressed by name, not by position. It must resolve now,
                # for the reason every --governs ref must — a policy about nothing is a mis-capture.
                _guide_section_locus(repo, config, relpath, slug)
                if locus_hash(repo, ref)[0] is None:
                    _guidance(f"no section {ref} — a policy governs a locus that exists."
                              + _section_suggestion(repo, ref))
        out.append(memory.Concern(sym=ref, anchor=None, anchor_algo=memory.GOVERNS_ALGO))
    return out


def _serves_warnings(graph, serves: list[str]) -> list[str]:
    """Soft-warn on a ``--serves`` id absent from the graph — a dangling edge, never a block (D#3)."""
    return [f"⚠ no such node {t} — creating a dangling serves edge (a forward-reference is fine; it "
            f"resolves when the intent/plan is created)." for t in serves if t not in graph]


def _dedup_guard(repo: Path, config: dict, graph, statement: str, why: str,
                 concerns: list[memory.Concern], serves: list[str]) -> None:
    """Advisory write-time near-duplicate check (capture-flow §4); no-op without an embedding backend.

    Asks the index for the most similar *active* memory node sharing a serves/concerns target; over the
    ``dup_cosine`` threshold ⇒ refuse (point at it; suggest supersede or ``--new``). Cheap when there's
    no backend (returns immediately) — dedup is then trivially skipped. Reuses the caller's ``graph``.
    """
    text = statement + (f"\n{why}" if why else "")
    scope = set(serves) | {c.sym for c in concerns}
    hit = embeddings.most_similar_memory(repo, graph, config, text, scope)
    threshold = config.get("embeddings", {}).get("dup_cosine", 0.9)
    if hit and hit[1] >= threshold:
        _guidance(
            f"This looks like a near-duplicate of {hit[0]} (cosine {hit[1]:.2f}). "
            f"If you're changing your mind, `yigraf supersede {hit[0]} \"<new>\"`; "
            f"otherwise re-run with --new to capture it anyway."
        )


def _hollow_why_guard(repo: Path, config: dict, why: str, supersedes: list[str]) -> None:
    """Refuse a ``--why`` that only POINTS at an argument nobody ever wrote (feedback-v5 amendment).

    A deferring ``--why`` — *"the belief is unchanged and the argument is in the node this
    supersedes"* — is a promise the store has no way to keep. Nothing checked that the target carried
    an argument, and by the time a reader follows the pointer the only way to find out is archaeology:
    in the field, four such pointers all resolved to nodes whose entire body was a single statement
    line. **The trail was load-bearing and empty at the same time, and ``--why`` was the field that was
    supposed to prevent that.** Catching it at creation costs one lookup; catching it as the field did
    costs a session years later, by which time the argument exists nowhere.

    Silent when the argument is really there (design law #4): a ``--why`` may cite a node freely, and
    deferring to a node that argues its case is legitimate shorthand — only a pointer that bottoms out
    in nothing is refused. A supersede gets a second sentence, because a supersede whose ``--why`` says
    the belief is *unchanged* is not a mind-change at all: it is the locus repair ``reanchor`` exists
    for, filed under the verb that writes a false entry in the supersedes trail.
    """
    max_words = config.get("hollow_why_words", 25)
    found = memory.deferral_verdict(repo, why, supersedes, max_words=max_words)
    if found is None:
        return
    _target, verdict, chain = found
    end = chain[-1]
    lands = {
        "missing": f"no node {end} exists",
        "archived": f"{end} is archived — `gc` moved it out of the active graph",
        "hollow": f"{end} carries no --why of its own",
        "loop": f"{end} defers back to a node that defers here",
    }[verdict]
    _guidance(
        f"this --why argues nothing — it defers to {' → '.join(chain)}, and {lands}, so a reader "
        f"following the pointer lands on nothing. Nothing else will ever check this, which is why it "
        f"is checked here: write the argument into the --why you are composing now."
        + (f" If it belongs on {end} instead, `yigraf amend {end} --why \"<the argument>\"` puts it "
           f"there — no supersedes trail, no re-stated belief."
           if verdict in ("hollow", "loop") else "")
        + (" And a supersede whose --why says the belief is UNCHANGED is not a mind-change: that is a "
           "locus repair, and `yigraf reanchor <mem:id> <old-locus> <new-locus>` moves the anchor "
           "without writing a false entry into the supersedes trail." if supersedes else "")
        + f" (config: hollow_why_words: 0 turns this off.)")


def _premise_already_holds(repo: Path, graph, ref: str) -> bool:
    """Does a rejection premise hold at CAPTURE time? (:func:`retrieval.premise_holds`, pre-build.)

    Read-time liveness is the graph's answer, but capture runs against the graph as it was BEFORE this
    artifact existed — and a ``file:`` node outside an extractable language (``console.html``,
    ``redis.tf``, a Dockerfile) is projected only by the references to it, including this very
    capture's. Asking that graph would report every such premise absent, i.e. never warn on the one
    mis-fill this check exists to catch. So for a ``file:`` ref, ask the filesystem instead — files are
    truth (design law #6), and ``astnorm.locus_hash`` already resolves the ``:L<a>-L<b>`` region and
    ``#<section>`` forms.
    Every other family (``int:``/``mem:``/``sym:``) is projected independently of who points at it.
    """
    if ref.startswith("file:"):
        return locus_hash(repo, ref)[0] is not None
    return retrieval.premise_holds(graph, ref)


def _capture_memory(repo: Path, workspace: Path, *, statement: str, type_: str, why: str,
                    serves: list[str], concern_syms: list[str], rejected: str | None,
                    supersedes: list[str], promotable: bool, force_new: bool = False,
                    grounding: str | None = None, evidence_refs: list[str] | None = None,
                    pending_supersedes: list[str] | None = None,
                    rejected_valid_when: list[str] | None = None,
                    rejected_invalidated_when: list[str] | None = None,
                    pinned: bool = False,
                    governs_refs: list[str] | None = None,
                    was_anchored: set[str] | None = None,
                    typed_loci: bool = True,
                    provenance: dict | None = None) -> memory.Memory:
    """Write a new memory artifact, then re-materialize the view. Shared by remember/supersede/note-constraint.

    ``provenance`` (default agent-asserted ``{"source": "cli"}``) drives the *landed* maturity tier
    (:func:`yigraf.memory.landing_maturity`, task #1): an agent ``remember`` lands ``working``; the
    miner / review bridge pass ``{"source": "mined"|"review"}`` to land a ``proposed`` candidate."""
    if type_ not in memory.MEMORY_TYPES:
        _guidance(f"--type must be one of {', '.join(memory.MEMORY_TYPES)} (got {type_}).")
    grounding = grounding or memory.DEFAULT_GROUNDING
    if grounding not in memory.GROUNDINGS:
        _guidance(f"--grounding must be one of {', '.join(memory.GROUNDINGS)} (got {grounding}). "
                  f"inferred = a reasoned assertion; docs = distilled from written rationale; "
                  f"empirical = confirmed by a live observation (a spike/test/prod signal).")
    evidence_refs = evidence_refs or []
    # The empirical tier is a claim about a live observation — it must NAME the observation, or it's
    # just an assertion dressed as evidence (int:memory-grounding; mem:032 'silence is not evidence').
    if grounding == "empirical" and not evidence_refs:
        _guidance("--grounding empirical means confirmed by a live observation — name what confirmed "
                  "it with --evidence sym:<path>#<test> | file:<path> | commit:<sha> | <url> "
                  "(repeatable). If it's a reasoned assertion rather than an observation, use "
                  "--grounding inferred (the default). "
                  # Refused before any build, so this costs no work — but it does cost the caller the
                  # --why it just composed, which is the actual expense the field filed (v4 #15).
                  "Re-sending a long --why to clear this? Put it in a file and pass --why-file "
                  "<path> — then a refusal costs a path, not the argument.")
    pending_supersedes = pending_supersedes or []
    rejected_valid_when = rejected_valid_when or []
    rejected_invalidated_when = rejected_invalidated_when or []
    provenance = provenance or {"source": "cli"}

    # Applicability premises condition a rejection (task 3), so they only make sense alongside one, and
    # each must be a locator yigraf can evaluate the liveness of — not prose (retrieval.premise_holds).
    premises = rejected_valid_when + rejected_invalidated_when
    if premises and not rejected:
        _guidance("--rejected-valid-when / --rejected-invalidated-when condition WHEN a rejected "
                  "alternative still applies — pass --rejected \"<the ruled-out option + why>\" too, "
                  "or drop the premises.")
    bad = [p for p in premises if not p.startswith(("int:", "mem:", "sym:", "file:"))]
    if bad:
        _guidance(f"a rejection premise must be a graph locator yigraf can evaluate the liveness of — "
                  f"int:<slug> | mem:<id> | sym:<path>#<name> | file:<path> (got: {', '.join(bad)}). "
                  f"valid-when = surfaces only while the premise holds; invalidated-when = withdrawn "
                  f"once it holds (e.g. --rejected-invalidated-when file:infra/redis.tf).")

    # serves works toward a GOAL — an intent or plan node (relations grammar). Unlike --concerns, which
    # _resolve_concerns prefix-checks, --serves was only existence-warned, so a wrong-typed target
    # (--serves sym:foo, a memory id, …) would silently land an ill-typed edge. A wrong *form* is a hard
    # guide (exit 0, design law #1), distinct from the soft dangling-warning for a not-yet-created goal.
    mistyped = [t for t in serves if not relations.well_typed_ids("serves", "mem:_", t)]
    if mistyped:
        _guidance(f"--serves points at the goal a decision works toward — an intent (int:<slug>) or a "
                  f"plan (plan:<slug>), not {', '.join(mistyped)}. To pin a decision to the code it "
                  f"governs use --concerns sym:<path>#<name>.")

    config = load_config(workspace / "config.yaml")
    # Before the build, like the empirical-grounding refusal above: a --why that only points somewhere
    # costs nothing to reject, and rejecting it costs the caller one short sentence to rewrite.
    _hollow_why_guard(repo, config, why, list(supersedes) + list(pending_supersedes))
    graph, _ = build_graph(repo, config)  # built once, reused for concern/serves resolution + dedup
    concerns, warnings = _resolve_concerns(repo, config, graph, concern_syms, was_anchored,
                                           typed=typed_loci)
    concerns += _resolve_governs(repo, config, graph, governs_refs or [], typed=typed_loci)
    evidence, ev_warnings = _resolve_evidence(repo, config, graph, evidence_refs)
    warnings += ev_warnings
    warnings += _serves_warnings(graph, serves)
    # A valid-when premise that doesn't resolve NOW would hide the rejection until it does — usually a
    # typo. Soft-warn only (D#3): the edge is still captured. Asked of the SAME oracle as its sibling
    # below (feedback-v4 #8): this half asked bare graph membership, so a `file:` premise outside an
    # extractable language warned "typo?" on the first capture for that path and never again — an
    # artifact of projection order, not of store state, and false besides (`show` reported the premise
    # holding right after). `_premise_already_holds` carries the reason, and it always applied to both.
    warnings += [f"⚠ --rejected-valid-when {p} doesn't resolve to a known node — the rejection stays "
                 f"hidden until it does (a typo, or a path that exists but isn't indexed?)."
                 for p in rejected_valid_when if not _premise_already_holds(repo, graph, p)]
    # The mirror failure, and the more expensive one, because it is silent in the other direction: an
    # invalidated-when premise legitimately names something NOT YET true (that's the point) — but one
    # that ALREADY holds withdraws the rejection from the moment of capture, so the clause is born
    # invisible and no later event can reveal it. Measured in the field on `--rejected-invalidated-when
    # file:<a file that already exists>`: a locator is not a condition unless it can still become true.
    warnings += [f"⚠ --rejected-invalidated-when {p} ALREADY holds — the rejection is withdrawn from "
                 f"the moment of capture and will never surface. Name the condition that would RETIRE "
                 f"it (something not true yet), or drop the premise and let the rejection stand."
                 for p in rejected_invalidated_when if _premise_already_holds(repo, graph, p)]
    # A supersede (applied or pending) is a deliberate mind-change → skip the near-duplicate guard.
    if not supersedes and not pending_supersedes and not force_new:
        _dedup_guard(repo, config, graph, statement, why, concerns, serves)
    slug = memory.slugify(statement)
    # Content-addressed id (memid-v1, mem:063): coordinator-free, so no racy next_seq — and two agents
    # who assert the same decision mint the same id and collapse on merge (int:concurrent-write-model).
    mem_id = memory.memory_id(type_, statement, why, rejected, list(serves),
                              [c.sym for c in concerns], [e.ref for e in evidence], list(supersedes),
                              rejected_valid_when=rejected_valid_when,
                              rejected_invalidated_when=rejected_invalidated_when)
    dest = memory.hashed_memory_path(repo, slug, mem_id)
    node = memory.Memory(
        id=mem_id, seq=0, slug=slug, type=type_, statement=statement, why=why,
        alternatives=rejected, rejected_valid_when=list(rejected_valid_when),
        rejected_invalidated_when=list(rejected_invalidated_when),
        serves=list(serves), concerns=concerns, evidence=evidence,
        supersedes=list(supersedes), pending_supersedes=list(pending_supersedes),
        grounding=grounding, promotable=promotable, pinned=pinned, provenance=provenance,
        maturity=memory.landing_maturity(provenance),  # proposed for mined/review, else working (task #1)
        source_file=f"memory/{dest.name}",
    )
    dest.parent.mkdir(parents=True, exist_ok=True)  # a bare workspace (memory/ unscaffolded) passes _require_workspace
    dest.write_text(memory.render_memory(node), encoding="utf-8")
    _rebuild(repo)
    for w in warnings:  # soft-warn AFTER capture — the edge is written; these guide, never block (D#3)
        # The id exists by now, so the placeholders these were composed with get filled: printing a
        # literal `<mem-id>` one line before minting the id is a command the reader cannot run (v4 #4).
        typer.echo(w.replace("<this mem-id>", node.id).replace("<mem-id>", node.id))
    return node


def _offer_ledger(root: Path) -> Path:
    """The machine-local ledger of section offers *considered* (``yigraf/.local/section-offers.json``).

    Volatile, gitignored, never the graph — the same rule that keeps usage/last_seen out of the
    projection (design law #6), and the same shape as :func:`_reaffirm_ledger`.

    It exists because the offer was the one guidance surface with no record, and the number that should
    set ``section_offer_margin`` — how often an offer is *right* — is uncollectable without one
    (feedback-v7 G#4). A snapshot of a store can say how many whole-file anchors *could* have been
    narrowed; it cannot attribute a section anchor to the offer that suggested it, and the suppressed
    cases leave no trace at all. Two of yigraf's own design choices make that airtight: ``reanchor``
    writes no supersedes edge, and a ``concerns`` entry carries no timestamp, so nothing in the artifact
    dates a narrowing.

    A row is written for **every** whole-file markdown anchor considered, carrying both scores, *before*
    the margin gate — a row written where the offer is printed would log only what the margin let
    through, which is exactly the half that cannot re-fit a threshold. With ``top``/``runner_up`` stored,
    one window re-scores offline at every candidate margin (``sectionfit.Fit.wins_by``). Acceptance needs
    no second record: it is "does that memory now carry that anchor".
    """
    return Path(root) / WORKSPACE_DIRNAME / ".local" / "section-offers.json"


def _record_offer(root: Path, mem_id: str, ref: str, fit: sectionfit.Fit, offered: bool) -> None:
    """Append one considered offer, keeping the last 500. Silent on any I/O failure (design law #5)."""
    try:
        path = _offer_ledger(root)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = []
        entries = [e for e in data if isinstance(e, dict)][-499:] if isinstance(data, list) else []
        entries.append({"at": time.time(), "mem": mem_id, "ref": ref, "candidate": fit.candidate,
                        "top": round(fit.top, 6), "runner_up": round(fit.runner_up, 6),
                        "offered": offered})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries), encoding="utf-8")
    except OSError:
        pass


def _section_offers(node: memory.Memory, repo: Path | None, config: dict | None) -> list[str]:
    """Offer the ``#section`` a whole-file markdown anchor is probably about. An OFFER, never a warning.

    The field measured its store for a rule that separates a legitimate whole-file anchor from one that
    should have been a section, and got a null: nothing beats "warn unconditionally", which is right
    two times in three — i.e. a mark the agent correctly learns to ignore. An offer needs no such rule.
    On a claim that really is about the document the reader sees one line, sees it is not what they
    meant, and keeps what they have: no ⚠, nothing to clear, no training signal. Their mechanical
    version of exactly this named a plausible home for 19 of 25 mis-anchored items (feedback-v6 §7).

    Capture time is the only honest moment for it: the anchor is a *choice*, and it is being made now.
    :mod:`yigraf.sectionfit` stays silent unless one section wins clearly, so most captures print
    nothing (design law #4). ``--governs`` is exempt — a policy anchor deliberately names the file it
    governs the use of, and narrowing it would change what the policy covers.

    Every anchor *considered* is recorded (:func:`_record_offer`), including the ones the margin
    suppresses, because those are the half that can re-fit the threshold later (feedback-v7 G#4).
    """
    if repo is None:
        return []
    margin = float((config or {}).get("section_offer_margin") or 0)
    if margin <= 0:
        return []
    out: list[str] = []
    seen: set[str] = set()
    anchors = ([(c.sym, c.anchor_algo) for c in node.concerns]
               + [(e.ref, e.anchor_algo) for e in node.evidence])
    carried = {ref for ref, _ in anchors}
    for ref, algo in anchors:
        # Whole-file only: a `#section` is already the narrow form and a `:L` range is addressed by
        # position, which no heading can name.
        if ref in seen or (algo or "") == memory.GOVERNS_ALGO:
            continue
        if not ref.startswith("file:") or "#" in ref or ":L" in ref:
            continue
        seen.add(ref)
        fit = sectionfit.section_fit(repo, ref[len("file:"):], node.statement)
        # The node ALREADY carrying the section we would name is the fifth exemption, and the one that
        # was missing: the `reanchor` we hand over cannot move an anchor onto a locus that is already
        # there, so it drops the whole-file anchor instead — a removal, and until feedback-v7 G#3 one
        # reported as a move. The offer is the likeliest way to meet that branch, so it stops here —
        # before the ledger too, because this is not a candidate the margin could ever be right about,
        # and a row whose `offered` disagreed with its own scores would poison the re-fit.
        if fit.candidate is not None and f"{ref}#{fit.candidate}" in carried:
            continue
        offered = fit.wins_by(margin)
        _record_offer(repo, node.id, ref, fit, offered)
        if not offered:
            continue
        out.append(f"↳ Offer (not drift — nothing to clear): {ref} is anchored whole-file, and "
                   f"#{fit.candidate} reads like this claim's subject.")
        out.append(f"  Narrow it with `yigraf reanchor {node.id} {ref} {ref}#{fit.candidate}`, or keep "
                   f"the whole-file anchor if the claim really is about the whole document.")
    return out


def _report_capture(node: memory.Memory, repo: Path | None = None,
                    config: dict | None = None) -> None:
    """The one-line capture echo — the moment a mis-filled locator is cheap to catch.

    ``governs`` is reported under its own label (feedback-v4 #10): calling a policy anchor ``concerns``
    hid the distinction at the only moment it is correctable, and on a ``supersede`` the echo and the
    inheritance line ("Carried 1 governs from …") printed together and disagreed about the same edge.
    """
    bits = [f"type={node.type}"]
    if node.serves:
        bits.append("serves " + ", ".join(node.serves))
    regular = [c.sym for c in node.concerns if (c.anchor_algo or "") != memory.GOVERNS_ALGO]
    policy = [c.sym for c in node.concerns if (c.anchor_algo or "") == memory.GOVERNS_ALGO]
    if regular:
        bits.append("concerns " + ", ".join(regular))
    if policy:
        bits.append("governs " + ", ".join(policy))
    if node.supersedes:
        bits.append("supersedes " + ", ".join(node.supersedes))
    if node.pinned:
        bits.append("pinned")
    typer.echo(f"Captured {node.id} ({'; '.join(bits)})")
    for line in _section_offers(node, repo, config):
        typer.echo(line)


#: Shared help for the ``--governs`` capture flag — one wording, three capture verbs.
_GOVERNS_HELP = ("A locus this belief governs the USE of (repeatable): surfaces at the edit hook like "
                 "--concerns but carries no content hash, so it never drifts — for a policy like "
                 "'status.md holds ONLY status', where a content anchor would demand a reaffirm on "
                 "every edit that obeys it. sym:<path>#<name>, file:<path> or file:<path>#<section>; "
                 "must exist. Not a line range — that is addressed by position, not by name.")

#: Shared help for the ``--pin`` capture flag and the ``pin`` verb — one wording, three surfaces.
_PIN_HELP = ("Inject this belief IN FULL at every SessionStart, whatever the session turns out to be "
             "about. For the few rules that are load-bearing on EVERY task; the budget binds, so a "
             "repo that pins everything pins nothing.")


@app.command()
def remember(
    statement: str = typer.Argument(..., help="The claim in one line (the H2 heading)."),
    type: str = typer.Option("decision", "--type", help=f"One of: {', '.join(memory.MEMORY_TYPES)}."),
    why: str = typer.Option("", "--why", help="The reasoning (ReCAP's T) — what /clear loses."),
    why_file: Path = typer.Option(None, "--why-file", help=_WHY_FILE_HELP),
    serves: list[str] = typer.Option(None, "--serves", help="An intent/plan id this serves (repeatable)."),
    concerns: list[str] = typer.Option(None, "--concerns", help="The locus this governs: sym:<path>#<name>, file:<path>[:L<a>-L<b>] or — in markdown — file:<path>#<section> (repeatable, anchored)."),
    governs: list[str] = typer.Option(None, "--governs", help=_GOVERNS_HELP),
    rejected: list[str] = typer.Option(None, "--rejected", help="The rejected alternative + why (the most perishable content) (repeatable — joined with ' || ')."),
    rejected_valid_when: list[str] = typer.Option(None, "--rejected-valid-when", help="A premise the rejection depends on: int:<slug> | mem:<id> | sym:<path>#<name> | file:<path> (repeatable). The rejection surfaces ONLY while every one of these still holds."),
    rejected_invalidated_when: list[str] = typer.Option(None, "--rejected-invalidated-when", help="A condition that WITHDRAWS the rejection once true (same locator forms, repeatable), e.g. --rejected \"no Redis in deploy\" --rejected-invalidated-when file:infra/redis.tf."),
    grounding: str = typer.Option(None, "--grounding", help=f"How the belief is grounded: {' | '.join(memory.GROUNDINGS)} (default inferred). empirical = confirmed by a live observation."),
    evidence: list[str] = typer.Option(None, "--evidence", help="What grounds the belief (required for --grounding empirical): sym:<path>#<test> | file:<path> (drift-checked) | commit:<sha> | <url> (repeatable)."),
    new: bool = typer.Option(False, "--new", help="Capture even if it looks like a near-duplicate (skip the dedup guard)."),
    pin: bool = typer.Option(False, "--pin", help=_PIN_HELP),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Capture a decision/rationale/learned-fact as a memory node (serves an intent, concerns code)."""
    workspace = _require_workspace(repo)
    node = _capture_memory(repo, workspace, statement=statement, type_=type,
                           why=_why_text(why, why_file) or "",
                           serves=serves or [], concern_syms=concerns or [],
                           rejected=_joined_rejected(rejected),
                           supersedes=[], promotable=False, force_new=new, grounding=grounding,
                           evidence_refs=evidence or [], rejected_valid_when=rejected_valid_when or [],
                           rejected_invalidated_when=rejected_invalidated_when or [], pinned=pin,
                           governs_refs=governs or [])
    _report_capture(node, repo, load_config(workspace / "config.yaml"))


@app.command(name="note-constraint")
def note_constraint(
    rule: str = typer.Argument(..., help="The constraint in one line."),
    concerns: list[str] = typer.Option(None, "--concerns", help="The locus this constrains: sym:<path>#<name>, file:<path>[:L<a>-L<b>] or — in markdown — file:<path>#<section> (repeatable, anchored)."),
    governs: list[str] = typer.Option(None, "--governs", help=_GOVERNS_HELP),
    why: str = typer.Option("", "--why", help="Why the constraint holds (optional)."),
    why_file: Path = typer.Option(None, "--why-file", help=_WHY_FILE_HELP),
    serves: list[str] = typer.Option(None, "--serves", help="An intent/plan id this serves (repeatable)."),
    rejected: list[str] = typer.Option(None, "--rejected", help="The ruled-out alternative + why (a constraint often exists *because* one was rejected) (repeatable — joined with ' || ')."),
    rejected_valid_when: list[str] = typer.Option(None, "--rejected-valid-when", help="A premise the rejection depends on: int:<slug> | mem:<id> | sym:<path>#<name> | file:<path> (repeatable). The rejection surfaces ONLY while every one of these still holds."),
    rejected_invalidated_when: list[str] = typer.Option(None, "--rejected-invalidated-when", help="A condition that WITHDRAWS the rejection once true (same locator forms, repeatable)."),
    grounding: str = typer.Option(None, "--grounding", help=f"How the belief is grounded: {' | '.join(memory.GROUNDINGS)} (default inferred). empirical = confirmed by a live observation."),
    evidence: list[str] = typer.Option(None, "--evidence", help="What grounds the constraint (required for --grounding empirical): sym:<path>#<test> | file:<path> (drift-checked) | commit:<sha> | <url> (repeatable)."),
    new: bool = typer.Option(False, "--new", help="Capture even if it looks like a near-duplicate (skip the dedup guard)."),
    pin: bool = typer.Option(False, "--pin", help=_PIN_HELP),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Capture a constraint memory (flagged promotable to an enforced check; capture-flow §0a)."""
    workspace = _require_workspace(repo)
    node = _capture_memory(repo, workspace, statement=rule, type_="constraint",
                           why=_why_text(why, why_file) or "",
                           serves=serves or [], concern_syms=concerns or [],
                           rejected=_joined_rejected(rejected),
                           supersedes=[], promotable=True, force_new=new, grounding=grounding,
                           evidence_refs=evidence or [], rejected_valid_when=rejected_valid_when or [],
                           rejected_invalidated_when=rejected_invalidated_when or [], pinned=pin,
                           governs_refs=governs or [])
    _report_capture(node, repo, load_config(workspace / "config.yaml"))


@app.command()
def pin(
    target: str = typer.Argument(..., help="A memory id (mem:<id>) to inject at every SessionStart."),
    off: bool = typer.Option(False, "--off", help="Unpin instead: drop it back to relevance-ranked retrieval."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Mark a belief for unconditional SessionStart injection — the tier relevance cannot reach.

    Ranking answers "what is relevant to this topic?", which is the right question for a query and the
    wrong one for orientation. A rule the agent needs on *every* task ("never write this vendor's APIs
    from memory — grep the pinned refs") resembles no particular task, so it loses every cut no matter
    how it is worded; and a belief the agent has never heard of is a query it cannot formulate. Pinning
    is the escape hatch for the first case, and it is deliberately narrow — routing, not a claim, so it
    changes nothing about what the memory asserts and never re-identifies the node.

    Keep it scarce. ``session_start.pinned_budget`` binds and drops the lowest-standing pins loudly,
    because a session-start block that grows without limit is the same wallpaper the per-edit channel
    became. Everything else stays reachable through the titles manifest and ``yigraf context``.
    """
    _require_workspace(repo)
    if not target.startswith("mem:"):
        _guidance(f"pin takes a memory id (mem:<id>), got: {target}. Intents and active plans already "
                  f"seed SessionStart unconditionally — only a decision needs pinning.")
    path = memory.find_memory(repo, target)
    if path is None:
        _guidance(f'No memory node with id {target} to pin. Find it with `yigraf context "<topic>"`, '
                  f"or read one by id with `yigraf show <id>`.")
    node = memory.read_memory(path)
    if node.pinned == (not off):
        _guidance(f"{target} is already {'unpinned' if off else 'pinned'} — nothing to do.")
    if not off:
        # Refuse a superseded belief (feedback-v3 #7): the render correctly excludes non-live nodes, so
        # this pin would report success and inject nothing, ever — the worst kind of write. The
        # successor is in hand (its `supersedes` names the target), so the refusal points at it.
        # Artifact-side scan, because pre-1.5 predecessors may still read `status: active` (#8).
        successor = node.superseded_by or next(
            (m.id for m in memory.iter_memories(repo) if target in m.supersedes), None)
        if node.status != "active" or successor:
            _guidance(f"{target} is superseded{f' by {successor}' if successor else ''} — a non-live "
                      f"belief is never injected, so pinning it would silently do nothing. "
                      + (f"Pin the successor instead: `yigraf pin {successor}`."
                         if successor else f"Read it with `yigraf show {target}` to find the successor."))
    node.pinned = not off
    path.write_text(memory.render_memory(node), encoding="utf-8")
    _rebuild(repo)
    if off:
        typer.echo(f"Unpinned {target} — it is back to relevance-ranked retrieval.")
        return
    typer.echo(f"Pinned {target} — SessionStart now injects it in full, every session. "
               f"Keep the set small: `yigraf pin <id> --off` to retire one.")


@app.command()
def propose(
    statement: str = typer.Argument(..., help="The candidate belief in one line (a review anti-pattern, or a distilled decision)."),
    from_: str = typer.Option(..., "--from", help=f"Where the candidate came from: {' | '.join(sorted(memory.PROPOSED_SOURCES))}. Both LAND at the `proposed` tier."),
    type: str = typer.Option(None, "--type", help=f"One of: {', '.join(memory.MEMORY_TYPES)} (default: constraint for review, decision for mined)."),
    concerns: list[str] = typer.Option(None, "--concerns", help="The locus this candidate governs: sym:<path>#<name>, file:<path>[:L<a>-L<b>] or — in markdown — file:<path>#<section> (repeatable, anchored — this is what re-surfaces it at the edit hook)."),
    governs: list[str] = typer.Option(None, "--governs", help=_GOVERNS_HELP),
    rejected: list[str] = typer.Option(None, "--rejected", help="The anti-pattern (review) / rejected alternative (mined) — the ruled-out shape the finding warns against (repeatable — joined with ' || ')."),
    rejected_valid_when: list[str] = typer.Option(None, "--rejected-valid-when", help="A premise the rejection depends on: int:<slug> | mem:<id> | sym:<path>#<name> | file:<path> (repeatable). The rejection surfaces ONLY while every one of these still holds."),
    rejected_invalidated_when: list[str] = typer.Option(None, "--rejected-invalidated-when", help="A condition that WITHDRAWS the rejection once true (same locator forms, repeatable)."),
    why: str = typer.Option("", "--why", help="The reasoning behind the candidate (optional)."),
    why_file: Path = typer.Option(None, "--why-file", help=_WHY_FILE_HELP),
    serves: list[str] = typer.Option(None, "--serves", help="An intent/plan id this serves (repeatable)."),
    origin: str = typer.Option(None, "--origin", help="Free-text provenance detail for the audit trail, e.g. 'security-review', 'commit abc123', 'docs/DESIGN.md'."),
    grounding: str = typer.Option(None, "--grounding", help=f"How the belief is grounded: {' | '.join(memory.GROUNDINGS)} (default inferred)."),
    evidence: list[str] = typer.Option(None, "--evidence", help="What grounds the candidate (required for --grounding empirical): sym:<path>#<test> | file:<path> (drift-checked) | commit:<sha> | <url> (repeatable)."),
    new: bool = typer.Option(False, "--new", help="Capture even if it looks like a near-duplicate (skip the dedup guard)."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Land a distilled *candidate* memory at the `proposed` tier (the review bridge + knowledge miner).

    A `proposed` node carries near-zero retrieval weight and does NOT pollute a topic query — but,
    anchored via `--concerns` to a locus, it re-surfaces at the edit hook the next time that code is
    touched (int:review-compound), and a real encounter there confirms it up to `working`. Distilling
    the finding/rationale into one line is YOUR job (an LLM task); this verb only persists it with the
    provenance that lands it in quarantine. Over-proposing is safe — an un-encountered candidate expires.
    """
    workspace = _require_workspace(repo)
    if from_ not in memory.PROPOSED_SOURCES:
        _guidance(f"--from must be one of {', '.join(sorted(memory.PROPOSED_SOURCES))} (got {from_}). "
                  f"review = a confirmed code-/security-review finding; mined = distilled from commit "
                  f"rationale, PR discussion, or repo docs.")
    type_ = type or ("constraint" if from_ == "review" else "decision")
    provenance = {"source": from_}
    if origin:
        provenance["origin"] = origin
    node = _capture_memory(repo, workspace, statement=statement, type_=type_,
                           why=_why_text(why, why_file) or "",
                           serves=serves or [], concern_syms=concerns or [],
                           rejected=_joined_rejected(rejected),
                           supersedes=[], promotable=(type_ == "constraint"), force_new=new,
                           grounding=grounding, evidence_refs=evidence or [], provenance=provenance,
                           rejected_valid_when=rejected_valid_when or [],
                           rejected_invalidated_when=rejected_invalidated_when or [],
                           governs_refs=governs or [])  # the 4th capture verb was the one missed (v4 #11)
    _report_capture(node, repo, load_config(workspace / "config.yaml"))


@app.command()
def supersede(
    old_id: str = typer.Argument(..., help="The memory id being superseded, e.g. mem:001."),
    statement: str = typer.Argument(..., help="The new claim in one line."),
    type: str = typer.Option(None, "--type", help=f"One of: {', '.join(memory.MEMORY_TYPES)} (default: inherited from the superseded node)."),
    why: str = typer.Option("", "--why", help="Why the mind changed."),
    why_file: Path = typer.Option(None, "--why-file", help=_WHY_FILE_HELP),
    serves: list[str] = typer.Option(None, "--serves", help="An intent/plan id this serves (repeatable; default: inherited from the superseded node)."),
    concerns: list[str] = typer.Option(None, "--concerns", help="A symbol this governs (repeatable, anchored; default: inherited from the superseded node)."),
    governs: list[str] = typer.Option(None, "--governs", help=_GOVERNS_HELP + " Default: inherited from the superseded node."),
    rejected: list[str] = typer.Option(None, "--rejected", help="The rejected alternative + why (repeatable — joined with ' || ')."),
    rejected_valid_when: list[str] = typer.Option(None, "--rejected-valid-when", help="A premise the rejection depends on: int:<slug> | mem:<id> | sym:<path>#<name> | file:<path> (repeatable). The rejection surfaces ONLY while every one of these still holds."),
    rejected_invalidated_when: list[str] = typer.Option(None, "--rejected-invalidated-when", help="A condition that WITHDRAWS the rejection once true (same locator forms, repeatable)."),
    grounding: str = typer.Option(None, "--grounding", help=f"How the new belief is grounded: {' | '.join(memory.GROUNDINGS)} (default inferred)."),
    evidence: list[str] = typer.Option(None, "--evidence", help="What grounds the new belief (required for --grounding empirical): sym:<path>#<test> | file:<path> (drift-checked) | commit:<sha> | <url> (repeatable)."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Record a mind-change: a new memory node with a supersedes edge to the old one (never edit-in-place)."""
    workspace = _require_workspace(repo)
    if old_id.startswith("int:"):  # wrong verb for an intent reversal — hand them the right recipe (D#5)
        _guidance(f"{old_id} is an intent, not a memory — `supersede` reverses a *decision*. To reverse "
                  f"an intent's contract, use `yigraf supersede-intent {old_id[len('int:'):]} <new-slug> "
                  f'-s "<new SHALL/MUST>" --why "<why the premise changed>"`.')
    old_path = memory.find_memory(repo, old_id)
    if old_path is None:
        _guidance(f"No memory node with id {old_id} to supersede. "
                  f'Find the decision you mean with `yigraf context "<topic>"`.')
    # Sticky attestation (int:memory-attestation): an agent supersede of a HUMAN-attested node is held
    # pending — the new reasoning is captured, but the old node is NOT demoted; it surfaces as a conflict
    # until a human resolves it. Every CLI/MCP caller is "the agent", so human attestation always sticks.
    old_node = memory.read_memory(old_path)
    human_attested = old_node.attestation == "human"
    # Inherit anchors by default (feedback-v3 #4): `supersede` is the verb you reach for while thinking
    # about the CLAIM, not the graph — and a correction that lands with no anchor never resurfaces at
    # the edit hook on the exact symbol it warns about, which is the entire reason to store it. A
    # mind-change is about the same subject, so the old node's concerns/governs/serves carry unless the
    # caller re-aims with explicit flags (each flag overrides its own kind). Inherited loci are
    # re-resolved fresh at capture, so a moved locus soft-warns instead of silently re-anchoring wrong.
    old_regular = [c.sym for c in old_node.concerns if (c.anchor_algo or "") != memory.GOVERNS_ALGO]
    old_governs = [c.sym for c in old_node.concerns if (c.anchor_algo or "") == memory.GOVERNS_ALGO]
    concern_syms = concerns if concerns is not None else old_regular
    governs_refs = governs if governs is not None else old_governs
    serves_ids = serves if serves is not None else list(old_node.serves)
    # `--type` and `promotable` inherit for the same reason the anchors do (feedback-v4 #12): a
    # mind-change is about the same SUBJECT, so a correction to a constraint is still a constraint.
    # Defaulting `--type` to `decision` silently demoted one — while the flag's three siblings on this
    # very verb said "default: inherited" — and `promotable` (the candidate-for-an-enforced-check mark)
    # was dropped with no flag anywhere to restore it, in a verb that ADVERTISES what it carried.
    type_ = type if type is not None else old_node.type
    node = _capture_memory(
        repo, workspace, statement=statement, type_=type_, why=_why_text(why, why_file) or "",
        serves=serves_ids, concern_syms=concern_syms, rejected=_joined_rejected(rejected),
        supersedes=[] if human_attested else [old_id],
        pending_supersedes=[old_id] if human_attested else [],
        promotable=old_node.promotable, grounding=grounding, evidence_refs=evidence or [],
        was_anchored={c.sym for c in old_node.concerns if c.anchor is not None},
        # Only guide loci this caller actually typed. With neither flag given both lists are the
        # predecessor's, and a stored locus that has since become unresolvable or ambiguous must not
        # refuse the mind-change that reacts to it (see `_anchor`'s ``guide``).
        typed_loci=concerns is not None or governs is not None,
        rejected_valid_when=rejected_valid_when or [],
        rejected_invalidated_when=rejected_invalidated_when or [],
        governs_refs=governs_refs)
    _report_capture(node, repo, load_config(workspace / "config.yaml"))
    carried = []
    if concerns is None and old_regular:
        carried.append(f"{len(old_regular)} concerns")
    if governs is None and old_governs:
        carried.append(f"{len(old_governs)} governs")
    if serves is None and old_node.serves:
        carried.append(f"{len(old_node.serves)} serves")
    if type is None and old_node.type != memory.DEFAULT_MEMORY_TYPE:
        carried.append(f"type={old_node.type}")
    if old_node.promotable:
        carried.append("promotable")
    if carried:
        typer.echo(f"Carried {' and '.join(carried)} from {old_id} — the correction stays anchored "
                   f"where the old belief fired (pass --concerns/--serves to re-aim it).")
    if human_attested:
        typer.echo(f"⚠ {old_id} is human-attested — this supersede is HELD PENDING: {node.id} is captured "
                   f"but {old_id} stays authoritative until a human resolves the conflict "
                   f"(`yigraf attest {node.id}` to apply it). Nothing was silently overwritten.")
    else:
        # An APPLIED supersede demotes the predecessor — say so on its own artifact (feedback-v3 #8):
        # `status: active` on a retired belief is what caused a superseded node to get pinned. Metadata,
        # not a claim, so it is edited in place exactly like `attest`/`pin` (the content-addressed id
        # is read from frontmatter and never recomputed). Mirrors what `supersede-intent` already does.
        old_node.status = "superseded"
        old_node.superseded_by = node.id
        old_path.write_text(memory.render_memory(old_node), encoding="utf-8")
        _rebuild(repo)


def _find_intent_file(workspace: Path, slug_cf: str) -> Path | None:
    for path in sorted((workspace / "intents").glob("*.md")):
        if path.stem.casefold() == slug_cf:
            return path
    return None


@app.command()
def attest(
    target: str = typer.Argument(..., help="A memory id (mem:NNN) or an intent (int:<slug>) to mark human-attested."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Record the principal's endorsement: mark a decision or intent HUMAN-attested — a sticky trust floor.

    The human-attestation entry (int:intent-elicitation; resolves the deferral in mem:048). Run it once
    the principal has *actually* chosen — capturing a preference-fork you elicited, or endorsing a
    decision the agent flagged for ack. Attesting a memory that PENDING-supersedes a human-attested node
    APPLIES the held supersede (the principal accepted the change). Attestation is metadata, not a claim,
    so it's edited in place. Only mark human when the human genuinely decided — the trust floor depends
    on that honesty (the agent is the scribe, the principal is the source).
    """
    workspace = _require_workspace(repo)
    if target.startswith("mem:"):
        path = memory.find_memory(repo, target)
        if path is None:
            _guidance(f'No memory node with id {target} to attest. Find it with `yigraf context "<topic>"`.')
        node = memory.read_memory(path)
        applied = list(node.pending_supersedes)
        node.supersedes = list(dict.fromkeys(node.supersedes + applied))  # a held supersede now applies
        node.pending_supersedes = []
        node.attestation = "human"
        path.write_text(memory.render_memory(node), encoding="utf-8")
        # The held supersede just applied, so each predecessor is demoted NOW — stamp its artifact the
        # way an applied `supersede` does (feedback-v3 #8), so the store never shows two active twins.
        for old_id in applied:
            old_path = memory.find_memory(repo, old_id)
            if old_path is not None:
                old_node = memory.read_memory(old_path)
                old_node.status = "superseded"
                old_node.superseded_by = node.id
                old_path.write_text(memory.render_memory(old_node), encoding="utf-8")
        _rebuild(repo)
        typer.echo(f"Attested {target} (human) — a trust floor: an agent supersede of it is now held pending.")
        if applied:
            typer.echo(f"Applied the held supersede: {target} now supersedes {', '.join(applied)} "
                       f"(conflict resolved — the superseded node is demoted).")
        return
    if target.startswith("int:"):
        intent_file = _find_intent_file(workspace, target[len("int:"):].casefold())
        if intent_file is None:
            _guidance(f'No intent {target}. Create it first with `yigraf intent {target[len("int:"):]} -s "…"`.')
        artifacts.update_intent_frontmatter(intent_file, attestation="human")
        _rebuild(repo)
        typer.echo(f"Attested {target} (human) — a human-endorsed spec (trust floor).")
        return
    _guidance(f"attest takes a memory id (mem:NNN) or an intent (int:<slug>), got: {target}")


def _known_belief(repo: Path, belief_id: str) -> bool:
    """Whether ``belief_id`` names a belief this workspace can see — authored here, or arrived over the
    sync log and folded into the built graph. The second case is exactly the one a resolution exists to
    serve, so validation must not be limited to what has a local markdown file."""
    if memory.find_memory(repo, belief_id) is not None:
        return True
    graph, _ = build_graph(repo, load_config(_require_workspace(repo) / "config.yaml"))
    return belief_id in graph


def _author_resolution(repo: Path, kind: str, left: str, right: str, why: str, origin: str | None) -> None:
    """Write a resolution artifact — the verdict path for a pair this workspace does not own.

    Content-addressed by ``(kind, left, right)``, so re-running is idempotent and two principals who
    reach the same verdict collapse to one node (:func:`yigraf.resolution.resolution_id`).
    """
    existing = resolution.find_resolution(repo, kind, left, right)
    if existing is not None:
        _guidance(f"{left} and {right} already have a {kind} verdict ({existing.id}) — nothing to do.")
    provenance = {"source": "cli"}
    if origin:
        provenance["origin"] = origin
    res = resolution.Resolution(
        id=resolution.resolution_id(kind, left, right),
        kind=kind, left=left, right=right, why=why, provenance=provenance)
    dest = resolution.resolution_path(repo, res)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(resolution.render_resolution(res), encoding="utf-8")
    _rebuild(repo)


@app.command()
def dispute(
    left: str = typer.Argument(..., help="A belief id (mem:NNN / int:<slug>) — one side of the disagreement."),
    right: str = typer.Argument(..., help="The belief it contradicts."),
    why: str = typer.Option("", "--why", help="What the disagreement is, for whoever resolves it."),
    why_file: Path = typer.Option(None, "--why-file", help=_WHY_FILE_HELP),
    origin: str = typer.Option(None, "--origin", help="Free-text provenance detail for the audit trail."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Nominate two beliefs as contradictory — the durable "open a PR" step for a knowledge-conflict.

    The coherence sweep (:mod:`yigraf.contradiction`) is *derived* and fails open to silence when there
    is no embedding index, which is right for one developer and wrong for a team: the same merged log
    would otherwise yield a different open-conflict set on every client. A nomination is an assertion,
    so it rides the log and everyone sees it — index or not, and including the stance-opposed pairs
    that read as too dissimilar for the cosine gate to ever catch.

    It blocks nothing. Both beliefs stay live and fully weighted; the pair is simply now a named,
    actor-stamped open question. Close it with ``reconcile`` (both true) or ``supersede`` (a
    mind-change) — never by deleting the nomination.
    """
    _require_workspace(repo)
    if left == right:
        _guidance("A belief can't dispute itself — pass the two distinct beliefs of the pair.")
    for belief_id in (left, right):
        if not (belief_id.startswith("mem:") or belief_id.startswith("int:")):
            _guidance(f"dispute takes two belief ids (mem:NNN or int:<slug>); got: {belief_id}")
        if not _known_belief(repo, belief_id):
            _guidance(f'No belief with id {belief_id}. Find it with `yigraf context "<topic>"`.')
    _author_resolution(repo, "dispute", left, right, _why_text(why, why_file) or "", origin)
    typer.echo(f"Disputed {left} ↔ {right} — an open conflict, now on the log for the team. "
               f"Resolve with `yigraf reconcile` (both true) or `yigraf supersede` (a mind-change).")


@app.command()
def reconcile(
    left: str = typer.Argument(..., help="A memory id (mem:NNN) — the pair's first belief."),
    right: str = typer.Argument(..., help="A memory id (mem:NNN) — the belief it is compatible with."),
    why: str = typer.Option("", "--why", help="Why they are compatible (recorded when the verdict is a resolution artifact)."),
    why_file: Path = typer.Option(None, "--why-file", help=_WHY_FILE_HELP),
    origin: str = typer.Option(None, "--origin", help="Free-text provenance detail for the audit trail."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Reconcile a co-anchored conflict: record that two live beliefs are *compatible*, not opposed.

    The honest counterpart to ``supersede`` for a knowledge-conflict (the coherence sweep,
    int:concurrent-write-model / mem:062): when two memories concerning the same locus read as
    near-duplicates, the sweep surfaces the pair for a principal. If they are a redundant or
    *complementary* restatement — both true, at different altitudes — reconcile them; if one is a
    mind-change, ``supersede`` instead. This appends an ``equivalent_to`` edge (a *later append*, never
    an edit of either belief) that :mod:`yigraf.contradiction` reads to drop the pair from the sweep.
    Both beliefs stay live and fully weighted; only the redundant conflict-finding goes away.

    The verdict is always its own append — a resolution artifact (:mod:`yigraf.resolution`) — never an
    edit of either belief, for two reasons that turn out to be the same reason.

    *Ownership.* The resolving principal frequently owns neither belief (both arrived over the sync
    log, so there is no local artifact to edit at all). A conflict only its authors may close would
    deadlock the moment one of them leaves the team.

    *Content-addressing.* ``equivalent_to`` frontmatter used to be written onto ``left``'s artifact when
    it happened to be local. That silently broke the ``memid-v1`` invariant: the id hashes what a memory
    says and links to, but :func:`yigraf.memory.memory_id` does not cover ``equivalent_to``, so the edit
    changed the assertion's *body* while leaving its *id* fixed. Two different bodies then shared one id,
    and ``yigraf sync`` — which identifies an assertion by id — could never see that the belief had
    changed, so the reconciliation stayed silently local forever. An append has no such problem: it is a
    new node with its own id. Existing ``equivalent_to`` frontmatter is still *read* for compatibility.
    """
    _require_workspace(repo)
    if left == right:
        _guidance("A memory can't be reconciled with itself — pass the two distinct beliefs of the pair.")
    for mem_id in (left, right):
        if not mem_id.startswith("mem:"):
            _guidance(f"reconcile takes two memory ids (mem:NNN mem:NNN); got: {mem_id}")
        if not _known_belief(repo, mem_id):
            _guidance(f'No memory node with id {mem_id}. Find it with `yigraf context "<topic>"`.')

    # Duplicate detection lives in _author_resolution (by content-addressed verdict id). Legacy
    # ``equivalent_to`` frontmatter deliberately does NOT block: promoting one to a real append is how
    # a pre-sync workspace makes its old, purely-local reconciliations visible to the team.
    _author_resolution(repo, "reconcile", left, right, _why_text(why, why_file) or "", origin)
    typer.echo(f"Reconciled {left} ↔ {right} (equivalent_to) — the co-anchored pair is marked "
               f"compatible, so the coherence sweep no longer surfaces it. Both stay live.")


def _reaffirm_concerns(repo: Path, config: dict, node: memory.Memory,
                       only: set[str]) -> tuple[list[str], list[str]]:
    """Re-stamp a memory's matching ``concerns`` anchors to current content; return ``(restamped, gone)``.

    Mutates ``node`` in place (the caller writes it). ``only`` restricts which concern loci are touched
    (empty ⇒ all). A gone symbol/file is left un-restamped (hard drift, not a reaffirm) and reported so
    rename re-anchoring still works. Shared by both reaffirm forms (single-node and locus-scoped).
    """
    restamped, gone = [], []
    for c in node.concerns:
        if only and c.sym not in only:
            continue
        if (c.anchor_algo or "") == memory.GOVERNS_ALGO:
            continue  # a policy anchor has no content hash — nothing to re-stamp, nothing to re-arm
        if c.sym.startswith("file:"):
            fresh, algo = locus_hash(repo, c.sym)  # section | line range | whole file
        else:
            fresh, algo = symbol_content_hash(repo, c.sym, config), ANCHOR_ALGO
        if fresh is None:  # a gone symbol/file is hard drift, not a reaffirm — keep anchor for rename match
            gone.append(c.sym)
            continue
        if fresh != c.anchor:
            restamped.append(c.sym)
        c.anchor, c.anchor_algo = fresh, algo
    return restamped, gone


def _rescued_renames(repo: Path, config: dict,
                     pairs: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """Which ``(memory id, gone locus)`` pairs the projection has already re-anchored → the new locator.

    ``_reaffirm_concerns`` hashes the stored locus and stops, so the batch could not see a rescue
    :func:`yigraf.drift.resolve_renames` had already made — and reported as permanent hard drift the one
    obligation that EXPIRES (feedback-v6 F#2). Like :func:`_renamed_predecessor` this does not guess: it
    asks ``compute_drift``, which carries every false-positive guard the rescue needs, so this surface
    and ``drift``/``gc`` cannot disagree about one event. Built only when something is actually gone —
    every ordinary reaffirm returns here empty and pays nothing.
    """
    if not pairs:
        return {}
    graph, _ = build_graph(repo, config)
    wanted = set(pairs)
    return {(item.task_id, item.locator): item.new_locator
            for item in compute_drift(graph)
            if item.kind == "renamed" and item.new_locator and (item.task_id, item.locator) in wanted}


def _reaffirm_evidence(repo: Path, config: dict, node: memory.Memory, new_refs: list[str]) -> list[str]:
    """Upsert ``--evidence`` refs onto ``node`` (int:memory-grounding); return the refs touched.

    Each locus (sym:/file:) is stamped with a fresh drift anchor: a ref already grounding the node is
    re-anchored to current content (grounds-drift: the observation was re-verified), a new one is
    appended; opaque refs (commit:/url/text) upsert with no anchor. Mutates ``node`` in place. Called
    ONLY on an explicit ``--evidence`` — never a bare reaffirm — so clearing grounds-drift requires
    re-naming the observation, never a silent rubber-stamp (the dishonesty mem:031 guards against).
    """
    touched: list[str] = []
    by_ref = {e.ref: e for e in node.evidence}
    for ref in new_refs:
        anchor, algo = _anchor(repo, config, ref) if ref.startswith(("sym:", "file:")) else (None, None)
        if ref in by_ref:
            by_ref[ref].anchor, by_ref[ref].anchor_algo = anchor, algo
        else:
            ev = memory.Evidence(ref=ref, anchor=anchor, anchor_algo=algo)
            node.evidence.append(ev)
            by_ref[ref] = ev
        touched.append(ref)
    return touched


def _stale_grounds(repo: Path, config: dict, node: memory.Memory) -> list[str]:
    """Evidence refs whose stored anchor no longer matches the current source — the grounds-drift a
    bare ``reaffirm`` structurally cannot clear (only ``--evidence`` re-stamps; ``unlink`` retires).
    A gone locus counts too: its current anchor is ``None`` ≠ the stored one.

    ``guide=False`` because every ref here is one the node already **stores**, not one this caller
    typed — the distinction :func:`_anchor` documents. Without it, a third party making a governed
    evidence section ambiguous made ``reaffirm`` refuse with a message about heading titles, dead-ending
    the very verb the drift line had just named, for a caller who touched no docs (D5)."""
    out: list[str] = []
    for e in node.evidence:
        if e.anchor is None or not e.ref.startswith(("sym:", "file:")):
            continue  # opaque (commit:/url) or never-anchored — nothing to compare
        if _anchor(repo, config, e.ref, guide=False)[0] != e.anchor:
            out.append(e.ref)
    return out


def _dead_grounds(repo: Path, config: dict, node: memory.Memory) -> list[str]:
    """Evidence loci that no longer resolve at all — the HARD grounds-drift ``_stale_grounds`` cannot see.

    A deleted locus stamps ``anchor: None``, which ``_stale_grounds`` skips (nothing to compare), and
    the ref then projects as a *dangling* ``grounded_by`` edge — permanent hard drift. So the one
    ``--evidence`` form the empirical guard accepts (re-naming the drifting locator) used to report
    success on a path that does not exist, with no warning tail at all (feedback-v4 #2).

    ``guide=False`` for the reason :func:`_stale_grounds` gives: these refs are stored, not typed.
    """
    return [e.ref for e in node.evidence
            if e.ref.startswith(("sym:", "file:"))
            and _anchor(repo, config, e.ref, guide=False)[0] is None]


def _reaffirm_ledger(root: Path) -> Path:
    """The machine-local ledger of recent single-id reaffirms (``yigraf/.local/reaffirms.json``).

    Volatile, gitignored, never the graph — the same rule that keeps usage/last_seen out of the
    projection (design law #6). It is not belief state: it records *that a re-verification was claimed*
    and, when one was given, the caller's own one-line account of what they checked. That makes it the
    one thing the graph could never hold — an audit trail of the claim rather than the claim.
    """
    return Path(root) / "yigraf" / ".local" / "reaffirms.json"


def _read_reaffirm_ledger(root: Path) -> list[dict]:
    """The ledger, or ``[]`` — fail-open in the permissive direction. A guard that cannot read its own
    history must let the caller through, not block real work over a corrupt sidecar (design law #5)."""
    try:
        data = json.loads(_reaffirm_ledger(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict) and isinstance(e.get("at"), (int, float))] \
        if isinstance(data, list) else []


def _record_reaffirm_claim(root: Path, target: str, verified: str | None) -> None:
    """Append one reaffirm to the ledger, keeping the last 50. Silent on any I/O failure."""
    entries = _read_reaffirm_ledger(root)[-49:]
    entries.append({"at": time.time(), "target": target, "verified": verified or None})
    try:
        path = _reaffirm_ledger(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries), encoding="utf-8")
    except OSError:
        pass


def _guard_reaffirm_burst(repo: Path, config: dict, target: str, verified: str | None) -> None:
    """Past N unverified single-id reaffirms in a window, require ``--verified "<what you checked>"``.

    ``reaffirm`` is the one verb whose whole meaning is "I read this and it still holds", and it is the
    one verb that asks for no evidence of the reading. So a `for` loop over ids clears a drift count to
    zero, prints a success line each time, and the counter going down *feels* like progress — while an
    active decision can be certified as re-verified carrying a clause the same session's edit already
    falsified (feedback-v5, still-open #1).

    Three properties this deliberately has:

    * it never blocks the honest caller. The first few are free, and past that the cost is one sentence
      naming what you checked — which somebody who actually read the claim can write and a loop cannot.
    * it exits **0** with guidance, like every other recoverable refusal (design law #1), so it teaches
      the retry instead of teaching the agent that yigraf fails.
    * it is scoped to the **id** form. The locus form is already bounded by an act — you re-verified
      one locus — and rate-limiting it would punish the honest batch to catch the dishonest loop.

    A prose prohibition in the session preamble is what this replaces, and the argument for the guard is
    that the preamble is precisely the artifact a hurrying agent skips.
    """
    limit = int(config.get("reaffirm_burst", 3) or 0)
    if limit <= 0 or verified:
        return
    window = float(config.get("reaffirm_burst_window", 300) or 0)
    cutoff = time.time() - window
    recent = [e for e in _read_reaffirm_ledger(repo)
              if e["at"] >= cutoff and not e.get("verified")]
    if len(recent) < limit:
        return
    ids = ", ".join(dict.fromkeys(e.get("target", "?") for e in recent[-limit:]))
    _guidance(
        f"That is {len(recent)} reaffirms in the last {int(window // 60) or 1} minute(s) "
        f"({ids}) with nothing recorded about what was checked — so this one needs "
        f'`--verified "<what you actually re-read, in one line>"`.\n'
        f"  Reaffirm means \"I read this claim and it still holds\". Nothing in the command proves the "
        f"reading, and a clearing drift count feels like progress whether or not it happened — so past "
        f"a few in a row, say what you checked.\n"
        f"  Read it first if you have not: `yigraf show {target}`. Then:\n"
        f'    yigraf reaffirm {target} --verified "<e.g. re-read the retry policy; the 3-attempt cap '
        f'is still what the code does>"\n'
        f"  If the claim did NOT survive your reading, the verb is not this one: "
        f'`yigraf supersede {target} "<the restated belief>" --why "<what changed>"`.\n'
        f"  (Turn this off with reaffirm_burst: 0 in yigraf/config.yaml.)")


@app.command()
def reaffirm(
    target: str = typer.Argument(..., help="A memory id (mem:NNN → reaffirm its concerns) or a locus (sym:<path>#<name> or file:<path> → reaffirm every memory concerning it)."),
    concerns: list[str] = typer.Option(None, "--concerns", help="With a mem: id, re-anchor only these loci (default: all the node's concerns)."),
    grounding: str = typer.Option(None, "--grounding", help=f"With a mem: id, upgrade its grounding in place ({' | '.join(memory.GROUNDINGS)}) — e.g. a live spike just confirmed an inferred decision."),
    evidence: list[str] = typer.Option(None, "--evidence", help="With a mem: id, name/re-anchor the observation grounding it (required to reach empirical): sym:<path>#<test> | file:<path> | commit:<sha> | <url> (repeatable)."),
    verified: str = typer.Option(None, "--verified", help="One line naming what you actually re-read. Required past a burst of unverified single-id reaffirms; recorded in the local audit ledger."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Re-verify a decision still holds and re-stamp its ``concerns`` anchors to the current code.

    The honest counterpart to ``supersede``: when a locus a memory ``concerns`` is edited, drift fires
    ("body changed since anchored") to force a re-verify — but if the decision still holds, there was no
    mind-change to ``supersede`` and re-``remember`` would only duplicate. ``reaffirm`` records the
    re-verification by re-stamping the anchor to the locus's current content, clearing the drift
    in-place (no claim changes, only the anchor advances). Mirrors how ``link`` re-stamps a task's
    ``implements`` anchor.

    Two forms: ``reaffirm mem:<id>`` reaffirms one memory's concerns; ``reaffirm <sym|file>`` reaffirms
    **every** memory concerning that locus — the honest batch for an edit-heavy session, scoped to a
    locus you actually re-verified. There is deliberately no blanket "clear all drift" (that would
    rubber-stamp decisions you never re-checked — the dishonesty ``reaffirm`` exists to avoid; mem:031).
    """
    workspace = _require_workspace(repo)
    config = load_config(workspace / "config.yaml")
    if grounding is not None and grounding not in memory.GROUNDINGS:
        _guidance(f"--grounding must be one of {', '.join(memory.GROUNDINGS)} (got {grounding}).")

    if target.startswith("mem:"):
        path = memory.find_memory(repo, target)
        if path is None:
            _guidance(f"No memory node with id {target} to reaffirm. "
                      f'Find the decision you mean with `yigraf context "<topic>"`.')
        # Before anything is written: past a burst of unverified single-id reaffirms, this one must say
        # what was checked (feedback-v5 still-open #1). Id form only — see the guard's docstring.
        _guard_reaffirm_burst(repo, config, target, verified)
        _record_reaffirm_claim(repo, target, verified)
        node = memory.read_memory(path)
        # Upsert any --evidence first: re-anchor a locus already grounding this node (grounds-drift:
        # re-observed) or add a fresh observation. Done before the empirical gate so the gate sees it.
        # Captured BEFORE the upsert: the guard below must report every locator drifting on DISK, not
        # what is left after this call's in-memory re-stamps. Reporting the remainder sent the caller
        # into a ping-pong — the refusal writes nothing, so re-running with only the ref it named then
        # refuses naming the other one (feedback-v4 #2).
        pre_stale = _stale_grounds(repo, config, node)
        # Also captured before the upsert, for the success line: whether there was any grounds-drift to
        # clear, and which refs the node already grounded on. `--evidence` upserts onto `grounded_by`
        # whatever the ref is, so without these two the message cannot tell "re-observed the drifting
        # locator" from "filed a brand-new locus on a list this node did not have" (feedback-v9 H#5).
        pre_dead = _dead_grounds(repo, config, node)
        pre_grounds = {e.ref for e in node.evidence}
        added_evidence = _reaffirm_evidence(repo, config, node, evidence or [])
        # The empirical tier must NAME a live observation — the same gate as capture (int:memory-grounding).
        # This closes the reaffirm loophole: `--grounding empirical` no longer upgrades on the agent's word.
        #
        # Keyed on the flag the caller PASSED, never on the tier the node already carries. Falling back
        # to `node.grounding` turned a gate on the *upgrade* into a gate on every reaffirm of a node that
        # predates the evidence requirement — five in this repo's own store, all pre-1.5.0 — and the
        # concerns re-stamp such a caller wants has nothing to do with grounding. Both exits the message
        # names then miss: `--evidence` asks them to invent an observation, and the downgrade discards a
        # tier that is probably true, to clear a drift on a different axis. That is design law #1's dead
        # end — guidance whose taught retry cannot do what was asked. The sibling guard below already
        # keyed on `grounding` alone, so the two disagreed about the same question.
        if grounding == "empirical" and not node.evidence:
            _guidance(f"--grounding empirical requires naming the observation that confirms {target}: add "
                      f"--evidence sym:<path>#<test> | file:<path> | commit:<sha> | <url>. If you can no "
                      f"longer confirm it, downgrade honestly: `yigraf reaffirm {target} --grounding inferred`.")
        # The other half of that loophole (feedback-v3 #6): a node that already HAS evidence passes the
        # gate above, so `--grounding empirical` with no --evidence exits clean while the stale anchor
        # — the thing grounds-drift is about — was never touched. An empirical re-stamp that does not
        # re-observe is the rubber-stamp the reaffirm/supersede split exists to prevent, so refuse it.
        stale_grounds = _stale_grounds(repo, config, node)
        if stale_grounds and grounding == "empirical":
            # Say the condition, not a rule about a command nobody ran (feedback-v4 #2). The guard is
            # "every drifting locator must be re-named", and it refuses atomically — so naming one of
            # two and following the message verbatim used to refuse again on the other. Both halves
            # were the message's fault, not the guard's: the rule is right, it just never said itself.
            _guidance(f"{target} has grounds-drift on {', '.join(pre_stale)}, and --grounding empirical "
                      f"re-asserts the tier — so EVERY drifting locator must be re-observed and named "
                      f"in this same call, by the exact string the node carries "
                      f"({', '.join(stale_grounds)} still uncovered). Nothing was written. "
                      f"Re-observe, then `yigraf reaffirm {target} --grounding empirical "
                      + " ".join(f"--evidence {r}" for r in pre_stale) + "`. "
                      f"If an observation MOVED, that is a locus repair, not a re-observation: "
                      f"`yigraf reanchor {target} {stale_grounds[0]} <where it lives now>` keeps both "
                      f"the tier and the evidence link. If it never belonged, "
                      f"`yigraf unlink {target} {stale_grounds[0]}`.")
        # A pure grounding upgrade is meaningful even for a memory with no concerns anchor (the claim is
        # unchanged; only its epistemic status advances) — so require concerns only when nothing else acts.
        if not node.concerns and grounding is None and not added_evidence:
            _guidance(f"{target} concerns no symbol/file and you named no --evidence, so there is nothing "
                      f"to re-anchor. To record that a live observation confirms it, "
                      f"`yigraf reaffirm {target} --grounding empirical --evidence <locus>`.")
        only = set(concerns or [])
        unknown = only - {c.sym for c in node.concerns}
        if unknown:
            # The refusal that used to dead-end a locus repair (feedback-v3 #2) — now it hands over
            # the verb that moves an anchor instead of leaving supersede as the only way out.
            first = sorted(unknown)[0]
            _guidance(f"{target} doesn't concern {', '.join(sorted(unknown))}. "
                      f"It concerns: {', '.join(c.sym for c in node.concerns)}. "
                      f"If the subject moved there, `yigraf reanchor {target} <old> {first}`; "
                      f"reaffirm only re-stamps anchors the node already carries.")
        restamped, gone = _reaffirm_concerns(repo, config, node, only)
        upgraded = grounding is not None and grounding != node.grounding
        was = node.grounding
        if grounding is not None:
            node.grounding = grounding
        path.write_text(memory.render_memory(node), encoding="utf-8")
        _rebuild(repo)
        if upgraded:
            typer.echo(f"Reaffirmed {target}: grounding {was} → {node.grounding}.")
        if added_evidence:
            # Only claim the ⚠ is gone when it is (feedback-v4 #2). `stale_grounds` is recomputed after
            # the upsert, so it still lists whatever this call did not reach — and a ref whose file was
            # DELETED stamps a null anchor, drops out of `stale_grounds` entirely, and goes on hard-
            # drifting as a dangling edge. A success line a following `drift` contradicts is the one
            # message an agent is most likely to believe and stop on.
            left = ((stale_grounds if node.grounding == "empirical" else [])
                    + _dead_grounds(repo, config, node))
            # …and only claim there WAS drift when there was: a node with no `grounded_by` list has no
            # grounds-drift, so "cleared" on its first-ever observation described an event that never
            # happened — and it read as compliance to a caller who had arrived from the reanchor/unlink
            # drop ⚠ trying to put a `concerns` anchor back (feedback-v9 H#5).
            had_drift = bool(pre_stale) or bool(pre_dead)
            typer.echo(f"Reaffirmed {target}: grounded by {', '.join(added_evidence)}"
                       + (" — grounds-drift cleared." if had_drift and not left else "."))
            # Name the list when a locus lands on it for the first time and the node also carries
            # `concerns` anchors, because there the two lists are both live and mean different things:
            # `grounded_by` is evidence FOR the claim, `concerns` is the code the claim GOVERNS. Only a
            # governed locus surfaces as one, so a ref filed here instead is not the anchor the drop ⚠
            # says no verb restores — it is a different assertion that happens to name the same locus.
            fresh = [r for r in added_evidence if r not in pre_grounds]
            if fresh and node.concerns:
                one = len(fresh) == 1
                anchors = " ".join(f"--concerns {r}" for r in [c.sym for c in node.concerns] + fresh)
                plural = "" if one else "s"
                typer.echo(f"  {', '.join(fresh)} {'is' if one else 'are'} now evidence FOR {target}, "
                           f"on `grounded_by` — not {'a ' if one else ''}`concerns` anchor{plural}, "
                           f"which is the code the claim GOVERNS, and only a governed locus surfaces "
                           f"as one. This does not add a `concerns` anchor back; no verb does. If the "
                           f"belief governs {'it' if one else 'them'} too, restate it with the anchors "
                           f"it should carry: `yigraf supersede {target} \"<the belief, restated>\" "
                           f"{anchors}` (--concerns replaces the list, so name every one).")
        if restamped:
            typer.echo(f"Reaffirmed {target}: re-anchored {', '.join(restamped)} to current code — drift cleared.")
        elif not gone and not upgraded and not added_evidence:
            typer.echo(f"Reaffirmed {target}: anchors already matched the current code (no drift to clear).")
        if gone:
            typer.echo(f"⚠ {target} concerns {', '.join(gone)}, which no longer resolve(s) in the source — "
                       f"reaffirm can't re-anchor a gone locus. If the locus moved but the belief holds, "
                       f"`yigraf reanchor {target} <old> <new>`; if the decision itself changed, "
                       f'`yigraf supersede {target} "<restated>"`.')
        # Two clean exits that leave a ⚠ standing read as "done" (feedback-v3 #6/#9): when grounds-drift
        # survives this call (computed AFTER the --evidence upsert, so a re-stamped ref has already
        # dropped out), say so and name the two verbs that actually reach it.
        # Mirrors drift.is_surfaced: a SOFT grounds-drift on a belief that is no longer `empirical` is
        # not an obligation — the tier it defended has been withdrawn (feedback-v4 #2). A DEAD ref is,
        # at any tier: a citation to something that does not exist is broken however weakly it is held.
        soft_unrepaired = stale_grounds if node.grounding == "empirical" else []
        dead = _dead_grounds(repo, config, node)
        unrepaired = soft_unrepaired + dead
        if unrepaired:
            first = unrepaired[0]
            # A DEAD ref is not offered the re-observe exit: re-naming a locator whose file is gone is
            # exactly the call that just "succeeded" and cleared nothing (feedback-v4 #2).
            reobserve = ("" if not soft_unrepaired else
                         f" if you re-ran it in place, `yigraf reaffirm {target} --grounding empirical "
                         + " ".join(f"--evidence {r}" for r in soft_unrepaired) + "`;")
            typer.echo(f"⚠ grounds-drift still stands on {', '.join(unrepaired)} — reaffirm re-stamps "
                       f"concerns, never evidence. If the observation MOVED or was replaced, "
                       f"`yigraf reanchor {target} {first} <fresh>` (keeps the tier, no supersede);"
                       + reobserve
                       + (f" if nothing replaces it, downgrade `yigraf reaffirm {target} --grounding "
                          f"inferred` and then `yigraf unlink {target} {first}`." if dead else
                          f" if it never belonged, `yigraf unlink {target} {first}`."))
        # An `empirical` node carrying no evidence at all is a real gap — the tier claims an observation
        # the artifact cannot name, so nothing can drift-check it and `grounds-drift` can never fire. It
        # is said here, once, after the re-stamp it must not block: the caller asked to re-verify a
        # decision, and refusing that to collect a citation would be the dead end above (design law #1
        # cuts both ways — teach the fix, don't hold the work hostage to it).
        if node.grounding == "empirical" and not node.evidence:
            typer.echo(f"note: {target} claims the empirical tier but names no evidence, so nothing "
                       f"drift-checks it. When you next confirm it, `yigraf reaffirm {target} "
                       f"--grounding empirical --evidence <locus>`; if it was really an inference, "
                       f"`yigraf reaffirm {target} --grounding inferred`.")
        if verified:
            # Echoed, and kept in the local ledger: an assertion the caller had to compose is the only
            # evidence of reading this verb can ever have, so it must not vanish into the exit code.
            typer.echo(f'  verified: "{verified}"')
        _record_reaffirm_uphold(repo, config, [target])  # an explicit re-verification → strong uphold
        return

    if not (target.startswith("sym:") or target.startswith("file:")):
        _guidance(f"reaffirm takes a memory id (mem:NNN) or a locus (sym:<path>#<name> or file:<path>), "
                  f"got: {target}")
    if concerns:
        _guidance("--concerns filters a single mem: node; with a locus the locus IS the filter — drop --concerns.")

    # Locus-scoped batch: reaffirm the target's anchor on *every* LIVE memory that concerns it (you
    # verified this one locus, so reaffirming its decisions is a bounded, honest act — not a blanket
    # sweep). Superseded memories are excluded (feedback-v3 #14): re-stamping a retired belief inflates
    # the reported count, and crediting it an uphold pollutes the maturity counters — the field watched
    # a node it had superseded minutes earlier get "re-verified" by the batch. Liveness is read
    # artifact-side (successors' `supersedes` + the status stamp), matching drift.is_reverifiable.
    all_memories = memory.iter_memories(repo)
    superseded_ids = {old for m in all_memories for old in m.supersedes}
    matched, restamped_ids, matched_ids, skipped = 0, [], [], []
    # The (memory, locus) PAIRS that failed — never just the ids. D#4 widened this batch so a whole-file
    # target covers the section anchors inside it, which severed the old identity `gone ⊆ {target}`: the
    # thing that is gone is now routinely an anchor the caller did not type, and reporting the file they
    # did type named a file still on disk and handed over a `reanchor` whose old-locus was the healthy
    # anchor (feedback-v6 F#2). The pair is the informative unit — two memories under one file can fail
    # at two different sections, so neither half alone identifies what to repair.
    gone_pairs: list[tuple[str, str]] = []
    sections_reached: set[str] = set()
    for node in all_memories:
        # A whole-file locus reaches the section anchors inside it, so the mdsec-v1 cure for prose
        # false-drift composes with the batch-clear (feedback-v5 D#4).
        covered = _covered_loci(target, {c.sym for c in node.concerns})
        if not covered:
            continue
        if node.id in superseded_ids or node.status != "active":
            skipped.append(node.id)
            continue
        matched += 1
        matched_ids.append(node.id)
        restamped, gone = _reaffirm_concerns(repo, config, node, covered)
        if restamped or gone:
            memory.memory_file_path(repo, node).write_text(
                memory.render_memory(node), encoding="utf-8")
        if restamped:
            restamped_ids.append(node.id)
        gone_pairs += [(node.id, locus) for locus in gone]
        # Only the anchors this call actually re-stamped. The echo invites the reading "here are this
        # file's sections", so listing one that was just DELETED misleads exactly where it matters; the
        # failures are enumerated by name below instead.
        sections_reached |= {c for c in covered if c != target and c not in gone}
    if matched == 0:
        if skipped:
            _guidance(f"Only superseded memories concern {target} ({', '.join(sorted(skipped))}) — "
                      f"a retired belief is not re-verified. If its successor should govern this locus, "
                      f"anchor the successor instead.")
        # Before advising a SECOND memory about a locus the store already reasons about (feedback-v4
        # #9): the locus form scans `concerns` by design, but a live `grounded_by` anchor on the same
        # locus is reachable — by the mem: form — and pointing at `remember` there duplicates a claim
        # the node two lines away in `show` already holds. Name what actually carries it.
        grounding_it = [m.id for m in all_memories
                        if target in {e.ref for e in m.evidence}
                        and m.id not in superseded_ids and m.status == "active"]
        if grounding_it:
            _guidance(f"No memory *concerns* {target} — the locus form re-stamps `concerns` only. But "
                      f"{', '.join(grounding_it)} {'is' if len(grounding_it) == 1 else 'are'} grounded "
                      f"by it, and that anchor is reached per-node: "
                      f"`yigraf reaffirm {grounding_it[0]} --evidence {target}` re-stamps it once you "
                      f"have re-observed it. Don't capture a second memory about a locus the store "
                      f"already reasons about.")
        _guidance(f"No memory concerns {target} — nothing to reaffirm. "
                  f'Anchor one with `yigraf remember "…" --concerns {target}`.')
    _rebuild(repo)
    gone_ids = sorted({mem_id for mem_id, _ in gone_pairs})
    # A gone locus is hard drift, not a survival — credit an uphold only to memories still anchored there.
    _record_reaffirm_uphold(repo, config, [m for m in matched_ids if m not in gone_ids])
    # A "gone" anchor whose subject was merely RENAMED is not gone at all: the projection already
    # re-anchored it by content hash, and `drift` and `gc` both report it as a settle-with-`gc --apply`
    # rescue in the same store in the same minute. Saying "hard drift" here contradicted them, and it
    # said it about the ONE signal that expires — the rescue is re-derived from the body on every build,
    # so an agent told the drift is permanent has no reason to settle it while it still can (F#2).
    rescued = _rescued_renames(repo, config, gone_pairs)
    renamed_pairs = [(m, loc, rescued[(m, loc)]) for m, loc in gone_pairs if (m, loc) in rescued]
    hard_pairs = [(m, loc) for m, loc in gone_pairs if (m, loc) not in rescued]
    if sections_reached:
        # Never silently: the caller named a file and the batch touched anchors that name sections, so
        # the echo says which. A count alone would leave them believing they re-stamped one thing.
        shown = ", ".join(sorted(sections_reached)[:6])
        more = f" (+{len(sections_reached) - 6} more)" if len(sections_reached) > 6 else ""
        typer.echo(f"{target} reached {len(sections_reached)} section anchor(s) inside it: {shown}{more}")
    if restamped_ids:
        # A memory in BOTH lists is partially repaired, and saying so is more useful than either line
        # alone — "drift cleared: mem:x" directly above "⚠ … mem:x" reads as a contradiction (F#2).
        partial = sorted(set(restamped_ids) & set(gone_ids))
        note = f" (partial — {', '.join(partial)} still carries the ⚠ below)" if partial else ""
        typer.echo(f"Reaffirmed {len(restamped_ids)} memory(ies) concerning {target} — drift cleared: "
                   f"{', '.join(restamped_ids)}{note}.")
    elif not gone_pairs:
        typer.echo(f"Reaffirmed {matched} memory(ies) concerning {target}: anchors already matched "
                   f"the current code (no drift to clear).")
    if renamed_pairs:
        typer.echo(f"⚠ {len(renamed_pairs)} anchor(s) under {target} were RENAMED, not lost — the graph "
                   f"re-anchored them by content hash and the artifact still names the locator they "
                   f"left, so reaffirm cannot re-stamp them. Settle with `yigraf gc --apply` while the "
                   f"body is untouched; edit that body first and it becomes hard drift with no record "
                   f"of where the subject went:")
        for mem_id, old, new in renamed_pairs:
            typer.echo(f"  · {mem_id} —concerns→ {old} ⇒ {new}")
    if hard_pairs:
        first_mem, first_locus = hard_pairs[0]
        typer.echo(f"⚠ {len(hard_pairs)} anchor(s) under {target} no longer resolve in the source — "
                   f"hard drift, not a reaffirm:")
        for mem_id, locus in hard_pairs:
            typer.echo(f"  · {mem_id} —concerns→ {locus}")
        typer.echo(f"  If the subject moved, `yigraf reanchor {first_mem} {first_locus} <new>` (the "
                   f"anchor that failed, not the locus you typed); if the decision itself changed, "
                   f'`yigraf supersede {first_mem} "<restated>"`.')
    if skipped:
        typer.echo(f"(skipped {len(skipped)} superseded: {', '.join(sorted(skipped))} — a retired "
                   f"belief is not re-verified and earns no uphold.)")


@app.command()
def context(
    query: str = typer.Argument(..., help="What to look up, e.g. \"session expiry\"."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
    family: str = typer.Option(None, "--family", help="Restrict to one family: structure|intent|plan."),
    grounding: str = typer.Option(None, "--grounding", help=f"Restrict memory nodes to one grounding tier: {' | '.join(memory.GROUNDINGS)} (C#6)."),
    scores: bool = typer.Option(False, "--scores", help="Append the per-node semantic similarity (cosine) to each rendered node."),
    budget: int = typer.Option(None, "--budget", help="Token budget for the render."),
) -> None:
    """Retrieve a scoped, token-budgeted slice of the graph for a query (locators + signatures)."""
    workspace = _require_workspace(repo)
    if grounding is not None and grounding not in memory.GROUNDINGS:
        _guidance(f"--grounding must be one of {', '.join(memory.GROUNDINGS)} (got {grounding}).")
    config = load_config(workspace / "config.yaml")
    graph, _ = graphdb.load_or_build(repo, config)  # materialized view; rebuilt only when inputs changed
    # An id is not a topic. Handed `context "mem:1678ce10…"` the seeder tokenizes the hex and returns
    # whatever sits nearest in embedding space under a low-confidence banner — proximity noise that
    # reads as an answer. Every drift/conflict line now pre-fills an id, so this is the query an agent
    # makes right after being told what to act on; send it to the verb that reads one (design law #1).
    if show_mod.looks_like_locator(query):
        resolved, candidates = show_mod.resolve(graph, query)
        if resolved:
            _guidance(f"{query} is a node id, not a topic — read it in full with "
                      f"`yigraf show {resolved}`. (`context` searches by meaning; it has no way to "
                      f"match an id except by accident.)")
        if candidates:
            _guidance(f"{query} matches {len(candidates)} nodes — read one with `yigraf show <id>`: "
                      f"{', '.join(candidates[:8])}{' …' if len(candidates) > 8 else ''}")
    _ranked_with_telemetry(repo, graph, config)  # recency/popularity + maturity verdict (R1)
    semantic = embeddings.semantic_scores(repo, graph, config, query)  # {} ⇒ lexical-only (M8 / v0)
    result = retrieval.context(graph, query, config, family=family, budget_tokens=budget,
                               semantic_match=semantic, root=repo, grounding=grounding,
                               show_scores=scores)
    _record_injection(repo, graph, result)  # a surfacing is a soft usage signal (sidecar, not the view)
    typer.echo(result.text, nl=False)
    # The footer carries the obligation counts because it is the one line a truncating caller keeps.
    # An agent that pipes `context` through `head` — a reasonable thing to do with a long packet —
    # cut off the ⚠ Stale block, which renders near the end, and missed real obligations for a whole
    # session. The counts are graph-wide on purpose: the blocks above are scoped to the query, so a
    # footer that agreed with them would only ever confirm what was already visible.
    typer.echo(f"[~{result.token_estimate} tokens · {result.nodes_rendered}/{result.nodes_total} "
               f"nodes shown{_obligation_footer(graph)}]")


def _obligation_footer(graph) -> str:
    """`` · ⚠ 3 drift · 2 stale`` for the context footer — empty when the graph is clean (design law #4)."""
    items = [i for i in compute_drift(graph) if i.kind in ("soft", "hard")]
    drifting = sum(1 for i in items if is_surfaced(graph, i))
    stale = len(items) - drifting
    bits = ([f"{drifting} drift"] if drifting else []) + ([f"{stale} stale"] if stale else [])
    return f" · ⚠ {' · '.join(bits)}" if bits else ""


def _show_archived(repo: Path, target: str) -> None:
    """Print an archived memory's claim and its successor, then exit 0 — or return, if it isn't one.

    The archive is out of the active graph on purpose (a retired belief must not surface in a scan), so
    this renders from the artifact rather than the graph, and says plainly that the node is retired.
    That is the whole difference between "kept for history" as a filesystem fact and as something a
    reader can actually reach (feedback-v5 E#1).
    """
    if not target.startswith("mem:"):
        return
    path = memory.find_archived_memory(repo, target)
    if path is None:
        return
    node = memory.read_memory(path)
    successor = node.superseded_by
    typer.echo(f"{node.id} — ARCHIVED (collected by `yigraf gc`; the artifact is kept at "
               f"{path.relative_to(Path(repo))})")
    typer.echo(f'  "{node.statement}"')
    if node.why:
        typer.echo(f"  why: {node.why}")
    if successor:
        typer.echo(f"  superseded by {successor} — `yigraf show {successor}` is the live belief.")
    else:
        typer.echo("  no successor recorded: it was collected as an abandoned proposed candidate "
                   "(never confirmed by a real encounter), not as superseded churn.")
    typer.echo("  It is out of the active graph, so `context` will not return it. To bring it back, "
               f"move the file back into yigraf/memory/.")
    raise typer.Exit(code=0)


@app.command()
def show(
    target: str = typer.Argument(..., help="A node id or unique prefix: mem:<id> | int:<slug> | task:<plan>/<n> | sym:<path>#<name> | file:<path>."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Read ONE node by id, in full and unbudgeted — the verb that closes the loop drift opens.

    Every warning yigraf prints hands you an id; this is what reads one. ``context`` cannot: it
    searches by meaning, so an id reaches the seeder as a bag of hex characters and comes back as
    whichever nodes happen to sit nearest, under a banner that is easy to skim past. Nothing here is
    ranked, truncated, or budgeted — a 2000-character ``--why`` prints whole, because that reasoning is
    the thing the node exists to survive ``/clear`` with.

    Beyond the frontmatter it answers the two questions a caller acting on a drift line actually has:
    which of this node's anchors are drifting *right now*, and which list each one lives in — a memory
    can carry the same symbol under both ``concerns`` and ``evidence``, and a different call clears each.
    """
    workspace = _require_workspace(repo)
    config = load_config(workspace / "config.yaml")
    graph, _ = graphdb.load_or_build(repo, config)
    _ranked_with_telemetry(repo, graph, config)  # so the shown maturity is the read-time verdict (R1)
    resolved, candidates = show_mod.resolve(graph, target)
    if resolved is None:
        if candidates:
            _guidance(f"{target} matches {len(candidates)} nodes — name one: "
                      f"{', '.join(candidates[:10])}{' …' if len(candidates) > 10 else ''}")
        # Before declaring the id unknown, look in the archive — `gc` promises "never delete, kept for
        # history", and that promise was true of the FILE and not of the ID (feedback-v5 E#1). An id
        # cited in prose outside the graph answered "no such node", which reads as *lost* rather than
        # *retired*, and sent a reader looking for a deletion that never happened.
        _show_archived(repo, target)
        _guidance(f'No node {target}. Find one by meaning with `yigraf context "<topic>"`, or by '
                  f"obligation with `yigraf drift` / `yigraf drift --stale` — both print ids.")
    typer.echo(show_mod.node_detail(graph, resolved, root=repo, config=config), nl=False)
    # A read IS a review-encounter (mem:033): reading a belief and leaving it standing is the same
    # un-superseded survival the edit hook books, so it feeds maturity exactly like an injection does.
    _record_injection(repo, graph, retrieval.ContextResult(
        text="", token_estimate=0, nodes_rendered=1, nodes_total=1, rendered=[resolved]))


def _verb_catalog() -> list[dict]:
    """Introspect the CLI into ``[{verb, summary, args, options}]`` — the source for the cheatsheet.

    Derived from the live click command tree, so it can never drift from the real verbs/flags (D#5).
    The universal ``--repo`` and click's ``--help`` are dropped (noise for an orchestrator prompt).
    Params are classified by ``param_type_name`` (``argument``/``option``) rather than isinstance —
    typer's ``TyperArgument``/``TyperOption`` don't subclass click's Argument/Option cleanly.
    """
    group = typer.main.get_command(app)
    verbs: list[dict] = []
    for name, cmd in sorted(group.commands.items()):
        if getattr(cmd, "hidden", False):
            continue
        summary = (cmd.help or "").strip().split("\n", 1)[0]
        args, options = [], []
        for p in cmd.params:
            if p.name == "repo" or "--help" in getattr(p, "opts", []):
                continue
            if getattr(p, "param_type_name", "") == "argument":
                args.append(f"<{p.name}>" if p.required else f"[{p.name}]")
            else:
                options.append({"flag": (p.opts or [f"--{p.name}"])[0],
                                "help": (p.help or "").strip(), "required": bool(p.required)})
        verbs.append({"verb": name, "summary": summary, "args": args, "options": options})
    return verbs


def _changelog_source() -> tuple[str, str] | None:
    """``(text, where)`` for the changelog — the copy inside the installed package, else the repo's own.

    The packaged copy is tried first *on purpose*: it is the one that describes the yigraf actually
    running. A developer working in this repo gets the working-tree file as a fallback, which is the
    same document one commit ahead.
    """
    try:
        from importlib.resources import files
        packaged = files("yigraf").joinpath("CHANGELOG.md")
        if packaged.is_file():
            return packaged.read_text(encoding="utf-8"), "the installed package"
    except (ImportError, OSError, ModuleNotFoundError):
        pass
    local = Path(__file__).resolve().parent.parent.parent / "CHANGELOG.md"
    if local.is_file():
        return local.read_text(encoding="utf-8"), str(local)
    return None


def _version_key(raw: str) -> tuple:
    """A sortable key for a ``1.7.1``-shaped version; non-numeric parts sort as 0 rather than raising."""
    parts = []
    for chunk in raw.strip().lstrip("v").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


@app.command()
def changelog(
    since: str = typer.Option(None, "--since", help="Only releases NEWER than this version (e.g. --since 1.5.1) — what an upgrade from it actually changed."),
    limit: int = typer.Option(3, "--limit", help="How many releases to print when --since is not given (0 = all)."),
) -> None:
    """Print yigraf's release notes — from the copy that ships inside the wheel (feedback-v5 C).

    An upgrade is the moment the notes are worth reading and the moment they are hardest to reach: the
    tool is installed, the repo is not, and a version that never reached PyPI leaves a gap no installed
    artifact can explain. ``--since <the version you were on>`` answers the only question an upgrader
    actually has — *what changed under me* — including across releases that were skipped.
    """
    found = _changelog_source()
    if found is None:
        _guidance("No changelog is available in this install. It ships inside the wheel from 1.8.0 on; "
                  "an older install predates that. The notes are also at "
                  "https://github.com/mansilla/yigraf/blob/main/CHANGELOG.md")
    text, where = found
    # Split on the `## [x.y.z]` release headings; anything before the first is the file's own preamble.
    chunks = re.split(r"^## \[", text, flags=re.MULTILINE)[1:]
    releases = [(c.split("]", 1)[0], "## [" + c.rstrip()) for c in chunks]
    if not releases:
        typer.echo(text)
        return
    if since:
        floor = _version_key(since)
        selected = [(v, body) for v, body in releases if _version_key(v) > floor]
        if not selected:
            newest = releases[0][0]
            _guidance(f"Nothing newer than {since} in the changelog — the newest release recorded is "
                      f"{newest}. (If you expected more, you may be reading an older install's copy: "
                      f"this one came from {where}, and reports itself as yigraf {__version__}.)")
        skipped = ""
        if len(selected) > 1:
            # The specific thing that made this ask: 1.5.2 and 1.6.0 never reached PyPI, so an upgrade
            # from 1.5.1 delivered four releases at once and nothing installed could say so.
            skipped = (f"  ({len(selected)} releases are between {since} and {__version__} — an upgrade "
                       f"can skip intermediate ones, and they all arrive at once.)")
        typer.echo(f"yigraf {__version__} — what changed since {since}:")
        if skipped:
            typer.echo(skipped)
        typer.echo("")
    else:
        selected = releases if limit <= 0 else releases[:limit]
    typer.echo("\n\n".join(body for _, body in selected))


@app.command()
def cheatsheet(
    as_json: bool = typer.Option(False, "--json", help="Emit as JSON (for an orchestrator to parse programmatically)."),
    preamble: bool = typer.Option(False, "--preamble", help="Print the session preamble THIS yigraf ships, to paste into a repo's yigraf/config.yaml."),
) -> None:
    """Emit the verb/flag list an orchestrator can paste into a subagent's prompt (D#5).

    Assume the agent calling yigraf guesses its surface: this is the compact, always-in-sync map of
    every verb, its arguments, and its flags. Text by default; ``--json`` for a machine consumer. Every
    verb also takes ``--repo <path>`` (default: cwd), omitted here for brevity.

    ``--preamble`` prints the shipped session preamble instead. It is here because the ``config.yaml``
    nudge (feedback-v6 F#1) has to hand over a command that produces the replacement text — telling
    someone their committed preamble is stale without a way to read the current one is guidance that
    cannot be followed (design law #1), and the text lives in the installed package, not in the repo.
    """
    if preamble:
        typer.echo(DEFAULT_SESSION_PREAMBLE.rstrip("\n"))
        return
    verbs = _verb_catalog()
    if as_json:
        typer.echo(json.dumps({"verbs": verbs}, indent=2))
        return
    lines = ["yigraf verbs — every verb also takes --repo <path> (default: cwd).", ""]
    for v in verbs:
        sig = " ".join(["yigraf", v["verb"], *v["args"]])
        lines.append(sig)
        lines.append(f"    {v['summary']}")
        for o in v["options"]:
            req = " (required)" if o["required"] else ""
            lines.append(f"      {o['flag']}{req}  {o['help']}")
        lines.append("")
    typer.echo("\n".join(lines).rstrip())


@app.command("status")
def status_cmd(
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
    as_json: bool = typer.Option(False, "--json", help="Emit the summary as JSON (for a host adapter)."),
    ctx_used: int = typer.Option(None, "--ctx-used", help="Context tokens in use (host/adapter-supplied; optional)."),
    ctx_limit: int = typer.Option(None, "--ctx-limit", help="Context window size in tokens (host/adapter-supplied; optional)."),
    color: bool = typer.Option(None, "--color/--no-color", help="Force/disable ANSI color + glyphs (default: auto — on for a TTY)."),
) -> None:
    """Print a host-agnostic status line (graph scale, drift, freshness, semantic, context) for an ambient UI.

    The agnostic backbone of the status surface (int:status-surface): a per-host adapter (e.g. a Claude
    Code ``statusLine`` running ``yigraf status --color``) renders this; the human sees graph health
    without spending the agent's context budget. ``--ctx-*`` are the one non-agnostic, host-fed datum.
    """
    workspace = _require_workspace(repo)
    config = load_config(workspace / "config.yaml")
    update.refresh(repo)  # throttled (≤1×/day) + fail-open: refresh the "newer yigraf on PyPI?" cache
    graph, _ = build_graph(repo, config)  # no telemetry overlay — keep graph byte-equal for freshness
    summary = status.compute_status(graph, repo, config, ctx_used=ctx_used, ctx_limit=ctx_limit)
    if as_json:
        typer.echo(json.dumps(summary.as_dict()))
        return
    # Auto: color a TTY (honoring NO_COLOR); a statusline pipes stdout, so it passes --color explicitly.
    use_color = color if color is not None else (sys.stdout.isatty() and not os.environ.get("NO_COLOR"))
    icon = status.SPIN[int(time.time()) % len(status.SPIN)] if use_color else None
    # color= keeps click from stripping ANSI on a non-TTY pipe — exactly the statusline's case.
    typer.echo(summary.render_line(color=use_color, icon=icon), color=use_color)
    # The knee note: the one-liner stays terse (percent + raw pair), and the full "what that percent is
    # of" sentence lands here — a human at a real terminal, never a piped statusline. Self-silencing
    # when the knee doesn't clamp (see ctx_note).
    note = summary.ctx_note()
    if note and sys.stdout.isatty():
        typer.echo(note)
    # Same split, for the view's state: the ambient line carries the token + its remedy, and the reason
    # it happened at all lands here, where there is room for a sentence (feedback-v5 A).
    fresh_note = summary.freshness_note()
    if fresh_note and sys.stdout.isatty():
        typer.echo(fresh_note)
    # A one-line "how to update" notice, only for a human at a real terminal (never a piped statusline).
    if summary.update and sys.stdout.isatty():
        typer.echo(f"⬆ yigraf {summary.update} is available — update with: "
                   f"uv tool upgrade yigraf  (or: pipx upgrade yigraf · pip install -U yigraf)")
    # The skill is the agent's instruction sheet and an upgrade does not touch it, so a stale one keeps
    # naming verbs that changed or are gone (feedback-v5 D). One line, only for a human at a terminal.
    if summary.skill_behind and sys.stdout.isatty():
        typer.echo(f"⬆ .claude/skills/yigraf/SKILL.md was written by yigraf {summary.skill_behind}, "
                   f"not {__version__} — an upgrade does not rewrite it. Refresh it with: "
                   f"yigraf install-claude-hooks")
    # The same two-copy hazard, one file over (feedback-v6 F#1): an `init` through 1.10.0 spliced the
    # preamble into the repo's committed config.yaml and the file value wins, so an upgrade cannot reach
    # it either — and on a host with no skill the preamble is the ONLY channel that teaches what "up to
    # date" means. Fires only on a byte-exact older default, never on a preamble the team rewrote (that
    # is the point of the file being committed), so it cannot nag anyone who made it theirs.
    # The remedy is a command, not a paste: `install` retires the copy under the same byte-exact guard
    # that raised this line, which is what stops the nudge from being a chore that scales with users.
    if summary.preamble_behind and sys.stdout.isatty():
        typer.echo(f"⬆ yigraf/config.yaml carries the session preamble shipped before {__version__} — "
                   f"an `init` before 1.11.0 spliced it in and the file wins, so upgrading the CLI "
                   f"cannot update it. Retire the copy with: yigraf install  (or keep it and make it "
                   f"yours — a preamble you edit is never touched or nudged again).")


def _claude_ctx(data: dict) -> tuple[Path, int | None, int | None]:
    """Derive ``(repo, ctx_used, ctx_limit)`` from Claude Code's statusline stdin event.

    Host-specific glue, NOT the agnostic core: ``compute_status`` never reads a transcript (mem:013),
    so this Claude-Code-shaped parse lives here in the adapter command. Token usage = the last
    transcript record's input + cache-read + cache-creation tokens; the window ceiling is model-derived
    (1M-context models report a larger limit). Stdlib ``json`` only — no ``jq``. A missing transcript or
    usage record ⇒ no ctx, and the bar simply renders without the gauge.
    """
    workspace = data.get("workspace") or {}
    repo = Path(workspace.get("current_dir") or data.get("cwd") or ".")
    model_id = ((data.get("model") or {}).get("id") or "")
    limit = 1_000_000 if "1m" in model_id.lower() else 200_000
    used: int | None = None
    tx = data.get("transcript_path")
    if tx and Path(tx).is_file():
        for line in Path(tx).read_text(encoding="utf-8").splitlines():
            try:
                usage = (json.loads(line).get("message") or {}).get("usage")
            except ValueError:
                continue
            if usage:  # keep the last usage record's running total
                used = (usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0)) or None
    return repo, used, (limit if used is not None else None)


@app.command("statusline")
def statusline_cmd(
    repo: Path = typer.Option(None, "--repo", help="Repo root; default: the event's cwd, else current dir."),
) -> None:
    """Claude Code statusline adapter: render the [Yigraf] bar with a context-window gauge.

    Wired by ``install-claude-hooks`` as the ``statusLine`` command. Reads Claude Code's session JSON
    on stdin, derives context-window occupancy from the transcript (host-specific; the agnostic core
    never reads a transcript — mem:013), and prints the colored bar. Dependency-free (stdlib ``json``,
    no ``jq``; no shell) and fail-open: any error prints nothing rather than breaking the statusline.
    """
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError):
        data = {}
    try:
        event_repo, ctx_used, ctx_limit = _claude_ctx(data)
        root = repo or event_repo
        workspace = root / WORKSPACE_DIRNAME
        if not workspace.is_dir():
            return  # ungoverned repo — stay silent (fail-open)
        update.refresh(root)  # throttled (≤1×/day) + fail-open: the "newer yigraf on PyPI?" check
        config = load_config(workspace / "config.yaml")
        graph, _ = build_graph(root, config)
        summary = status.compute_status(graph, root, config, ctx_used=ctx_used, ctx_limit=ctx_limit)
        icon = status.SPIN[int(time.time()) % len(status.SPIN)]
        typer.echo(summary.render_line(color=True, icon=icon), color=True)
    except Exception:  # noqa: BLE001 — an ambient surface must never break the host (design law #5)
        return


@app.command("mcp")
def mcp_cmd(
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root the server serves (default: cwd; or $YIGRAF_REPO)."),
) -> None:
    """Run yigraf as an MCP server (stdio) — the host-agnostic pull channel (int:mcp-server).

    Any MCP host (Codex, Antigravity, Cursor, Claude Code, …) can then pull the graph as tool calls:
    `context` (the governing slice) and `status`. See docs/mcp.md for per-host config. The MCP SDK is
    a core dependency, so this always runs.
    """
    from yigraf import mcp_server  # lazy: keep the SDK import off every other command's path
    raise typer.Exit(code=mcp_server.run(repo))


def _blast_reconcile_lines(graph, drifted_loci: set[str], exclude: set[str]) -> list[str]:
    """Governed nodes (intent/plan/memory) affected by a drifted symbol — the typed reverse-reachability
    ripple (:func:`relations.blast_radius`) beyond the edges the drift lines already name, minus any node
    a direct drift line already named (no double signal). One sorted line per node; empty ⇒ the caller
    prints nothing (silence is a feature, CLAUDE.md #4). This is the read-only consumer of the composition
    algebra: ``implements ∘ calls ⇒ depends_on`` lets a change ripple to a task that only *transitively*
    touches the drifted code — which the direct implements/concerns anchors never name.

    The ripple is NOT all-transitive: a depth-1 hit is a *direct* edge onto the drifted locus that
    :func:`compute_drift` did not report — it reports an edge only when that edge's OWN anchor stopped
    matching, so a node correctly anchored to the same symbol (or anchored under a different algo, or
    holding a dangling forward-reference) surfaces first here. ``exclude`` already drops anything a
    drift line named, for both drift-bearing relations (``DriftItem.task_id`` is the edge SOURCE — a
    task for ``implements``, a memory for ``concerns``), so this never double-signals. Each line states
    the composed relation as an arrow plus its hop count, so the agent can tell an asserted one-hop
    anchor from a derived multi-hop entailment without having to decode the heading.

    Only *soft* drift can ripple: hard drift means the symbol is gone from the graph, so
    :func:`relations.reach` returns nothing for it (no node ⇒ no incoming edges to walk back through).
    The direct hard-drift line is the whole signal there, by construction.

    Every line ends in "re-verify it still holds", so a node that *cannot* honestly be re-verified must
    not appear: :func:`~yigraf.drift.is_reverifiable` drops done tasks, superseded memories and archived
    intents. Without it the ripple silently undid the suppression the caller applies one call earlier —
    ``is_surfaced`` withholds a done task's ``implements`` drift precisely so the agent is never prompted
    to rubber-stamp a closed task (int:drift-done-suppression), and reverse reachability handed it
    straight back, re-framed as a reconcile prompt and double-counting what ``stale`` already reports.
    Measured on yigraf's own graph when this landed: 10 of 11 ripple lines were unactionable (7 done
    tasks, 3 superseded memories), i.e. the section was ~9% signal.
    """
    best: dict[str, relations.Reach] = {}
    for locus in drifted_loci:
        for r in relations.blast_radius(graph, locus):
            if r.target in exclude or not is_reverifiable(graph, r.target):
                continue
            prior = best.get(r.target)
            if prior is None or (r.depth, r.relation, r.path) < (prior.depth, prior.relation, prior.path):
                best[r.target] = r
    return [f"  ⚠ {tid} —{r.relation}→ {r.path[-1]} "
            f"({r.confidence.lower()}, {'direct' if r.depth == 1 else f'{r.depth} hops'})"
            f" — re-verify it still holds"
            for tid, r in sorted(best.items())]


def _report_drift_item(graph, item) -> None:
    """One drift item for the CLI report: the ids, the node's own claim, then the resolving advice.

    The claim line is what made this report usable. ``soft drift: mem:X → sym:Y (body changed since
    anchored)`` says *that* something moved, never whether the belief still holds — and deciding
    between ``reaffirm`` and ``supersede`` requires the belief's text, so the honest workflow was
    drift → read each → act, with no verb that could do the reading. Printing the title collapses two
    of the three steps; ``yigraf show <id>`` covers the rest.
    """
    if item.kind == "renamed":
        # Re-anchored in the GRAPH, which is recomputed from the body hash every build — so this line
        # names the verb that writes it into the artifact, before the next body edit ends the rescue.
        typer.echo(f"renamed (re-anchored in the graph, not yet in the artifact): {item.task_id}  "
                   f"{item.locator} ⇒ {item.new_locator} — settle with `yigraf gc --apply`")
        return
    typer.echo(f"{item.kind} drift · {item.relation}: {item.task_id} → {item.locator}")
    claim = (graph.nodes.get(item.task_id, {}).get("statement")
             or graph.nodes.get(item.task_id, {}).get("label", ""))
    if claim:
        typer.echo(f'    "{claim}"')
    typer.echo(f"    {retrieval.drift_tail(item)}")


@app.command()
def drift(
    path: Path = typer.Argument(Path("."), help="Repo root (default: current dir)."),
    stale: bool = typer.Option(False, "--stale", help="Also list STALE completions — done tasks whose implementing symbol drifted. These are what `yigraf status`'s `⚠ n stale` counts."),
) -> None:
    """Report drift: soft (body changed), hard (symbol gone), renames — and, with --stale, completions.

    Each item names the relation that drifted (``concerns`` vs ``grounded_by`` vs ``implements``), the
    claim at stake, and the one verb that resolves it — the same wording the edit hook injects
    (``retrieval.drift_tail``), because the two surfaces disagreeing about the same event is how an
    agent ends up running the form it already ran.
    """
    workspace = _require_workspace(path)
    config = load_config(workspace / "config.yaml")
    graph, _ = build_graph(path, config)  # build re-anchors renames in-memory first
    # Surface only what the agent can honestly act on: a done task's implements drift is provenance,
    # not a re-verify prompt, so it's withheld (int:drift-done-suppression via drift.is_surfaced).
    all_items = compute_drift(graph)
    items = [i for i in all_items if is_surfaced(graph, i)]
    stale_items = [i for i in all_items if is_stale_completion(graph, i)]

    if not items:
        # With --stale, say WHICH zero this is (feedback-v3 #13): "No drift." beside a status line
        # reading `behind` cost a field session six commands, because the one command whose job is
        # to disambiguate answered with the ambiguous word.
        typer.echo("No drift, and no stale completions." if stale and not stale_items else "No drift.")
        # …but `status` may simultaneously report `⚠ n stale`, which reads as a contradiction unless
        # you already know stale is deliberately withheld from the agent-facing drift signal. A count
        # nothing can print is a dead end: name it, and name the flag that lists it.
        if stale_items and not stale:
            typer.echo(f"(⚠ {len(stale_items)} stale completion(s) not shown — `yigraf drift --stale` "
                       f"lists them. This is what `yigraf status`'s `⚠ n stale` counts.)")
    for item in items:
        _report_drift_item(graph, item)

    # Group by shared locus (feedback-v3 #12): a flat list of per-id tails reads as one command per
    # memory — the field ran FOURTEEN when four locus-form calls covered them. Nothing new is built;
    # the report just says what the locus form already does, with measured concentration (anchors per
    # symbol run 20, 7, 7, 6, 5 at the top of a real repo) turning a wall into one decision per locus.
    by_locus: dict[str, list[str]] = {}
    for item in items:
        if item.relation == "concerns" and item.kind == "soft":
            by_locus.setdefault(item.locator, []).append(item.task_id)
    grouped = {loc: ids for loc, ids in by_locus.items() if len(ids) > 1}
    if grouped:
        typer.echo("")
        typer.echo("Grouped (re-verify the locus once; one command then covers its memories):")
        for loc, ids in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            typer.echo(f"  {len(ids)} memories concern {loc} — once re-verified, "
                       f"`yigraf reaffirm {loc}` clears {', '.join(sorted(ids))}.")

    if stale and stale_items:
        typer.echo("")
        typer.echo("STALE completions (the work shipped; its evidence moved):")
        for item in stale_items:
            typer.echo(retrieval._stale_line(item).lstrip().removeprefix("⚠ "))
    elif items and stale_items and not stale:
        typer.echo("")
        typer.echo(f"(⚠ {len(stale_items)} stale completion(s) not shown — `yigraf drift --stale`.)")

    if not items:
        return

    # Beyond the edges the lines above named: which governed nodes are reachable back from a drifted
    # symbol (a task implementing code that *calls* it, a memory concerning its container)? Typed
    # reverse reachability — each line carries its own hop count, so the heading stays honest about
    # mixing direct and derived hits. Additive + gated: nothing prints without cross-family edges.
    ripple = _blast_reconcile_lines(
        graph,
        {i.locator for i in items if i.kind in ("soft", "hard")},
        exclude={i.task_id for i in items},
    )
    if ripple:
        typer.echo("")
        typer.echo("also affected (verify these too):")
        for line in ripple:
            typer.echo(line)

    # The same verb fork the edit hook carries (retrieval.VERB_FORK — one wording, both surfaces): this
    # report is a drift moment too, and until now it named no verb at all. Only when a decision drifted;
    # an implements-only report needs re-`link`, not this fork.
    if any(item.relation == "concerns" for item in items):
        typer.echo("")
        typer.echo(retrieval.VERB_FORK)

    # The CI gate is SURFACED SOFT/HARD DRIFT, deliberately not every signal this command reports
    # (feedback-v6 F#3 — until now the one line here with no comment). A pending rename is settled by
    # `gc --apply`, which REWRITES committed artifacts: gating on it would demand a
    # mutate-restage-recommit cycle on every rename, which is how a pre-commit hook gets `--no-verify`d.
    # A stale completion exits 0 for the same reason it is not drift — the anchor is fine, the
    # completion is what is in doubt. Both are counted by `yigraf status --json`, which is the gate for
    # a caller that wants them; SKILL.md §4 says so, because a gate whose coverage is unstated is read
    # as covering everything the command prints.
    if any(item.kind in ("soft", "hard") for item in items):
        raise typer.Exit(code=1)


@app.command()
def conflicts(
    path: Path = typer.Argument(Path("."), help="Repo root (default: current dir)."),
) -> None:
    """List open knowledge-conflicts — the pairs `status`'s `⚠ n conflict` counts, with resolving verbs.

    The third re-verify signal gets the same listing surface as the other two (`drift`,
    `drift --stale`): a count no command could print was a dead end — the field had to call
    `detect_conflicts` from Python to learn what its own warning meant, and every resolving verb
    (`reconcile` / `supersede` / `dispute`) takes two ids that nothing handed over (feedback-v3 #1).
    Each finding names the pair, the shared anchor, the cosine, and which side provenance prefers —
    the same wording the Stop-hook notice uses (`obligations._conflict`), because two surfaces
    disagreeing about one event is how an agent ends up distrusting both. Derived, never stored;
    exits non-zero when conflicts stand, so CI can gate on it exactly like `drift`.
    """
    from yigraf.contradiction import detect_conflicts
    from yigraf.embeddings import load_index

    workspace = _require_workspace(path)
    config = load_config(workspace / "config.yaml")
    graph, _ = build_graph(path, config)
    index = load_index(path, config)
    found = detect_conflicts(graph, path, config, index=index)
    if not found:
        typer.echo("No open conflicts." if index is not None else
                   "No open conflicts — but there is no embedding index, so the cosine sweep "
                   "contributes nothing and only nominated disputes could have been listed. "
                   "`yigraf build` creates the index.")
        return
    typer.echo(f"{len(found)} open conflict(s) — each needs a verdict "
               f"(`reconcile` = compatible · `supersede` = one side won · `dispute` = make it durable):")
    for c in found:
        typer.echo(obligations._conflict(c, graph).render())
    raise typer.Exit(code=1)


def _for_the_wire(assertion, repo: Path, session: str):
    """Complete an assertion's provenance envelope for the online ingest gate.

    The two substrates want different things and both are right. The git-file substrate records only
    what an *authored artifact* honestly knows (``source``, and an ``origin`` if given) — a committed
    markdown file cannot know the sha of the commit that will contain it. The online log demands full
    attribution (``REQUIRED_PROVENANCE_FIELDS``) because it is a shared, signed audit trail. The gap is
    real, so it is closed here, at the transport boundary, rather than by weakening either side.

    Nothing is invented: ``session`` identifies this sync run, ``commit_sha`` is the HEAD the push went
    out from, ``ts`` is the push time, and ``model`` is whatever the artifact recorded — falling back to
    an explicit ``unattributed`` rather than a plausible-looking guess. ``actor`` is deliberately absent:
    the server stamps it from the authenticated principal and a client claim would be meaningless.
    Provenance is not part of the content-addressed id (mem:063), so completing it here cannot change
    which node the assertion folds into.
    """
    from dataclasses import replace

    record = dict(assertion.provenance[0]) if assertion.provenance else {}
    head = counters._head_sha(repo)
    record.setdefault("source", "cli")
    record.setdefault("session", session)
    record.setdefault("model", record.get("source") or "unattributed")
    record.setdefault("commit_sha", head or "uncommitted")
    record.setdefault("ts", _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"))
    return replace(assertion, provenance=[record])


def _online_settings(repo: Path, config: dict) -> tuple[str, str, Path]:
    """``(project, remote, replica_path)`` for a workspace configured for the shared log, or guidance.

    The token is read from the environment, never the config: ``config.yaml`` is committed.
    """
    online = config.get("online") or {}
    project, remote = online.get("project"), online.get("remote")
    if not project or not remote:
        absent = [f"online.{k}" for k, v in (("project", project), ("remote", remote)) if not v]
        missing = " and ".join(absent) + (" are" if len(absent) > 1 else " is")
        _guidance(
            f"This workspace isn't connected to a shared log — {missing} unset in "
            f"yigraf/config.yaml.\nDon't fill them in by hand: generate a link code in the web console "
            f"(a project's Machines tab) and run `yigraf online <the URL>`, which redeems it, checks "
            f"that this repo and that project match, and writes all of this for you. Until then yigraf "
            f"works fully offline.")
    replica = Path(repo) / "yigraf" / (online.get("replica") or "cache/replica.db")
    return project, remote, replica


def _auth_guidance(exc, remote_url: str, project: str) -> str:
    """Name what the server refused, and the one thing that fixes it.

    Every case here is a *credential or membership* problem, which is why none of them is
    :class:`~yigraf.sync.RemoteUnavailable`: retrying changes nothing, so telling the caller to wait
    would be a lie. What they need instead is the specific correction, per design law #1.

    ``404`` is deliberately ambiguous and must stay that way in the message: the server answers it
    identically for "no such project" and "you are not a member", so that membership is not an
    existence oracle. Guessing one of the two here would re-leak what the route refused to say.
    """
    code = getattr(exc, "code", None)
    if code == 401:
        return (f"{remote_url} rejected your credential (401). ${TOKEN_ENV} is set but the server "
                f"doesn't accept it — it's expired, revoked, or meant for a different host. Check the "
                f"value, or re-issue a token for this workspace, then re-run `yigraf sync`.")
    if code == 403:
        return (f"{remote_url} authenticated you but refused this operation on '{project}' (403) — "
                f"your access is read-only where a write was needed. Ask a project owner to raise "
                f"your role, or point `online.project` at one you can write to.")
    if code == 404:
        return (f"{remote_url} has no project '{project}' that you can see (404) — either it doesn't "
                f"exist or your credential isn't a member of it, and the server deliberately doesn't "
                f"say which. Check `online.project` in yigraf/config.yaml for a typo, and that this "
                f"credential belongs to the account the project was shared with.")
    return (f"{remote_url} refused the request ({code} {getattr(exc, 'reason', '')}).".rstrip() +
            f" This isn't a transient failure, so re-running alone won't clear it — check "
            f"`online.remote`/`online.project` in yigraf/config.yaml and your ${TOKEN_ENV}.")


def _patch_online_config(workspace: Path, values: dict[str, str | None]) -> None:
    """Write the ``online:`` keys into ``yigraf/config.yaml`` in place, preserving the file.

    Round-tripping through a YAML dumper would be one line and would strip every comment out of a
    committed, human-authored file — so this patches the block textually instead, keeping each key's
    trailing comment and adding any key an older workspace predates.
    """
    path = workspace / "config.yaml"
    from yigraf.config import DEFAULT_CONFIG_YAML

    text = path.read_text(encoding="utf-8") if path.exists() else DEFAULT_CONFIG_YAML
    if not re.search(r"^online:\s*$", text, re.M):
        text = text.rstrip("\n") + "\n\nonline:\n"
    for key, value in values.items():
        rendered = "" if value is None else str(value)
        pattern = re.compile(rf"^([ \t]+{key}:)([^#\n]*)(#.*)?$", re.M)
        if pattern.search(text):
            text = pattern.sub(lambda m: f"{m.group(1)} {rendered}".rstrip()
                               + (f"  {m.group(3)}" if m.group(3) else ""), text, count=1)
        else:  # a workspace older than this key: append it inside the block
            text = re.sub(r"^online:\s*$", f"online:\n  {key}: {rendered}".rstrip(), text,
                          count=1, flags=re.M)
    path.write_text(text, encoding="utf-8")


@app.command()
def online(
    code: str = typer.Argument(None, help="The link URL you were given (or a bare ygl_ code)."),
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
    remote: str = typer.Option(None, "--remote", help="Server base URL, when passing a bare code."),
    label: str = typer.Option(None, "--label", help="Name this machine in the project's machine list."),
    force: bool = typer.Option(False, "--force", help="Override a repo mismatch / re-point the replica."),
) -> None:
    """Bring this workspace online: redeem a link code for a machine token and bind to the project.

    Generate the code in the web console (a project's Machines tab) while logged in, and paste the URL
    here. That is the whole of the CLI's identity story — redeem once, keep the token it returns. There
    is no login here, no browser, no callback port: a person's accounts, projects and invitations all
    live in the browser, and `yigraf` never meets a stranger.

    Run with no argument to report the current binding instead — project, remote, identity, and
    whether the credential still works.

    Before anything is written, three things are checked. **Repo identity**: the project's root-commit
    SHA against this one, because the shared graph is full of implements/concerns edges anchored to code
    symbols, and binding to a project about a different codebase leaves every one of them dangling — the
    graph still folds, still renders, and is silently meaningless. **Wire version**: that this client and
    that server would round-trip each other's events at all. **Replica state**: that the local mirror
    isn't already carrying a cursor for a different project. Only then is the code spent.
    """
    from yigraf import __version__ as engine_version
    from yigraf import online as online_mod
    from yigraf.sync import WIRE_VERSION

    workspace = _require_workspace(repo)
    config = load_config(workspace / "config.yaml")
    settings = config.get("online") or {}

    if not code:
        _report_binding(repo, settings)
        return

    try:
        base_url, link_code = online_mod.parse_link(code, remote)
    except online_mod.LinkError as exc:
        _guidance(exc.guidance)

    bound_project = settings.get("project")
    if bound_project and not force:
        try:
            info_project = online_mod.preflight(base_url, link_code).get("project")
        except online_mod.LinkError as exc:
            _guidance(exc.guidance)
        if info_project != bound_project:
            _guidance(
                f"This workspace is already bound to '{bound_project}'. Binding it to "
                f"'{info_project}' would strand the existing replica, whose cursor is scoped per "
                f"project.\nRe-run with --force if that's what you want (the replica is renamed, "
                f"never deleted).")

    try:
        info = online_mod.preflight(base_url, link_code)
        fingerprint = online_mod.repo_fingerprint(repo)
        online_mod.check_compatibility(info, fingerprint, force=force)
        replica = Path(repo) / "yigraf" / (settings.get("replica") or "cache/replica.db")
        moved = online_mod.check_replica(replica, bound_project, settings.get("remote"),
                                         info["project"], base_url, force=force)
        result = online_mod.redeem(
            base_url, link_code, repo_fingerprint=fingerprint,
            label=label or online_mod.default_label(repo),
            engine_version=engine_version, wire_version=WIRE_VERSION)
    except online_mod.LinkError as exc:
        _guidance(exc.guidance)

    # Order matters, and it is not arbitrary: a code is spent the moment it is redeemed, so the
    # credential is written FIRST. A token stored without config is recoverable (re-run and it resumes
    # from the stored credential); config written without a token is a dead binding and a dead code.
    creds = online_mod.store_credential(base_url, {
        "token": result["token"], "actor": result["actor"],
        "email": result.get("email"), "project": result["project"]})
    _patch_online_config(workspace, {
        "project": result["project"], "remote": base_url,
        "repo_fingerprint": result.get("repo_fingerprint") or fingerprint or ""})

    if moved:
        typer.echo(f"Moved the previous replica aside to {moved.name} (nothing was deleted).")
    if fingerprint is None:
        typer.echo("⚠ Couldn't fingerprint this repository (shallow clone, or not a git repo), so the "
                   "project's repo identity was left unclaimed. yigraf can't warn you later if this "
                   "config lands in a different repo.")
    typer.echo(f"Linked '{result['project']}' at {base_url} as {result.get('email') or result['actor']} "
               f"({result['role']}). Token saved to {creds}.")
    typer.echo("Pulling the project's graph…")
    sync(repo=repo, dry_run=False)


def _report_binding(repo: Path, settings: dict) -> None:
    """`yigraf online` with no code answers "am I connected?" — the other half of the command."""
    from yigraf import online as online_mod

    project, remote_url = settings.get("project"), settings.get("remote")
    if not (project and remote_url):
        typer.echo("This workspace isn't online. Generate a link code in the web console (a project's "
                   "Machines tab) and run `yigraf online <the URL>`. Until then yigraf works fully "
                   "offline.")
        return
    token = online_mod.resolve_token(remote_url, TOKEN_ENV)
    typer.echo(f"Project:  {project}\nRemote:   {remote_url}")
    if settings.get("repo_fingerprint"):
        typer.echo(f"Repo:     root commit {str(settings['repo_fingerprint'])[:12]}")
    if not token:
        typer.echo("Identity: no credential — export $" + TOKEN_ENV + " or re-run "
                   "`yigraf online <url>` with a fresh link code.")
        return
    try:
        me = online_mod.whoami(remote_url, token)
    except online_mod.LinkError as exc:
        typer.echo(f"Identity: unverified — {exc.guidance}")
        return
    typer.echo(f"Identity: {me.get('email') or me.get('actor')} ({me.get('role') or 'unknown role'})"
               + (f" as {me['label']}" if me.get("label") else ""))


@app.command()
def whoami(
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
) -> None:
    """Which identity is this workspace pushing as?

    One call to the server, so the answer never requires reading a graph — and it is the fastest way to
    tell "my token is wrong" apart from "my project name is wrong", which otherwise look identical.
    """
    from yigraf import online as online_mod

    workspace = _require_workspace(repo)
    settings = (load_config(workspace / "config.yaml").get("online") or {})
    remote_url = settings.get("remote")
    if not remote_url:
        _guidance("This workspace isn't online — run `yigraf online <link-url>` first.")
    token = online_mod.resolve_token(remote_url, TOKEN_ENV)
    if not token:
        _guidance(f"No credential for {remote_url}. Export ${TOKEN_ENV}, or run "
                  f"`yigraf online <link-url>` with a fresh link code.")
    try:
        me = online_mod.whoami(remote_url, token)
    except online_mod.LinkError as exc:
        _guidance(exc.guidance)
    # The answer is worth keeping, not just printing: while the replica does not know this workspace's
    # own name, every unpushed edit of its own keeps reporting as divergence
    # (OnlineLog.pending_local_revisions). `sync` learns it too, but only a push or a pull earns the
    # right to; this command is the read-only way to answer the same question, so a workspace that has
    # only ever pulled can clear a phantom divergence count without pushing anything.
    _remember_actor(repo, settings, me.get("actor"))
    typer.echo(f"{me.get('email') or me.get('actor')} — {me.get('role') or 'no role'} on "
               f"{me.get('project') or settings.get('project')} at {remote_url}"
               + (f" (machine: {me['label']})" if me.get("label") else ""))


def _remember_actor(repo: Path, settings: dict, actor: str | None) -> None:
    """Record the principal the authority reports as this workspace, on its replica. Best-effort: an
    identity yigraf failed to store costs precision in the divergence report, never the command."""
    project = settings.get("project")
    if not actor or not project:
        return
    replica = Path(repo) / "yigraf" / (settings.get("replica") or "cache/replica.db")
    if not replica.exists():
        return
    try:
        from yigraf.onlinelog import SqliteAssertionStore

        SqliteAssertionStore(replica).set_actor(project, actor)
    except Exception:  # noqa: BLE001 - see the docstring; never fail a read command over bookkeeping
        pass


def _structure_manifest(repo: Path, graph=None) -> list[dict]:
    """This tree's structure hashes, from the graph a caller already built (or a fresh read of it)."""
    from yigraf.sync import structure_manifest

    if graph is None:
        config = load_config(_require_workspace(repo) / "config.yaml")
        graph, _ = graphdb.load_or_build(repo, config)
    return structure_manifest(graph)


#: The server names each refusal; this only decides how to spell it for the person at the terminal.
_STRUCTURE_GUIDANCE = {
    "dirty_tree": "the server refused a snapshot of an uncommitted tree. Commit or stash, then re-run "
                  "with --push-structure.",
    "repo_mismatch": "this project's anchors belong to a different repository, so nothing was stored.",
    "empty_manifest": "the manifest had no hashable structure nodes — run `yigraf build` first.",
    "manifest_too_large": "the manifest is larger than this server accepts.",
    "snapshot_wire_unsupported": "this server doesn't speak this snapshot format — upgrade one of the "
                                 "two.",
}


def _push_structure(repo: Path, graph, project: str, remote_url: str, token: str) -> str:
    """Send the code-structure manifest, and return the line to print about it.

    Fail-open to a *reported* failure, never a raised one (design law #5). The assertion sync has
    already succeeded and printed by the time this runs, so an exception here would turn a completed
    sync into a crash — the wrong trade for an add-on that only affects what a console can render.

    The dirty-tree refusal is made locally as well as remotely. The server has the final say (drift
    computed against edits only you have is not a fact about the project, so it must refuse), but
    finding out before sending a whole manifest is the difference between guidance and a round trip.
    """
    from yigraf.online import repo_fingerprint, tree_state
    from yigraf.sync import STRUCTURE_WIRE_VERSION, HttpRemote, RemoteUnavailable, StructureRefused

    try:
        commit, branch, dirty = tree_state(repo)
        if not commit:
            return "⚠ Structure not sent: this isn't a git repository, and a snapshot has to name a tree."
        if dirty:
            return ("⚠ Structure not sent: your tree has uncommitted changes, and drift computed "
                    "against edits only you have is not a fact about the project. Commit or stash, "
                    "then re-run with --push-structure.")
        nodes = _structure_manifest(repo, graph)
        if not nodes:
            return "⚠ Structure not sent: no code structure was extracted from this tree."

        payload = {
            "wire_version": STRUCTURE_WIRE_VERSION, "commit": commit, "dirty": False,
            "branch": branch,
            "generated_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
                                         .isoformat().replace("+00:00", "Z"),
            "repo_fingerprint": repo_fingerprint(repo),
            "tool": f"yigraf/{__version__}", "nodes": nodes,
        }
        body = HttpRemote(remote_url, token).put_structure(project, payload)
    except StructureRefused as exc:
        return f"⚠ Structure not sent: {_STRUCTURE_GUIDANCE.get(exc.code, f'the server refused it ({exc.code}).')}"
    except RemoteUnavailable as exc:
        return (f"⚠ Structure not sent: {exc}. The sync itself stands — re-run with --push-structure "
                f"when the remote is back.")
    except Exception as exc:  # noqa: BLE001 - see the docstring: never retract a sync that succeeded
        return f"⚠ Structure not sent: {exc}"
    return (f"Structure: {body.get('symbols', len(nodes))} nodes at "
            f"{body.get('short_commit', commit[:7])} — drift and stale are now visible in the console.")


@app.command()
def sync(
    repo: Path = typer.Option(Path("."), "--repo", help="Repo root (default: current dir)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would move without writing anything."),
    push_structure: bool = typer.Option(
        False, "--push-structure",
        help="Also send this tree's code-structure hashes, so the console can compute drift."),
) -> None:
    """Reconcile this workspace with the shared log: pull the team's assertions, push yours.

    git-shaped, and conflict-free by construction. **Pull** fetches the delta since the replica's
    cursor and cryptographically re-derives the Merkle links over it before folding anything in, so a
    server that dropped, reordered, or forged an event is caught client-side. **Push** sends every
    assertion you authored that the log has not seen, in causal order so parents land first.

    A push is never rejected for disagreeing. Assertions are content-addressed and the fold re-derives
    belief from the whole set, so merging two logs is a commutative set-union — there is no
    last-writer-wins and nothing is overwritten. Two people asserting the *same* claim collapse to one
    node; two people asserting *opposed* claims both land, and the pair surfaces afterwards as a
    knowledge-conflict for a principal (`yigraf status`, then `reconcile` / `supersede` / `dispute`).
    The only writes the server refuses are structurally malformed ones, and it says how to fix them.

    Reads never touch the network: the replica is local, so `context`/`status`/hooks stay fast and work
    offline. Only assertions cross the wire — your source never does.

    `--push-structure` additionally sends this tree's code-structure *hashes* (locator + body hash, no
    source), which is the one thing the shared log cannot carry: structure is derived from source, not
    asserted, so without it a server folding the log has no current hash to compare a stamped anchor
    against and cannot compute drift at all. It runs last, after the rebuild that produces the hashes,
    and never retracts a sync that already succeeded — a refused or unreachable snapshot is reported
    and the sync still stands.
    """
    _require_workspace(repo)
    config = load_config(_require_workspace(repo) / "config.yaml")
    project, remote_url, replica_path = _online_settings(repo, config)

    from yigraf import online as online_mod

    token = online_mod.resolve_token(remote_url, TOKEN_ENV)
    if not token:
        _guidance(f"No credential for {remote_url} — `yigraf sync` needs one, and there is no "
                  f"${TOKEN_ENV} in the environment and nothing stored for this host.\n"
                  f"Generate a link code in the web console (a project's Machines tab) and run "
                  f"`yigraf online <the URL>`, which redeems it and binds this workspace. For CI, "
                  f"reveal a token in the console instead and export it as ${TOKEN_ENV}.")

    # The one check the bind-time check cannot make: a config.yaml copied into a DIFFERENT repository.
    # It is nearly free (one `git rev-list`), and it catches a failure that is otherwise silent — the
    # assertions would push fine and anchor to code that isn't here.
    expected = (config.get("online") or {}).get("repo_fingerprint")
    if expected:
        actual = online_mod.repo_fingerprint(repo)
        if actual and actual != expected:
            _guidance(
                f"This workspace's config is bound to a different repository: '{project}' expects root "
                f"commit {str(expected)[:12]}, and this repo's is {actual[:12]}.\n"
                f"Nothing was pushed. The shared graph's implements/concerns edges are anchored to that "
                f"repo's symbols, so pushing from this one would file assertions against code that "
                f"isn't here. If you copied yigraf/config.yaml between repos, run `yigraf online "
                f"<link-url>` here to bind this workspace properly.")

    import urllib.error

    from yigraf.filelog import FileLog
    from yigraf.onlinelog import IngestRejected, SqliteAssertionStore
    from yigraf.sync import HttpRemote, RemoteUnavailable, SyncError, push_assertion
    from yigraf.sync import sync as sync_replica

    replica_path.parent.mkdir(parents=True, exist_ok=True)
    store = SqliteAssertionStore(replica_path)
    remote = HttpRemote(remote_url, token)

    # Learn this workspace's own name if it doesn't know it yet. A push teaches it (the authority stamps
    # `actor` and `push_assertion` keeps it), but a workspace that has only ever pulled — or that
    # predates the identity table — would stay anonymous, and while it is anonymous every unpushed edit
    # of its own keeps reporting as divergence (OnlineLog.pending_local_revisions). One call yigraf
    # already owns, on a token it already has. Best-effort: an unreachable /me must not stop a sync.
    if store.get_actor(project) is None:
        try:
            actor = (online_mod.whoami(remote_url, token) or {}).get("actor")
            if actor:
                store.set_actor(project, actor)
        except Exception:  # noqa: BLE001 - identity is an optimization; syncing without it still works
            pass

    try:
        local = list(FileLog(repo).iter_assertions_in_causal_order())
        if dry_run:
            head = remote.head(project)
            cursor_seq, _ = store.get_cursor(project)
            known = store.known_ids(project)
            outgoing = [a for a in local if a.id not in known]
            structure = (f" Structure: {len(_structure_manifest(repo))} nodes would be sent."
                         if push_structure else "")
            typer.echo(f"{project} @ {remote_url}: remote head seq {head.seq}, local cursor {cursor_seq} "
                       f"⇒ {max(0, head.seq - cursor_seq)} to pull, {len(outgoing)} to push. "
                       f"Nothing written (--dry-run).{structure}")
            return

        result = sync_replica(store, remote, project)

        # Push after pulling, git-style: everything the log hasn't seen, in causal order so parents
        # land first. Identity is the assertion ``id`` (content-addressed, excludes provenance —
        # mem:063), NOT the event key, because the server stamps ``actor`` and re-signs on ingest.
        #
        # This is correct only because EVERY family's id is content-addressed. It was not: intents and
        # tasks keyed on a slug / positional locator while their status, state and implements anchors
        # lived in the mutable body, so once a locator had been pushed this filter skipped every later
        # edit as already-known — re-anchors, completions and `--status satisfied` silently never
        # propagated. Revisioned ids (yigraf.filelog) make an edited body a new id, and this line right.
        known = store.known_ids(project)
        outgoing = [a for a in local if a.id not in known]
        session = f"sync-{uuid.uuid4().hex[:12]}"
        pushed, deferred = 0, 0
        for index, assertion in enumerate(outgoing):
            try:
                push_assertion(store, remote, project, _for_the_wire(assertion, repo, session))
                pushed += 1
            except IngestRejected as exc:  # design law #1: a rejected write teaches the fix
                typer.echo(f"⚠ {assertion.id} rejected by the server: {exc}")
            except RemoteUnavailable as exc:
                # The remote went away mid-push. Stop rather than hammer it — every remaining assertion
                # would fail the same way — and let the file log carry them: `outgoing` is re-derived
                # from it on every run, so these go out on the next `yigraf sync` with no queue to keep
                # (push_assertion's docstring). Everything already pushed stays pushed.
                deferred = len(outgoing) - index
                typer.echo(f"⚠ lost the remote mid-push ({exc}) — {pushed} pushed, {deferred} deferred.")
                break
        # Write-through leaves the cursor behind its own append; a second pull advances it. Skipped when
        # the remote just dropped — re-polling it would only turn a clean partial sync into a hard exit.
        if pushed and not deferred:
            result = sync_replica(store, remote, project)
        # Read the log's order out before the store closes — it is what says whose turn a conflict is.
        events, local_ids = store.iter_events(project), {a.id for a in local}
    except SyncError as exc:
        # A broken chain is a genuine stop, not a recoverable condition: the replica is NOT advanced,
        # so re-running after the server is fixed resumes cleanly from the last verified cursor.
        typer.echo(f"Sync aborted — the pulled delta failed chain verification: {exc}\n"
                   f"The replica was left untouched. This means the remote's log is inconsistent with "
                   f"what this client last verified; nothing local is lost.")
        raise typer.Exit(code=1) from exc
    except RemoteUnavailable as exc:
        # Unreachable on head/pull — i.e. before any push was attempted. Recoverable weather, so it
        # exits 0 with guidance (a non-zero exit here would train an agent to stop calling sync over a
        # dropped wifi connection). Nothing is lost and nothing needs queueing: reads already run off
        # the local replica, and unpushed assertions sit in the git-committed file log.
        _guidance(f"Couldn't reach {remote_url}: {exc}\n"
                  f"Nothing was lost — yigraf keeps working fully offline against the local replica, "
                  f"and anything you've authored stays in the committed file log, so the next "
                  f"`yigraf sync` sends it once the remote is back.")
    except urllib.error.HTTPError as exc:
        # A credential/authorization refusal. HttpRemote deliberately re-raises a non-429 4xx as itself
        # (it fails identically on every retry, so it must not read as "try again later") — but "as
        # itself" is a transport contract, not a user-facing one. Unhandled here it reached the operator
        # as a Typer traceback, which is precisely the error that teaches abandonment (design law #1).
        # So it lands as guidance at exit 0, the same contract as the missing-token and unset-config
        # gaps above: all three are one misconfiguration the caller can fix and re-run.
        _guidance(f"{_auth_guidance(exc, remote_url, project)}\n"
                  f"Nothing was pushed or pulled, and nothing local was touched — the replica and the "
                  f"committed file log are unchanged, so `yigraf sync` resumes once the credential is "
                  f"sorted out.")
    finally:
        store.close()

    graph = _rebuild(repo)
    typer.echo(f"Synced {project}: pulled {result.pulled}, pushed {pushed} — head seq {result.head.seq} "
               f"({result.head.head_hash[:12]})." +
               (f" {deferred} deferred to the next sync (the remote dropped)." if deferred else ""))
    typer.echo("Their assertions now anchor to your code: run `yigraf drift` to see what your edits "
               "have moved under, and `yigraf status` for open conflicts.")
    if push_structure:
        typer.echo(_push_structure(repo, graph, project, remote_url, token))
    _report_divergence(repo, graph)
    notice = _responsibility_notice(repo, config, graph, events, local_ids)
    if notice:
        typer.echo(notice)


def _artifacts_are_committed(repo: Path) -> bool:
    """Does git track this workspace's authored artifacts? Fail-open to ``True`` (assume the safe world).

    Design law #6's answer to two workspaces editing one artifact is "the local file wins, and git
    merges the markdown." The second clause is an *assumption about the repo*, and yigraf cannot make it
    true — a repo may gitignore ``yigraf/`` (yigraf's own does), and then the merge point does not exist.
    Only the guidance changes on this, never the fold's verdict.
    """
    try:
        out = subprocess.run(["git", "ls-files", "--", str(WORKSPACE_DIRNAME)], cwd=repo,
                             capture_output=True, text=True, timeout=5)
        # A non-zero exit (not a repo, git unusable) is "I don't know" — and `git ls-files` reports that
        # by exiting 128 with an EMPTY stdout, i.e. indistinguishable from a real "tracks nothing" unless
        # the returncode is checked. Reading only stdout would turn every non-git directory into a
        # confident warning that the user has lost data.
        if out.returncode != 0:
            return True
        return bool(out.stdout.strip())
    except Exception:  # noqa: BLE001 - no git binary, a timeout ⇒ don't scare the caller
        return True


def _report_divergence(repo: Path, graph) -> None:
    """Name the locators another workspace holds a different revision of (extract._fold_replica).

    Silent when there are none (design law #4). This is the one moment the news is actionable — the
    divergence is *created* by the pull that just happened — and it is deliberately not an error: the
    build is correct either way, your working tree won, and nothing was lost locally.

    What is lost is the *other* copy, and only when the artifacts aren't committed. So the guidance
    forks on that: with git tracking the artifacts this is a routine merge and yigraf should not invent a
    ceremony for it; without, yigraf is the only thing that will ever mention it.
    """
    diverged = list(graph.graph.get("diverged") or ())
    if not diverged:
        return
    shown = diverged[:10]
    # Still deliberately NOT "another principal". An unpushed edit of your own no longer lands here once
    # the workspace knows its own name (pending_local_revisions, learned from the actor the authority
    # stamps on a push) — but a workspace that has never pushed has never been told it, and there the old
    # ambiguity stands: the log's newest word on that locator really is the older revision, and offline
    # yigraf cannot say whose. Both cases are honestly "the log disagrees with your file and you have not
    # replaced it there", and the push hint still separates them without yigraf having to guess.
    typer.echo(f"\n⚠ {len(diverged)} locator(s) diverged — the shared log holds a revision of these that "
               f"differs from your file and that you have not replaced there:")
    for locator in shown:
        typer.echo(f"    {locator}")
    if len(diverged) > len(shown):
        typer.echo(f"    … and {len(diverged) - len(shown)} more")
    # First the cheap explanation, because it covers the common case and costs nothing to check: an edit
    # you have not pushed looks identical to a disagreement from here, and one `sync` tells them apart —
    # the replaced revision then classifies as your own history and these lines stop appearing.
    typer.echo("  If you have local edits to these that you haven't pushed, `yigraf sync` is the whole "
               "fix — the log simply hasn't heard your revision yet. What follows applies to whatever "
               "survives a sync.")
    if _artifacts_are_committed(repo):
        typer.echo("  Your working tree won locally (design law #6). These artifacts are committed, so "
                   "the other side is in git — reconcile them the way you would any other merge.")
    else:
        typer.echo("  Your working tree won locally (design law #6). But this repo does not commit "
                   f"{WORKSPACE_DIRNAME}/, so there is no git history holding the other revision and no "
                   "merge will ever reconcile these — each machine will go on believing its own copy. "
                   "Reconcile by hand, or start committing the workspace.")


def _responsibility_notice(repo: Path, config: dict, graph, events, local_ids: set[str]) -> str:
    """Whose turn the open conflicts are, at the moment they arrive (task #6, int:team-reconciliation).

    This is the one place the answer is *timely*. A conflict is created by the second belief landing, and
    a pull is when that lands on your machine — so telling the later writer here is telling them at the
    moment they can act, rather than whenever they next happen to run ``yigraf status``. It costs nothing
    extra: ``detect_conflicts`` runs on the graph the rebuild above just produced, and the log's order is
    already in the replica we just reconciled.

    Fail-open to silence. The sync itself has already succeeded and been reported by the time this runs;
    a surfacing that raised would turn a completed sync into a failure, which is the wrong trade for a
    notice. Nothing here is load-bearing — ``yigraf status`` still holds the same findings.
    """
    try:
        from yigraf.contradiction import detect_conflicts
        from yigraf.responsibility import assign, landings, own_actor, render_notice

        conflicts = detect_conflicts(graph, repo, config)
        if not conflicts:
            return ""
        return render_notice(assign(conflicts, landings(events), own_actor(events, local_ids)))
    except Exception:  # noqa: BLE001 - a notice must never retract a sync that already succeeded
        return ""


def _unstamped_supersedes(repo: Path) -> dict[str, tuple[Path, str]]:
    """Memories an APPLIED supersede retired that still read ``status: active`` in their own artifact.

    The forward-only half of feedback-v3 #8, which no existing store ever reaches (feedback-v4). The
    stamp is written at exactly two places — an applied ``supersede`` and the ``attest`` that applies a
    held one — so a store built before those existed keeps 87-of-89 retired beliefs reading ``active``.
    Nothing *mis-ranks*: ``superseded_in`` is recomputed from the edges on every build, so retrieval,
    ``drift.is_reverifiable``, ``gc`` and ``show`` all already treat them as retracted. The gap is
    confined to a reader of the artifact FILES — which is exactly how it bit the field: both twins read
    ``active``, so the wrong one got pinned. Pending supersedes are excluded by construction: a held
    supersede has not retired anything, and stamping it would assert the resolution it is waiting for.
    """
    out: dict[str, tuple[Path, str]] = {}
    by_id = {m.id: m for m in memory.iter_memories(repo)}
    for new_id in sorted(by_id):
        for old_id in by_id[new_id].supersedes:  # applied only — `pending_supersedes` is a separate list
            old = by_id.get(old_id)
            if old is None or (old.status == "superseded" and old.superseded_by):
                continue
            path = memory.find_memory(repo, old_id)
            if path is not None:
                out.setdefault(old_id, (path, new_id))
    return out


def _settle_renames(repo: Path, graph, apply: bool) -> list[tuple[str, str, str, str]]:
    """Write every rename the graph resolved back into the artifact that still names the old locator.

    :func:`yigraf.drift.resolve_renames` re-anchors a moved symbol or section in the **graph**, which
    design law #6 makes a derived, recomputable projection — so the rescue is re-derived from the body
    hash on every build and lasts exactly as long as that body does. Edit the body before the file is
    told and the old locator is hard drift that will never resolve, with no record anywhere of where
    the subject went. This is the verb that ends that window.

    **Only the locator moves.** ``anchor``, ``anchor_algo`` and ``stamped_at`` are carried across
    untouched: a rename is by definition a content-hash *match*, so re-hashing would compute the same
    value, and re-stamping ``stamped_at`` would date the anchor to this commit when it was taken at an
    older one — the exact wrong-*when* inference feedback-v4 #14 exists to foreclose.

    Deliberately not done inside ``build_graph``. A read command (``context``, and the PostToolUse hook
    on every single edit) would then mutate authored, committed files as a side effect of being asked a
    question — and a task's ``implements`` anchors sit inside its revision-id body
    (:func:`yigraf.filelog._plan_assertions`), so two workspaces noticing one rename at two different
    HEADs would mint two revisions of one task: precisely the phantom divergence fa74839 removed and
    ``plan:divergence-ledger`` is about. Settling is an authored act, so it takes a verb.

    Returns ``(source_id, relation, old, new)`` per settled rename, whether or not ``apply``.
    """
    settled: list[tuple[str, str, str, str]] = []
    workspace = repo / WORKSPACE_DIRNAME
    for item in compute_drift(graph):
        if item.kind != "renamed" or not item.new_locator:
            continue
        old, new = item.locator, item.new_locator
        if item.relation == "implements":
            match = _TASK_ID.match(item.task_id)
            plan_file = _find_plan_file(workspace, match.group(1).casefold()) if match else None
            if plan_file is None:
                continue  # fail-open (R5): a task whose plan we cannot place is left as it was
            if apply:
                edge = graph.get_edge_data(item.task_id, new) or {}
                artifacts.add_edge_to_plan(
                    plan_file, item.task_id, "implements", new, anchor=edge.get("anchor"),
                    anchor_algo=edge.get("anchor_algo"), stamped_at=edge.get("stamped_at"),
                    replaces=old)
        else:  # concerns | grounded_by — a memory's own frontmatter
            mem_path = memory.find_memory(repo, item.task_id)
            if mem_path is None:
                continue
            if apply:
                node = memory.read_memory(mem_path)
                node.concerns = [memory.Concern(sym=new, anchor=c.anchor, anchor_algo=c.anchor_algo)
                                 if c.sym == old else c for c in node.concerns]
                node.evidence = [memory.Evidence(ref=new, anchor=e.anchor, anchor_algo=e.anchor_algo)
                                 if e.ref == old else e for e in node.evidence]
                mem_path.write_text(memory.render_memory(node), encoding="utf-8")
        settled.append((item.task_id, item.relation, old, new))
    return sorted(settled)


def _prose_citations(repo: Path, config: dict, doomed: set[str]) -> list[tuple[str, str, bool]]:
    """Live memories whose ``why`` TEXT names a node ``gc`` is about to archive (amendment #2).

    ``refs_in=0`` is a count of *edges*, and an id named in prose is a reference the edge set cannot
    see — so is a ``--why`` that defers to "the node this supersedes", where the pointer rides an edge
    ``gc`` deliberately discounts (every collectable node is superseded by definition). Both go
    unresolvable the moment the target moves to the archive, and this is the last cheap moment to say
    so. Returns ``(source, target, target_has_an_argument)``: the second half decides which sentence
    the caller prints, because a pointer to a real argument is a repair and a pointer to an empty node
    was never anything at all.
    """
    hits: list[tuple[str, str, str]] = []
    for node in memory.iter_memories(repo):
        if node.id in doomed or not (node.why or "").strip():
            continue
        deferred = memory.deferring_why(node.why, node.supersedes,
                                        max_words=config.get("hollow_why_words", 25))
        targets = [t for t in memory.ids_named_in(node.why) if t in doomed]
        if deferred in doomed and deferred not in targets:
            targets.append(deferred)
        for target in targets:
            if target != deferred:
                hits.append((node.id, target, "cited"))
                continue
            path = memory.find_memory(repo, target)
            argued = bool(path is not None and (memory.read_memory(path).why or "").strip())
            hits.append((node.id, target, "deferred" if argued else "hollow"))
    return hits


@app.command()
def gc(
    path: Path = typer.Argument(Path("."), help="Repo root (default: current dir)."),
    apply: bool = typer.Option(False, "--apply", help="Actually archive (default: dry-run report)."),
) -> None:
    """Archive collectable memory — never delete (DESIGN R3), always reversible, dry-run by default.

    Two reasons, both moved to ``yigraf/memory/archive/`` (out of the active graph, kept for history):

    - **superseded churn** (``superseded_in>0 ∧ refs_in=0``): the deterministic archive — keyed on
      committed supersede edges, never on telemetry (mem:008), so identical on every clone.
    - **abandoned proposed** (task #7): a mined/review candidate that was never confirmed by a real
      encounter and has aged past ``proposed_ttl`` commits un-referenced. Behavioral — it reads the
      read-time maturity verdict (a confirmed candidate has graduated to ``working`` and is spared), so
      we overlay telemetry + resolve the verdict first. It expires *speculation* by silence; it NEVER
      touches a genuine ``working``/``settled`` decision (silence is not evidence there — mem:033).

    It also runs the two **backfills** — repairs of legible state rather than collections, reported
    separately and under the same dry-run/``--apply`` contract, because a store can need either while
    having nothing to archive: a supersede that never stamped its predecessor, and a rename the graph
    re-anchored but the file was never told about (:func:`_settle_renames`). Both are the same sentence
    — the graph already knows, a reader of the files cannot tell — and the rename one is the urgent
    half, because it stops being repairable the moment the renamed body is edited.

    Dry-run by default — pass ``--apply`` to move the artifacts (the source of truth).
    """
    workspace = _require_workspace(path)
    config = load_config(workspace / "config.yaml")
    graph, _ = build_graph(path, config)
    _ranked_with_telemetry(path, graph, config)  # overlay upholds + resolve the maturity verdict (proposed→working)
    actions = counters.classify_gc(graph, config)

    # Backfill first, and report it separately: it is a *repair* of legible state, not a collection, and
    # a store can need it while having nothing to archive (feedback-v4). Same dry-run/--apply contract.
    unstamped = _unstamped_supersedes(path)
    if unstamped:
        typer.echo(f"{len(unstamped)} superseded memory(ies) still read `status: active` in their own "
                   f"artifact — the graph already treats them as retracted, but a reader of the files "
                   f"cannot tell:")
        for old_id in sorted(unstamped):
            typer.echo(f"  {'✓' if apply else '·'} {old_id} → status: superseded, "
                       f"superseded_by: {unstamped[old_id][1]}")
        if apply:
            for old_id, (mem_path, new_id) in unstamped.items():
                node = memory.read_memory(mem_path)
                node.status, node.superseded_by = "superseded", new_id
                mem_path.write_text(memory.render_memory(node), encoding="utf-8")
            _rebuild(path)
            typer.echo(f"Stamped {len(unstamped)} artifact(s). Claims and bodies are untouched — this is "
                       f"metadata the successor's edge already asserted.")
        else:
            typer.echo(f"Dry run — re-run with --apply to stamp them.")
        typer.echo("")

    renames = _settle_renames(path, graph, apply)
    if renames:
        typer.echo(f"{len(renames)} anchor(s) whose subject was RENAMED: the graph re-anchored them by "
                   f"content hash, the artifact still names the locator they left. That rescue is "
                   f"re-derived from the body on every build — edit that body first and it becomes hard "
                   f"drift with no record of where the subject went:")
        for source_id, relation, old_locator, new_locator in renames:
            typer.echo(f"  {'✓' if apply else '·'} {source_id} —{relation}→ {old_locator} ⇒ {new_locator}")
        if apply:
            _rebuild(path)
            typer.echo(f"Settled {len(renames)} anchor(s). The anchor hash and the commit it was "
                       f"stamped at are unchanged — a rename is a content-hash MATCH, so only the "
                       f"locator moved; no claim, completion or history is touched.")
        else:
            typer.echo(f"Dry run — re-run with --apply to write them down.")
        typer.echo("")

    if not actions:
        if not unstamped:
            typer.echo("Nothing to collect (no superseded churn, no abandoned proposed candidates).")
        return

    reasons = {
        "superseded-churn": "superseded churn, kept as history",
        "abandoned-proposed": "abandoned proposed candidate — never confirmed by an encounter",
    }
    for mem_id in sorted(actions):
        label = graph.nodes[mem_id].get("statement") or mem_id
        why = reasons.get(actions[mem_id], actions[mem_id])
        typer.echo(f"  {'✓' if apply else '·'} {mem_id} → archive ({why}): {label}")

    # The half of that which yigraf CAN see, and therefore must (feedback-v5 amendment #2): a live
    # node's own `why` naming one of these. `refs_in=0` kept them collectable because it counts edges,
    # and prose is not an edge. Printed above the general warning because this one is actionable — it
    # names both ends and the verb that repairs it.
    citations = _prose_citations(repo=path, config=config, doomed=set(actions))
    # A plain citation is one line for ALL of them: on a real store there are a dozen or more, `show`
    # still resolves every one of them out of the archive (feedback-v5 E#1), and a dozen ⚠ nobody can
    # act on is how a surface teaches its reader to skim (design law #4). The deferrals below get a
    # line each because they are rare and each names a repair.
    cited = [(s, t) for s, t, kind in citations if kind == "cited"]
    if cited:
        typer.echo(f"  · {len(cited)} live `why` field(s) cite an id above — `refs_in` counts edges, "
                   f"and prose is not an edge. They stay readable (`yigraf show <id>` resolves an "
                   f"archived node), but `yigraf context` will no longer reach one: "
                   f"{', '.join(f'{s}→{t}' for s, t in cited[:3])}"
                   f"{f' (+{len(cited) - 3} more)' if len(cited) > 3 else ''}.")
    for source, target, kind in citations:
        if kind == "cited":
            continue
        typer.echo(f"  ⚠ {source}'s own `why` DEFERS its argument to {target}, which this run "
                   f"archives — a pointer `refs_in` cannot see, because it counts edges and this is "
                   f"prose.")
        typer.echo("      " + (
            f"Copy the argument across before the pointer stops resolving: `yigraf amend {source} "
            f"--why \"<the argument, in full>\"` — no supersedes trail, no re-stated belief."
            if kind == "deferred" else
            f"And {target} carries no `why` of its own, so that pointer was always hollow: archiving "
            f"destroys nothing, but the argument {source} claims to have is not in the store at all. "
            f"`yigraf amend {source} --why \"<the argument>\"` puts it where it is read."))

    # "Never delete, always reversible, kept for history" is true of the FILE and not of the ID, and the
    # difference is invisible until something cites one (feedback-v5 E#1). An id written down outside
    # the graph — a code comment, a design note, a PR description — stops resolving here, and nothing
    # in the graph can warn about it, because the citation does not live in the graph. So the dry run
    # says it, while the caller can still repoint the citations, which is the only moment it helps.
    typer.echo(f"  ⚠ these ids stop resolving in the active graph: `yigraf show <id>` will report them "
               f"as archived and name the successor; `yigraf context` reaches only the successor. If "
               f"prose outside the graph cites one, repoint it first — cite the "
               f"`yigraf context \"<query>\"` that finds the belief, not the id, since the query "
               f"survives a supersede and the id does not.")
    if not apply:
        typer.echo(f"Dry run — {len(actions)} node(s) would be archived. Re-run with --apply.")
        return

    archive_dir = workspace / "memory" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    before_syms = sum(1 for _, a in graph.nodes(data=True)
                      if a.get("family") == "structure" and status.is_symbol(a))
    for mem_id in sorted(actions):
        mem_path = memory.find_memory(path, mem_id)
        if mem_path is None:
            continue
        mem_path.rename(archive_dir / mem_path.name)  # out of memory/*.md → drops from the active graph
    rebuilt, _ = build_graph(path, config)
    _rebuild(path)
    typer.echo(f"Archived {len(actions)} node(s) → {archive_dir.relative_to(path)}/.")
    # A symbol count that DROPS after a garbage collection is an alarming thing to read on a graph you
    # rely on, and the cause is benign: a retired memory's anchor projects a placeholder node for a
    # locus the extractor does not index, so collecting the memory collects the placeholder with it.
    # Correct, and previously unmentioned — so the reader had to derive it (feedback-v5 E#3).
    #
    # It is an UN-INDEXED file, never a missing symbol, and the wording has to say so (feedback-v6 F#4).
    # A locus genuinely absent from source mints no node at all — `artifacts.mint_locus_node` returns
    # early when `locus_hash` is None — so "not in the current source" is precisely the case in which
    # this line stays silent. It can only ever print for a `file-anchor`: a doc, a script, a Dockerfile
    # or a `file:<path>#<section>` inside one, all still on disk. Sending the reader to look for a
    # deleted function is the diagnosis cost the line exists to prevent.
    after_syms = sum(1 for _, a in rebuilt.nodes(data=True)
                     if a.get("family") == "structure" and status.is_symbol(a))
    if after_syms < before_syms:
        typer.echo(f"Also released {before_syms - after_syms} placeholder anchor node(s) for un-indexed "
                   f"files (docs, scripts) that only a collected memory referenced — those files are "
                   f"untouched and still on disk; the `sym` count on `yigraf status` drops by that much "
                   f"and a rebuild holds at the new number.")


@app.command(name="graph-merge", hidden=True)
def graph_merge(
    base: Path = typer.Argument(..., help="Common-ancestor graph.json (git %O; ignored — graph.json is recomputable)."),
    ours: Path = typer.Argument(..., help="Our graph.json (git %A) — the merged result is written here."),
    theirs: Path = typer.Argument(..., help="Their graph.json (git %B)."),
) -> None:
    """LEGACY union-merge driver for a committed ``graph.json`` (pre-v1 workspaces only).

    v1 retired the committed ``graph.json``: the projection is now a gitignored SQLite view, never
    committed, so there is nothing to merge and ``install-hooks`` no longer registers this driver
    (mem:059). It is kept hidden and functional purely so a repo that *still* has the old
    ``merge=yigraf-graph`` driver wired in ``.git/config`` doesn't break mid-merge — it unions
    nodes+edges (the post-merge build re-projects exactly). git invokes it as ``graph-merge %O %A %B``
    and expects the result in %A with exit 0.
    """
    def _load(p: Path) -> dict:
        try:
            return json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    merged = counters.merge_node_link(_load(ours), _load(theirs))
    write_graph(from_node_link(merged), ours)


def _retire_stale_preamble(workspace: Path, indent: str = "") -> None:
    """Bring a stale committed session preamble current, and say so. Silent when there is nothing to do.

    Every ``install`` verb calls this, because every one of them is the user asking yigraf to bring its
    own generated surfaces up to date — and the preamble is one of those surfaces whenever the file
    still holds a byte-exact copy of something we shipped. It is deliberately NOT on a read path or in
    a hook: those must stay side-effect-free and fail-open, and an unrequested write into a committed
    file is the part of mem:91fe59a8463b851d's rejection that still stands (mem:a90f5a944a2b233b). The
    guard lives in `refresh_preamble`, which acts only on a preamble that is provably ours, so a team's
    own rules can never be touched here.

    Nothing is printed when the file is already current: the installers are noisy enough, and design
    law #4 applies to a human reading a transcript too.

    The second line is not decoration. ``refresh_preamble`` splices the KEY and nothing else, so a
    migrated file keeps whatever prose the writing release put above it — in a ≤1.8.x file, a paragraph
    that says the preamble is "yours to rewrite" now sitting directly above a *commented-out* block,
    and the word "uncomment" appears nowhere in it (feedback-v9 H#3). A reader who follows that prose
    literally edits the text where they find it, leaves it commented, and commits a house rule every
    session silently ignores. Widening the splice to the surrounding comment block would be a much
    larger unrequested write into a committed file, which is the thing this function is careful not to
    do — so the transition is explained here instead, at the one moment the reader is looking.
    """
    retired = refresh_preamble(workspace / "config.yaml")
    if retired:
        typer.echo(f"{indent}preamble    → retired the committed copy in {workspace.name}/config.yaml; "
                   f"this repo now tracks the preamble yigraf ships (commit the change)")
        typer.echo(f"{indent}            the text is still in the file, now commented out: uncomment "
                   f"that block to take the rules back. Any prose above it that predates 1.11.0 "
                   f"describes the old live key")
    if retired == PREAMBLE_COPY_CURRENT:
        # The ambiguous history, said out loud. Nothing is destroyed — the bytes are the ones we ship
        # and they are still in the file, commented — so a message is a COMPLETE remedy here rather
        # than a consolation, and its absence was the whole defect (feedback-v9 H#1, 1.12.1).
        typer.echo(f"{indent}⚠ preamble  that copy was byte-identical to the preamble this yigraf "
                   f"ships, which means one of two things and the file cannot say which: a repo "
                   f"`init`ed by 1.9.0-1.10.0 (the common case, and why this runs), or a preamble you "
                   f"PINNED by hand before `preamble_pinned:` existed to declare it.")
        typer.echo(f"{indent}            If it was yours, nothing is lost and nothing needs retyping: "
                   f"the same text is in the file above, commented. Uncomment it together with the "
                   f"`preamble_pinned: true` line and no release will ever touch it again.")


@app.command(name="install-hooks")
def install_hooks(
    path: Path = typer.Argument(Path("."), help="Repo root (must be a git repository)."),
) -> None:
    """Install the post-commit git hook that re-materializes the gitignored view at HEAD (fail-open)."""
    workspace = _require_workspace(path)
    _retire_stale_preamble(workspace)
    try:
        result = install_post_commit_hook(path)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)
    if not result.installed:
        typer.echo(f"A non-yigraf post-commit hook already exists at {result.path} — left untouched.")
        raise typer.Exit(code=1)
    typer.echo(f"Installed post-commit hook at {result.path}")


@app.command(name="install-claude-hooks")
def install_claude_hooks_cmd(
    path: Path = typer.Argument(Path("."), help="Repo root to wire up for Claude Code."),
) -> None:
    """Register the PostToolUse + SessionStart hooks + skill so Claude Code surfaces intent & drift."""
    workspace = _require_workspace(path)
    _retire_stale_preamble(workspace)
    result = install_claude_hooks(path)
    typer.echo(f"Wrote hooks → {result.settings_path} (per-machine, gitignored)")
    typer.echo(f"Wrote skill → {result.skill_path}")
    typer.echo(f"Updated     → {result.agents_path}")
    _STATUSLINE_NOTE = {
        "set": "Statusline → wired to `yigraf statusline` — the [Yigraf] bar + ctx gauge on every refresh.",
        "refreshed": "Statusline → re-pointed at `yigraf statusline` for this clone's interpreter.",
        "kept-foreign": "Statusline → left your existing statusLine intact (point it at `yigraf statusline` to use the bar).",
        "unchanged": "Statusline → already wired to `yigraf statusline`.",
    }
    typer.echo(_STATUSLINE_NOTE[result.statusline])
    typer.echo("Teammates: re-run this command on your clone to wire your own interpreter path.")


@app.command(name="install-codex-hooks")
def install_codex_hooks_cmd(
    path: Path = typer.Argument(Path("."), help="Repo root to wire up for Codex CLI."),
) -> None:
    """Wire yigraf's SessionStart + PostToolUse hooks into Codex (.codex/hooks.json) + AGENTS.md.

    The push-channel complement for Codex (its hooks mirror Claude Code's). SessionStart re-injection
    is reliable; PostToolUse-on-edit is best-effort — verify your Codex version's edit-tool name.
    """
    workspace = _require_workspace(path)
    _retire_stale_preamble(workspace)
    result = install_codex_hooks(path)
    typer.echo(f"Wrote hooks → {result.hooks_path} (per-machine, gitignored)")
    typer.echo(f"Updated     → {result.agents_path}")
    typer.echo("Note: Codex loads project `.codex/` hooks only for a *trusted* project; trust it once.")
    typer.echo("Teammates: re-run this command on your clone to wire your own interpreter path.")


@app.command(name="install-antigravity")
def install_antigravity_cmd(
    path: Path = typer.Argument(Path("."), help="Repo root to wire up for the Antigravity IDE."),
) -> None:
    """Wire yigraf for Antigravity (which has no hooks): an always-on .agents/rule + AGENTS.md + MCP.

    Antigravity has no lifecycle hook, so the complement is an always-on rule pointing the agent at the
    yigraf MCP tools. Add the printed MCP-server entry via Antigravity's MCP editor to finish wiring.
    """
    workspace = _require_workspace(path)
    _retire_stale_preamble(workspace)
    result = install_antigravity(path)
    typer.echo(f"Wrote rule → {result.rule_path}")
    typer.echo(f"Updated    → {result.agents_path}")
    typer.echo("\nNow add the yigraf MCP server in Antigravity (Agent panel → MCP Servers → raw config),")
    typer.echo("in ~/.gemini/antigravity/mcp_config.json (or ~/.gemini/config/mcp_config.json):")
    _print_mcp_config(path)


@app.command(name="install-kilo")
def install_kilo_cmd(
    path: Path = typer.Argument(Path("."), help="Repo root to wire up for Kilo Code."),
) -> None:
    """Wire yigraf for Kilo Code (Tier A — VS Code family, no edit hook): `.kilocode/rules/` + MCP.

    Kilo exposes rules files + MCP but no edit-lifecycle hook, so push tops out at an always-on rule
    telling the agent to pull `context`. Writes `.kilocode/rules/yigraf.md` + the AGENTS block and prints
    the MCP-server config to add via Kilo's MCP settings.
    """
    _install_ambient_rule_cmd(path, "kilo")


@app.command(name="install-cursor")
def install_cursor_cmd(
    path: Path = typer.Argument(Path("."), help="Repo root to wire up for Cursor."),
) -> None:
    """Wire yigraf for Cursor (Tier A — VS Code family, no edit hook): `.cursor/rules/*.mdc` + MCP.

    Cursor exposes `.mdc` rules + MCP but no edit-lifecycle hook, so push tops out at an always-on rule
    (frontmatter `alwaysApply: true`) telling the agent to pull `context`. Writes
    `.cursor/rules/yigraf.mdc` + the AGENTS block and prints the MCP-server config to add via Cursor.
    """
    _install_ambient_rule_cmd(path, "cursor")


@app.command(name="install-windsurf")
def install_windsurf_cmd(
    path: Path = typer.Argument(Path("."), help="Repo root to wire up for Windsurf."),
) -> None:
    """Wire yigraf for Windsurf (Tier A — VS Code family, no edit hook): `.windsurf/rules/` + MCP.

    Windsurf exposes rules + MCP but no edit-lifecycle hook, so push tops out at an always-on rule
    (frontmatter `trigger: always_on`) telling the agent to pull `context`. Writes
    `.windsurf/rules/yigraf.md` + the AGENTS block and prints the MCP-server config to add via Windsurf.
    """
    _install_ambient_rule_cmd(path, "windsurf")


@app.command(name="install-kiro")
def install_kiro_cmd(
    path: Path = typer.Argument(Path("."), help="Repo root to wire up for Kiro."),
) -> None:
    """Wire yigraf for Kiro (Tier A — no edit hook): `.kiro/steering/` + MCP.

    Kiro's steering docs are always-on context but expose no edit-lifecycle hook, so push tops out at a
    rule telling the agent to pull `context`. Writes `.kiro/steering/yigraf.md` + the AGENTS block and
    prints the MCP-server config to add via Kiro's MCP settings.
    """
    _install_ambient_rule_cmd(path, "kiro")


@app.command(name="install-gemini")
def install_gemini_cmd(
    path: Path = typer.Argument(Path("."), help="Repo root to wire up for Gemini CLI."),
) -> None:
    """Wire yigraf for Gemini CLI (Tier A — no edit hook): a fenced block in `GEMINI.md` + MCP.

    Gemini CLI's always-on context is the shared `GEMINI.md`, not a rules dir yigraf can own, so yigraf
    maintains only its `yigraf:start`/`yigraf:end` section — the user's own instructions survive a
    re-install. Prints the MCP-server config to add to `.gemini/settings.json`.
    """
    _install_ambient_rule_cmd(path, "gemini")


@app.command(name="install-copilot")
def install_copilot_cmd(
    path: Path = typer.Argument(Path("."), help="Repo root to wire up for GitHub Copilot."),
) -> None:
    """Wire yigraf for GitHub Copilot (Tier A — no edit hook): a fenced block in the instructions file.

    Copilot's repo-wide context is the shared `.github/copilot-instructions.md`, so yigraf maintains only
    its fenced section. Copilot is **explicit-only**: `.github/` exists in nearly every repo and its
    extension dir is version-globbed, so there is no marker `yigraf install` could auto-detect without
    false-positiving on almost everything — run this command (or `--host copilot`) to opt in.
    """
    _install_ambient_rule_cmd(path, "copilot")


def _print_mcp_config(repo: Path) -> None:
    """Print the ``mcpServers`` entry for ``yigraf mcp`` — the universal pull setup any MCP host accepts."""
    cfg = {"mcpServers": {"yigraf": {
        "command": sys.executable,
        "args": ["-m", "yigraf", "mcp", "--repo", str(Path(repo).resolve())]}}}
    typer.echo(json.dumps(cfg, indent=2))


#: name → its push tier from the fidelity matrix, for labeling the install output/plan by tier.
_HOST_TIER = {h.name: h.tier for h in HOST_FIDELITY}
_TIER_LABEL = {TIER_EVENT: "E · event-scoped push (edit/session hooks)",
               TIER_AMBIENT: "A · ambient-rule push (always-on rule + MCP, no edit hook)"}


def _host_tier(host: str) -> str:
    """The push tier ('E'/'A') a supported host lands in — from the single fidelity matrix."""
    return _HOST_TIER.get(host, "P")


def _install_ambient_rule_cmd(path: Path, host: str) -> None:
    """Shared body of the standalone Tier-A installers (install-kilo/-cursor/-windsurf/-antigravity).

    One shape: write the always-on rule + AGENTS block, then print the MCP-server config for the user to
    add via the host's own MCP editor. Ambient rule = Tier A (mem:045): the agent must *pull* context, so
    there is no edit-lifecycle push — that is the honest ceiling of a host with rules + MCP but no hook.
    """
    workspace = _require_workspace(path)
    _retire_stale_preamble(workspace)
    r = install_ambient_rule(path, host)
    typer.echo(f"Wrote rule → {r.rule_path}")
    typer.echo(f"Updated    → {r.agents_path}")
    typer.echo(f"\nTier A (ambient-rule) — {host} has no edit-lifecycle hook, so the rule tells the agent")
    typer.echo(f"to pull `context` before editing. Now add the yigraf MCP server via {host}'s MCP editor:")
    _print_mcp_config(path)


def _preamble_plan_note(config_path: Path) -> str | None:
    """What ``install`` would do to the committed ``config.yaml``, in one line — ``None`` if nothing.

    Reads the same predicate the installer acts on, so the preview cannot promise a write the verb
    would decline or stay quiet about one it would make.
    """
    retiring = preamble_copy_class(config_path)
    if retiring is None:
        return None
    if retiring == PREAMBLE_COPY_CURRENT:
        return ("yigraf/config.yaml — would retire the live `preamble:` key (its text is byte-identical "
                "to the one this yigraf ships) and leave that text in the file, commented. If you "
                "PINNED it by hand rather than inheriting it from a 1.9.0-1.10.0 `init`, add "
                "`preamble_pinned: true` beside the key FIRST and install will leave it alone.")
    return ("yigraf/config.yaml — would retire the live `preamble:` key (an older default yigraf "
            "shipped) and leave the current text in the file, commented.")


def _build_install_plan(path: Path, config: dict, host: str) -> dict:
    """Inspect the host + repo and return the menu of what *would* be wired — the data an agent shows
    the human before touching anything.

    Pure inspection: reads the environment (Python, git, detected hosts, whether the embeddings backend
    is importable) and never mutates. ``install --plan`` renders this; ``install`` applies it. Keeping
    the two on one source of truth means the menu can't drift from what the installer actually does.
    """
    choice = host.lower()
    detected = detect_hosts(path)
    if choice == "auto":
        push_targets = detected
    elif choice in SUPPORTED_HOSTS:
        push_targets = [choice]
    else:  # "mcp" / unknown → generic MCP channel only
        push_targets = []

    emb = embeddings.status(config)
    py = sys.version_info
    return {
        "yigraf_version": __version__,
        "environment": {
            "python": f"{py.major}.{py.minor}.{py.micro}",
            "python_ok": (py.major, py.minor) >= (3, 11),
            "git_repo": (Path(path) / ".git").is_dir(),
        },
        "hosts": {"detected": detected, "target": choice, "push_targets": push_targets},
        # The ONE thing `install` writes that git tracks, so it is the one thing a dry-run most owes
        # the reader. `--plan` returns before `_retire_stale_preamble` by construction (inspect-only
        # must write nothing), which had the side effect of making the preview silent about it —
        # so the preview names it here instead, in the same words (feedback-v9 H#1, 1.12.1).
        "committed_write": _preamble_plan_note(Path(path) / "yigraf" / "config.yaml"),
        # The generic channel is host-independent and always wired — it works with any agent.
        "generic_channel": [
            "post-commit hook — re-materializes the gitignored view (.local/graph.db) on every commit",
            "AGENTS.md instruction block — any agent reads it",
            "MCP pull server (`yigraf mcp`) — the universal channel every MCP host speaks",
        ],
        # Capabilities the human chooses from. Core is always on; plugins carry their real cost so the
        # decision is deliberate, not a surprise mid-install.
        "capabilities": {
            "core": [
                "structure index — tree-sitter parsing, 16 languages (bundled, no setup)",
                "intent & plan authoring + intent↔code drift detection",
                "memory (decisions + the why) with lexical recall",
                "token-cheap `yigraf context` retrieval",
                f"semantic recall — {'ON' if emb['active'] else 'OFF'} "
                f"(backend: {emb['backend']}; fastembed/ONNX, no torch) — downloads a small "
                f"bge-small model from HuggingFace on first use",
            ],
            "plugins": [
                {
                    "name": "embeddings-torch",
                    "enabled": emb["backend"] in ("sentence-transformers", "sentence_transformers")
                               and emb["torch_available"],
                    "enables": "swap semantic recall onto the torch/sentence-transformers backend "
                               "(Apple-Silicon MPS throughput or the exact fp32 model)",
                    "cost": "pulls torch (~1GB+); semantic recall already works without it",
                    "fallback": "the default fastembed backend (semantic recall is on regardless)",
                    "enable_cmd": "pip install 'yigraf[embeddings-torch]'  "
                                  "# then set embeddings.backend: sentence-transformers",
                },
            ],
        },
    }


def _render_plan(plan: dict) -> None:
    """Human/agent-readable rendering of the install plan (the menu to present before applying)."""
    env = plan["environment"]
    typer.echo(f"yigraf {plan['yigraf_version']} — install plan (nothing applied yet)\n")
    typer.echo("Environment:")
    typer.echo(f"  Python {env['python']} " + ("✓" if env["python_ok"] else "✗ (needs ≥ 3.11)"))
    typer.echo("  git repo " + ("✓ (drift anchoring enabled)" if env["git_repo"]
               else "— none (drift/maturity degrade gracefully)"))
    hosts = plan["hosts"]
    typer.echo("  detected host(s): " + (", ".join(hosts["detected"]) or "none"))

    if plan.get("committed_write"):
        # First, and marked: everything else in this menu is per-machine or gitignored. This is the
        # only line that describes a change to a file the team shares.
        typer.echo("\n⚠ Will change a COMMITTED file:")
        typer.echo(f"  • {plan['committed_write']}")

    typer.echo("\nWill wire (generic — every host, always on):")
    for item in plan["generic_channel"]:
        typer.echo(f"  • {item}")
    if hosts["push_targets"]:
        typer.echo("\nWill wire (native push, by fidelity tier):")
        for h in hosts["push_targets"]:
            typer.echo(f"  • {h} — Tier {_TIER_LABEL.get(_host_tier(h), _host_tier(h))}")

    typer.echo("\nCore capabilities (included):")
    for item in plan["capabilities"]["core"]:
        typer.echo(f"  ✓ {item}")

    typer.echo("\nOptional plugins (your call):")
    for p in plan["capabilities"]["plugins"]:
        state = "ON" if p["enabled"] else "OFF"
        typer.echo(f"  [{state}] {p['name']} — {p['enables']}")
        typer.echo(f"        cost: {p['cost']}")
        typer.echo(f"        without it: {p['fallback']}")
        if not p["enabled"]:
            typer.echo(f"        turn on: {p['enable_cmd']}")

    typer.echo("\nTo apply the above: `yigraf install`  (add plugins first if you want them).")


@app.command(name="install")
def install_cmd(
    path: Path = typer.Argument(Path("."), help="Repo root to wire up."),
    host: str = typer.Option("auto", "--host",
                             help="auto | claude | codex | antigravity | kilo | cursor | windsurf | "
                                  "kiro | gemini | copilot | mcp "
                                  "(default: auto-detect)."),
    plan: bool = typer.Option(False, "--plan",
                              help="Inspect only: print the menu of what would be wired, apply nothing."),
    as_json: bool = typer.Option(False, "--json",
                                 help="With --plan, emit the plan as JSON (for an agent to parse)."),
) -> None:
    """Wire yigraf's full power by default — the host-agnostic channel every repo gets — plus any
    detected host's native push hooks layered on top.

    The **generic** channel installs unconditionally, because it works regardless of agent host: the
    post-commit hook (re-materializes the gitignored view at each commit),
    the AGENTS.md instruction block (any agent reads it), and the MCP pull server (the universal
    channel every MCP host speaks). Then ``auto`` detects each supported host and layers its native
    push at the highest tier its seams allow — Tier E (edit/session hooks: Claude Code, Codex) or Tier A
    (always-on rule + MCP: Antigravity, Kilo, Cursor, Windsurf); ``--host`` forces one. Semantic recall
    is on by default (the fastembed backend is bundled in core); the heavier torch backend stays opt-in.
    """
    workspace = _require_workspace(path)
    config = load_config(workspace / "config.yaml")

    # --- Plan mode: inspect the host, print the menu, apply nothing (the agent shows this first) ---
    if plan:
        built = _build_install_plan(path, config, host)
        if as_json:
            typer.echo(json.dumps(built, indent=2))
        else:
            _render_plan(built)
        return

    # --- Generic channel (host-independent) — always on -------------------------------------------
    # Below the `--plan` return by construction: inspect-only must write nothing, and this is the one
    # thing `install` touches that git tracks.
    typer.echo("== generic (every host) ==")
    _retire_stale_preamble(workspace, indent="  ")
    try:
        r = install_post_commit_hook(path)
        if r.installed:
            typer.echo(f"  post-commit → {r.path} (re-materializes the gitignored view on commit)")
        else:
            typer.echo(f"  post-commit → left your existing non-yigraf hook at {r.path} untouched")
    except FileNotFoundError:
        typer.echo("  post-commit → skipped (not a git repository)")
    typer.echo(f"  AGENTS.md   → {_write_agents_block(path / 'AGENTS.md')} (host-agnostic instructions)")
    typer.echo("  MCP pull server — the universal *fallback* channel, printed (not written) for any MCP")
    typer.echo("  host. If a push-hook host (Claude Code / Codex) is detected below, its hooks ARE your")
    typer.echo("  channel and you do NOT need to wire this — leave it unless you want redundant pull too:")
    _print_mcp_config(path)

    # --- Capability check: semantic recall (fastembed core → on by default; warn only if degraded) -
    emb = embeddings.status(config)
    if emb["active"]:
        # The model is fetched HERE, not on first build: every other path loads it local-only so a
        # missing model degrades to lexical instead of blocking the agent on a download (design law
        # #5). This is the one place a wait is expected, and the one place it is reported.
        if embeddings.model_cached(config):
            typer.echo(f"\n✓ semantic recall is ON (backend: {emb['backend']}, model cached in "
                       f"{emb['cache_dir']}).")
        else:
            typer.echo(f"\n… fetching the {embeddings.model_name(config)} model into "
                       f"{emb['cache_dir']} (~70MB, once) — nothing else ever downloads it.")
            if embeddings.fetch_model(config):
                typer.echo(f"✓ semantic recall is ON (backend: {emb['backend']}).")
            else:
                typer.echo("⚠ semantic recall is OFF — the model couldn't be fetched, so retrieval is "
                           "lexical-only (correct, just less recall). Nothing is broken and nothing "
                           "will retry in the background; re-run `yigraf install` when you're online.")
    else:
        typer.echo("\n⚠ semantic recall is OFF — retrieval is lexical-only.")
        if emb["backend"] in ("none", None):
            typer.echo("  (embeddings.backend is 'none' in yigraf/config.yaml — set it to 'fastembed' "
                       "to turn it on.)")
        else:
            typer.echo("    pip install fastembed   # the default backend is bundled in core; "
                       "reinstall yigraf if it's missing")

    # --- Host-specific push channels (layered on top of the generic channel above) ----------------
    choice = host.lower()
    if choice == "auto":
        targets = detect_hosts(path)
        typer.echo("\nDetected host(s): " + (", ".join(targets) if targets
                   else f"none ({', '.join(SUPPORTED_HOSTS)}) — the generic MCP channel covers you"))
        # Say what is about to appear in the tree, and how to narrow it. Auto-detect is documented, and
        # wiring two hosts is right for someone who drives this repo from two — but a host detected only
        # by a HOME marker is "installed on this machine", not "used here", and those directories arrive
        # untracked in a tree where every yigraf artifact is deliberately git-excluded, so they have to
        # be excluded by hand before a commit can pick them up (feedback-v4). One line, before the fact.
        from_home = [h for h in targets if h not in detect_hosts(path, home=path / "__no_home__")]
        if from_home:
            dirs = ", ".join(sorted({m for h in from_home for m in _HOST_MARKERS[h] if m}))
            typer.echo(f"  {', '.join(from_home)} matched a marker in your HOME dir, not this repo — "
                       f"wiring {'them' if len(from_home) > 1 else 'it'} creates {dirs} here. For one "
                       f"host only, re-run with `--host <name>`; `yigraf install --plan` shows the "
                       f"whole menu without applying any of it.")
    elif choice in SUPPORTED_HOSTS:
        targets = [choice]
    else:  # "mcp" or any unrecognized host name → generic MCP channel above is all that's needed
        targets = []

    for h in targets:
        typer.echo(f"\n== {h} (Tier {_host_tier(h)}) ==")
        if h == "claude":
            r = install_claude_hooks(path)
            typer.echo(f"  hooks → {r.settings_path}  ·  skill → {r.skill_path}  ·  AGENTS → {r.agents_path}")
            typer.echo(f"  statusline → {r.statusline} ([Yigraf] bar + ctx gauge; no deps)")
        elif h == "codex":
            r = install_codex_hooks(path)
            typer.echo(f"  hooks → {r.hooks_path}  ·  AGENTS → {r.agents_path}")
            typer.echo("  (Codex loads project `.codex/` hooks only for a *trusted* project.)")
        elif h in AMBIENT_HOSTS:  # antigravity, kilo, cursor, windsurf, kiro, gemini, copilot
            r = install_ambient_rule(path, h)
            typer.echo(f"  rule → {r.rule_path}  ·  AGENTS → {r.agents_path}")
            typer.echo(f"  ambient rule only (no edit-lifecycle hook); add the yigraf MCP server "
                       f"(config above) via {h}'s MCP editor.")


# --- Claude Code hook entry points (invoked by the hooks above; read event JSON on stdin) ----------

hook_app = typer.Typer(help="Claude Code hook entry points (read the hook event JSON on stdin).",
                       no_args_is_help=True, add_completion=False)
app.add_typer(hook_app, name="hook")


def _run_hook(handler) -> None:
    """Run a hook handler fail-open: parse stdin JSON, print the payload if any, always exit 0."""
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        payload = handler(data)
        if payload is not None:
            typer.echo(json.dumps(payload))
    except Exception:
        pass  # never block or fail the tool/session (R8 fail-open)
    raise typer.Exit(code=0)


def _hook_graph(root: Path):
    """Build the graph for a hook, or None if there's no workspace (→ stay silent)."""
    if not (root / WORKSPACE_DIRNAME).is_dir():
        return None
    config = load_config(root / WORKSPACE_DIRNAME / "config.yaml")
    graph, _ = graphdb.load_or_build(root, config)  # materialized view keeps the hot edit path cheap
    return graph, config


#: Edit-tool names across hosts. Claude Code: Edit/Write/MultiEdit (clean ``file_path``). Codex: the
#: ``apply_patch`` family (path lives *inside* the patch text). Gating on the tool name keeps the hook
#: off frequent non-edit tools (Read) so it doesn't rebuild the graph on every call.
_EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "apply_patch", "ApplyPatch",
                         "str_replace_editor", "create_file", "write_file"})
_PATCH_FILE = re.compile(r"^\*\*\*\s+(?:Add|Update|Delete) File:\s*(.+?)\s*$", re.MULTILINE)


def _edited_file(data: dict) -> str | None:
    """The file an edit tool touched, across hosts — or ``None`` (⇒ the hook stays silent, fail-open).

    A direct ``file_path``/``path`` covers Claude Code (Edit/Write/MultiEdit) and any host that hands a
    clean field. Codex's ``apply_patch`` carries the path inside the patch body, so fall back to the
    first ``*** Add|Update|Delete File: <path>`` line. An unknown shape returns ``None``.
    """
    if data.get("tool_name") not in _EDIT_TOOLS:
        return None
    tool_input = data.get("tool_input") or {}
    direct = tool_input.get("file_path") or tool_input.get("path")
    if direct:
        return direct
    for value in (tool_input.get("patch"), tool_input.get("input"), tool_input.get("changes")):
        if isinstance(value, str):
            m = _PATCH_FILE.search(value)
            if m:
                return m.group(1)
    return None


#: How many sessions of emission history the PostToolUse latch retains (mirrors obligations._MAX_SESSIONS).
_MAX_EMIT_SESSIONS = 20


def _already_emitted(root: Path, session: str, locus: str, digest: str) -> bool:
    """Has ``session`` already received EXACTLY this packet for ``locus``? Record it if not (Ask A).

    Editing the same file N times re-emitted the same ``Context for`` packet N times, and every copy
    then rides in the prompt for the rest of the session — measured on one field session, 15 of 23
    PostToolUse packets were byte-identical repeats costing 3.47M tokens for text the model could
    already read (feedback-v3, the highest-value item by tokens). Keyed by the DIGEST of the rendered
    text, not by the path: any change in what yigraf would say (new drift, a new decision, ranking
    movement) changes the digest and re-injects. Volatile, machine-local, session-keyed derived state
    in ``.local/`` (never the graph — design law #6), exactly like the obligations announce latch.
    Fail-open in the safe direction: an unreadable latch costs one duplicate packet, never a lost one.
    """
    path = Path(root) / WORKSPACE_DIRNAME / ".local" / "emitted.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    sessions = {k: v for k, v in data.items() if isinstance(v, dict)}
    if sessions.get(session, {}).get(locus) == digest:
        return True
    sessions.setdefault(session, {})[locus] = digest
    if len(sessions) > _MAX_EMIT_SESSIONS:
        keep = [session] + [k for k in reversed(list(sessions)) if k != session]
        sessions = {k: sessions[k] for k in keep[:_MAX_EMIT_SESSIONS] if k in sessions}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sessions, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass  # best-effort: a failed write means one duplicate later, never a crash in a hook (D#5)
    return False


def _post_tool_use(data: dict) -> dict | None:
    file_path = _edited_file(data)
    if not file_path:
        return None
    root = Path(data.get("cwd") or os.getcwd())
    built = _hook_graph(root)
    if built is None:
        return None
    # Claude Code hands an absolute path; Codex's apply_patch path is repo-relative — anchor it to root.
    edited = Path(file_path)
    if not edited.is_absolute():
        edited = root / edited
    try:
        rel = edited.resolve().relative_to(root.resolve())
    except ValueError:
        return None  # edited file is outside the repo
    graph, config = built
    # Indexed language OR a file something is explicitly anchored to. The suffix gate alone made a
    # `file:` anchor write-only at the moment of action: `remember --concerns file:docs/guide.md` is
    # accepted, stored, and answered by `yigraf context` — and `context_for_locus` returns that decision
    # for the doc — but the hook discarded it unasked, because .md is not an extracted language. An
    # anchor the principal placed by hand is the strongest possible signal that this locus is governed;
    # dropping it is design law #4 inverted (silence where there IS something worth saying).
    #
    # `retrieval.locus_nodes` answers it, rather than the `f"file:{casefolded}" in graph` this line used
    # to open-code: that form only ever matched a WHOLE-file anchor on an all-lowercase path, so a doc
    # governed by a `#<section>` or a `:L<a>-L<b>`, or a `file:Dockerfile` (the example
    # int:file-anchoring itself names), failed the gate and the hook stayed silent. An un-anchored .md
    # still has no nodes and still returns None — the hook says nothing on ordinary prose edits.
    if (rel.suffix not in extension_map(available_extractors(config))
            and not retrieval.locus_nodes(graph, rel.as_posix())):
        return None  # neither indexed nor anchored → nothing this hook could say
    _ranked_with_telemetry(root, graph, config)  # recency/popularity + maturity verdict (R1)
    result = retrieval.context_for_locus(graph, rel.as_posix(), config, root=root)
    if result is None:
        return None  # silent: nothing governs this locus and no drift
    _record_edit_upholds(root, graph, config, rel.as_posix())  # silent survival = a weak maturity uphold
    # A packet byte-identical to one this session already received is pure re-read cost (Ask A) —
    # inject nothing. The uphold above still books (the edit happened); the injection signal does not
    # (no injection happened). Anything yigraf would say differently re-injects by digest change.
    import hashlib
    session = str(data.get("session_id") or "default")
    if _already_emitted(root, session, rel.as_posix(),
                        hashlib.sha256(result.text.encode("utf-8")).hexdigest()):
        return None
    _record_injection(root, graph, result)  # a surfaced decision/intent is a soft usage signal (sidecar)
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": result.text}}


def _session_status_line(root: Path, graph, config: dict) -> str | None:
    """The one-line ``yigraf status`` summary for the SessionStart head, or ``None`` (fail-open).

    Called BEFORE :func:`_ranked_with_telemetry`, and that ordering is load-bearing: the freshness
    check compares the rebuilt graph byte-for-byte against the persisted view, and the maturity verdict
    the overlay applies rewrites ``maturity`` — a non-volatile attr — so computing this afterwards
    would report a spuriously ``stale`` view. Plain text, never ANSI: this goes into the *agent's*
    context, where escape codes are wasted tokens (design law #2).
    """
    try:
        summary = status.compute_status(graph, root, config)
        return summary.render_line(color=False)
    except Exception:
        return None  # a status failure must not cost the agent its rules and its plan (design law #5)


def _session_start(data: dict) -> dict | None:
    root = Path(data.get("cwd") or os.getcwd())
    built = _hook_graph(root)
    if built is None:
        return None
    graph, config = built
    scfg = config.get("session_start", {}) or {}
    status_line = (_session_status_line(root, graph, config)
                   if scfg.get("append_status", True) else None)
    _ranked_with_telemetry(root, graph, config)  # recency/popularity + maturity verdict (R1)
    result = retrieval.session_context(graph, config, root=root, status_line=status_line)
    if result is None:
        return None
    _record_injection(root, graph, result)  # the re-injection is a soft usage signal (sidecar)
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": result.text}}


def _stop(data: dict) -> dict | None:
    """Stop: notify the **principal** of obligations that appeared this turn (int:obligation-notice).

    Returns ONLY the universal ``systemMessage`` field — documented as "warning message shown to the
    user", never added to the agent's context. Two fields are deliberately never set (mem:bf00a1f5):

    - ``decision: "block"`` — design law #5 is unconditional; this channel informs, it never gates.
      It is also the honest shape: the sharpest obligation here (a *pending* supersede of a
      human-attested node, mem:048) is one the agent structurally **cannot** clear, so blocking on it
      would deadlock against a decision only the principal can make.
    - ``hookSpecificOutput.additionalContext`` — that is the agent's channel, and human-facing graph
      health does not spend the agent's budget (mem:012). Told "go fix that", the agent recovers the
      locators through ``yigraf context`` on the existing path.

    Silent unless something is *newly* unresolved (design law #4), and fail-open throughout: no
    workspace, no obligations, or an unchanged fingerprint all return ``None``.
    """
    root = Path(data.get("cwd") or os.getcwd())
    if not (root / WORKSPACE_DIRNAME).is_dir():
        return None
    config = load_config(root / WORKSPACE_DIRNAME / "config.yaml")
    if not config.get("status", {}).get("obligation_notice", True):
        return None

    # Fast path first: this runs on every turn, so an unchanged input fingerprint must cost a stat walk
    # plus one small indexed read — the view's `governed_files`, which names the inputs no source walk
    # can find — and nothing more: no graph load, no embedding index read. (Measured on this repo,
    # ~18ms either way.) Once, after the governed set changes, the latch misses its fast path and takes
    # the full path below; that is the rebuild it should be taking.
    session = str(data.get("session_id") or "default")
    fingerprint = graphdb.current_fingerprint(root, config)
    if obligations.is_unchanged(root, session, fingerprint):
        return None

    graph, _ = graphdb.load_or_build(root, config)
    current = obligations.obligations(graph, root, config)
    fresh = obligations.new_obligations(root, current, session, fingerprint=fingerprint)
    if not fresh:
        return None
    max_lines = int(config.get("status", {}).get("obligation_notice_max", obligations.DEFAULT_MAX))
    return {"systemMessage": obligations.render_notice(fresh, len(current), max_lines)}


@hook_app.command("post-tool-use")
def hook_post_tool_use() -> None:
    """PostToolUse(Edit|Write): inject governing intent + drift for the touched file (silent-unless)."""
    _run_hook(_post_tool_use)


@hook_app.command("session-start")
def hook_session_start() -> None:
    """SessionStart(clear|compact|…): re-inject the active plan + governing intents."""
    _run_hook(_session_start)


@hook_app.command("stop")
def hook_stop() -> None:
    """Stop: notify the *principal* of newly-unresolved obligations (never blocks, never the agent)."""
    _run_hook(_stop)


def main() -> None:
    """Console-script entry point (see ``[project.scripts]`` in pyproject.toml)."""
    app()
