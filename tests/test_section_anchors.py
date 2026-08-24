"""``file:<path>#<section>`` — a heading is a stable address for prose; a line range is not.

The feature exists because of one reproduction, pinned below as
``test_the_line_range_it_replaces_migrates_then_goes_quiet``: insert a paragraph *above* a governed
section and the line-range anchor false-drifts though its text never changed, ``reaffirm`` — the exit
the drift line names — reports success while re-stamping the hash of the WRONG region, and a later
rewrite of the actual governed claim then drifts nothing at all. A positional address silently
relocates the belief off its subject and goes quiet: a false negative in the moat, not a nag
(mem:a65f1ccad03b765e supersedes the 2026-08-12 call that kept doc support at file granularity).

So the contract has two halves and both are tested here. **Stability**: a heading rename, a rewrap, a
re-level, an edit in a subsection, and any edit outside the section must not drift it. **Sensitivity**:
rewriting the governed prose, changing a code sample, or adding/renaming/removing a subsection must.
Every normalization rule is one ``astnorm-v1`` already applies to code, so each test names the code
rule it mirrors.
"""
import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from yigraf import astnorm, graphdb
from yigraf.cli import app
from yigraf.config import default_config
from yigraf.drift import compute_drift
from yigraf.extract import build_graph

runner = CliRunner()

DOC = """# Guide

Intro text.

## Drift

Drift is the moat of this tool.

```python
def f():
    return 1
```

### Soft drift

Body edits trip it.

## Other

Unrelated.
"""

SECTION = "file:guide.md#drift"


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    (tmp_path / "code.py").write_text("def f():\n    return 1\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    (tmp_path / "guide.md").write_text(DOC)
    return tmp_path


def _run(root: Path, *args: str):
    result = runner.invoke(app, [*args, "--repo", str(root)])
    assert result.exit_code == 0, result.output
    return result


def _remember(root: Path, statement: str, *extra: str) -> str:
    out = _run(root, "remember", statement, "--why", "governs the prose", *extra).output
    return re.search(r"mem:[0-9a-f]+", out).group(0)


def _drift(root: Path) -> list[tuple[str, str, str | None]]:
    graph, _ = build_graph(root, default_config())
    return [(d.kind, d.locator, d.new_locator) for d in compute_drift(graph)]


# ── mdsec-v1: what the hash ignores, and what it must not ─────────────────────────────────────────


def _hash(tmp_path: Path, text: str, slug: str = "drift") -> str | None:
    (tmp_path / "g.md").write_text(text)
    return astnorm.section_content_hash(tmp_path, f"file:g.md#{slug}")


@pytest.mark.parametrize("label,edit,slug", [
    # Mirrors astnorm's ``exclude`` for a symbol's own declared name: the heading text is outside the
    # hash, which is the whole reason a rename can be re-anchored rather than reported as hard drift.
    ("the heading is renamed", lambda t: t.replace("## Drift\n", "## Drift detection\n"), "drift-detection"),
    # The prose analogue of quote canonicalization: a rewrap is to text what a ``black`` reflow is to
    # code. Per-LINE tokens looked equivalent and were not — this case is why the hash is per *block*.
    ("a paragraph is rewrapped", lambda t: t.replace("Drift is the moat of this tool.",
                                                     "Drift is the moat\nof this tool."), "drift"),
    ("a paragraph is re-indented", lambda t: t.replace("Drift is the moat of this tool.",
                                                       "   Drift  is   the moat of this tool. "), "drift"),
    ("blank lines are added", lambda t: t.replace("Drift is the moat of this tool.",
                                                  "Drift is the moat of this tool.\n\n"), "drift"),
    # The case the feature exists for: the section's own text is untouched, so nothing drifted.
    ("a paragraph is inserted ABOVE", lambda t: t.replace("Intro text.", "Intro text.\n\nAdded later."),
     "drift"),
    # Depth is deliberately unhashed: promoting a whole doc one level is a reflow-class edit.
    ("the whole doc is promoted one level", lambda t: t.replace("## ", "# ").replace("### ", "## "),
     "drift"),
    # Mirrors ``<def:NAME>``: a nested subsection's body is its own concern, not the parent's.
    ("a subsection's prose is edited", lambda t: t.replace("Body edits trip it.", "Body edits trip it now."),
     "drift"),
])
def test_a_cosmetic_or_neighbouring_edit_does_not_change_a_section_hash(tmp_path, label, edit, slug):
    assert _hash(tmp_path, DOC) == _hash(tmp_path, edit(DOC), slug), label


@pytest.mark.parametrize("label,edit", [
    ("the governed claim is rewritten", lambda t: t.replace("Drift is the moat of this tool.",
                                                            "Drift is NOT the moat.")),
    # Inside a fence every byte is kept: indentation is semantic in a sample, and equating two
    # different samples would be a false negative in the one part of a doc that is precise.
    ("a code sample is re-indented", lambda t: t.replace("    return 1", "        return 1")),
    ("a code sample's value changes", lambda t: t.replace("return 1", "return 2")),
    # Mirrors "a class hash captures its member names": the marker changes, so the parent drifts.
    ("a subsection is renamed", lambda t: t.replace("### Soft drift", "### Soft-drift rules")),
    ("a subsection is removed", lambda t: t.replace("### Soft drift\n\nBody edits trip it.\n\n", "")),
    ("a fenced block is added", lambda t: t.replace("Drift is the moat of this tool.",
                                                    "Drift is the moat of this tool.\n\n```\nx\n```")),
])
def test_a_substantive_edit_changes_the_section_hash(tmp_path, label, edit):
    assert _hash(tmp_path, DOC) != _hash(tmp_path, edit(DOC)), label


BLOCKS = """## S

- a long first item that wraps
- second item

| a | b |
|---|---|
| 1 | 2 |

> a quoted callout
> continued

    indented code sample
"""


@pytest.mark.parametrize("label,edit,same", [
    ("a list item is rewrapped", lambda t: t.replace("- a long first item that wraps",
                                                     "- a long first item\n  that wraps"), True),
    ("table pipes are realigned", lambda t: t.replace("| a | b |", "|  a  |  b  |"), True),
    ("a callout is rewrapped onto one line", lambda t: t.replace("> a quoted callout\n> continued",
                                                                 "> a quoted callout continued"), True),
    # A block *starter* never joins the block above it, so splitting one item into two is a change.
    ("one list item becomes two", lambda t: t.replace("- a long first item that wraps",
                                                      "- a long first item\n- that wraps"), False),
    ("a table row is added", lambda t: t.replace("| 1 | 2 |", "| 1 | 2 |\n| 3 | 4 |"), False),
    ("the quote marker is dropped", lambda t: t.replace("> a quoted callout", "a quoted callout"), False),
    ("a quote is nested deeper", lambda t: t.replace("> continued", ">> continued"), False),
    ("indented code is re-indented", lambda t: t.replace("    indented code sample",
                                                         "        indented code sample"), False),
])
def test_block_structure_decides_what_a_rewrap_may_hide(tmp_path, label, edit, same):
    base = _hash(tmp_path, BLOCKS, "s")
    assert (_hash(tmp_path, edit(BLOCKS), "s") == base) is same, label


def test_a_hash_inside_a_fence_is_code_not_a_heading(tmp_path: Path):
    """Fence state is tracked over the whole file — otherwise a shell comment in an example would be
    read as a heading and would cut the enclosing section short there."""
    (tmp_path / "g.md").write_text(
        "# Guide\n\n## Drift\n\n```sh\n# not a heading\necho hi\n```\n\nmore prose.\n\n## Other\n")
    assert astnorm.section_slugs(tmp_path, "g.md") == ["guide", "drift", "other"]


def test_an_ambiguous_slug_resolves_to_no_hash(tmp_path: Path):
    """Two headings with one slug make that slug unaddressable, so it gets no anchor at all rather
    than one silently pinned to whichever came first."""
    assert _hash(tmp_path, "# A\n\n## Dup\n\nx\n\n## Dup\n\ny\n", "dup") is None


# ── The drift round trip, and the failure it replaces ─────────────────────────────────────────────


def test_the_line_range_it_replaces_migrates_then_goes_quiet(tmp_path: Path):
    """The reproduction that earned the feature — pinned so the *reason* cannot be lost.

    A line range is positional, so inserting a paragraph above a governed section false-drifts it,
    ``reaffirm`` re-stamps the hash of a DIFFERENT region while reporting success, and rewriting the
    real governed claim then drifts nothing. This test asserts the broken behaviour on purpose: it is
    the control for ``test_a_paragraph_inserted_above_leaves_a_section_anchor_alone``, and if line
    ranges ever become relocatable it should fail and be rewritten, not deleted.
    """
    root = _repo(tmp_path)
    doc = root / "guide.md"
    mem = _remember(root, "the Drift section is the moat claim", "--concerns", "file:guide.md:L5-L7")

    doc.write_text(DOC.replace("Intro text.", "Intro text.\n\nAdded later."))
    assert [(k, loc) for k, loc, _ in _drift(root)] == [("soft", "file:guide.md:L5-L7")], "false drift"

    _run(root, "reaffirm", mem)  # the exit the soft-drift line names
    assert _drift(root) == [], "reported success — on a region it never governed"

    doc.write_text(doc.read_text().replace("Drift is the moat of this tool.", "Drift is NOT the moat."))
    assert _drift(root) == [], "and now the governed claim can be reversed in silence"


def test_a_paragraph_inserted_above_leaves_a_section_anchor_alone(tmp_path: Path):
    """The same edit as the control above, against a section anchor: no drift, and still sensitive."""
    root = _repo(tmp_path)
    doc = root / "guide.md"
    _remember(root, "the Drift section is the moat claim", "--concerns", SECTION)

    doc.write_text(DOC.replace("Intro text.", "Intro text.\n\nAdded later."))
    assert _drift(root) == []

    doc.write_text(doc.read_text().replace("Drift is the moat of this tool.", "Drift is NOT the moat."))
    assert [(k, loc) for k, loc, _ in _drift(root)] == [("soft", SECTION)]


def test_editing_the_governed_section_drifts_and_reaffirm_clears_it(tmp_path: Path):
    root = _repo(tmp_path)
    mem = _remember(root, "the Drift section is the moat claim", "--concerns", SECTION)

    (root / "guide.md").write_text(DOC.replace("Drift is the moat of this tool.", "Drift is central."))
    assert [(k, loc) for k, loc, _ in _drift(root)] == [("soft", SECTION)]

    _run(root, "reaffirm", mem)
    assert _drift(root) == []


def test_a_renamed_heading_re_anchors_instead_of_drifting(tmp_path: Path):
    """int:drift-detection SHALL NOT flag a pure rename — and a heading rename is one.

    Docs are deliberately not indexed, so nothing mints a node under the heading's new name;
    ``artifacts.mint_locus_node`` resolves the move from the stored anchor instead, and
    ``drift.resolve_renames`` then re-anchors the edge exactly as it does for a renamed symbol.
    """
    root = _repo(tmp_path)
    _remember(root, "the Drift section is the moat claim", "--concerns", SECTION)

    (root / "guide.md").write_text(DOC.replace("## Drift\n", "## Drift detection\n"))
    assert _drift(root) == [("renamed", SECTION, "file:guide.md#drift-detection")]


def test_a_deleted_section_is_hard_drift(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "the Drift section is the moat claim", "--concerns", SECTION)

    (root / "guide.md").write_text("# Guide\n\nIntro text.\n\n## Other\n\nUnrelated.\n")
    assert [(k, loc) for k, loc, _ in _drift(root)] == [("hard", SECTION)]


def test_a_section_anchor_ignores_an_edit_to_another_section(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "the Drift section is the moat claim", "--concerns", SECTION)

    (root / "guide.md").write_text(DOC.replace("Unrelated.", "Completely rewritten."))
    assert _drift(root) == []


def test_governs_accepts_a_section_and_never_drifts(tmp_path: Path):
    """A named section is a locus a policy can govern ("this section holds only status") — unlike a line
    range, which is refused, because it is addressed by position rather than by name."""
    root = _repo(tmp_path)
    _remember(root, "the Drift section states the claim, never the implementation",
              "--governs", SECTION)

    (root / "guide.md").write_text(DOC.replace("Drift is the moat of this tool.", "Rewritten entirely."))
    assert _drift(root) == [], "a policy anchor carries no content hash, so it cannot drift"

    refused = runner.invoke(app, ["remember", "x", "--repo", str(root), "--why", "w",
                                  "--governs", "file:guide.md:L5-L7"])
    assert refused.exit_code == 0 and "not a line range" in refused.output


def test_a_governs_section_survives_a_rewrite_and_reanchors_a_rename(tmp_path: Path):
    """The two policy paths composed. A ``--governs`` anchor carries no hash, so rewriting the section
    is silent (that is the point) — and that also means a rename has nothing to match by, so it lands as
    hard drift. Which is the honest signal: the named locus is gone. ``reanchor`` is what the hard-drift
    line leads with, and it keeps the policy kind (feedback-v4 #1), so the composition closes.
    """
    root = _repo(tmp_path)
    doc = root / "guide.md"
    mem = _remember(root, "the Drift section states the claim, never the implementation",
                    "--governs", SECTION)

    doc.write_text(DOC.replace("Drift is the moat of this tool.", "Rewritten entirely."))
    assert _drift(root) == [], "a policy anchor has no content hash to drift"

    doc.write_text(DOC.replace("## Drift\n", "## Drift detection\n"))
    assert [(k, loc) for k, loc, _ in _drift(root)] == [("hard", SECTION)]
    assert "reanchor" in runner.invoke(app, ["drift", str(root)]).output

    _run(root, "reanchor", mem, SECTION, "file:guide.md#drift-detection")
    assert _drift(root) == []
    artifact = next((root / "yigraf" / "memory").glob("*.md")).read_text()
    assert "governs-v1" in artifact, "the locus repair must not convert a policy into a content anchor"


def test_a_section_can_be_the_evidence_that_grounds_a_belief(tmp_path: Path):
    """A section flows through every relation an anchored locus does, not only ``concerns`` — so a
    measurement written up under one heading can carry the ``empirical`` tier, and rewriting *that*
    section is what withdraws it."""
    root = _repo(tmp_path)
    notes = root / "notes.md"
    notes.write_text("# Notes\n\nintro\n\n## Measurement\n\ntorque saturates at 12 rad/s.\n")
    _remember(root, "the controller saturates", "--concerns", "sym:code.py#f",
              "--grounding", "empirical", "--evidence", "file:notes.md#measurement")
    assert _drift(root) == []

    notes.write_text("# Notes\n\nintro\n\n## Measurement\n\ntorque saturates at 30 rad/s.\n")
    graph, _ = build_graph(root, default_config())
    assert [(d.kind, d.relation, d.locator) for d in compute_drift(graph)] == [
        ("soft", "grounded_by", "file:notes.md#measurement")]


def test_a_section_can_be_a_rejection_premise(tmp_path: Path):
    """The premise oracle asks whether the locus EXISTS, and a section is a locus — so
    ``--rejected-invalidated-when file:plan.md#redis`` withdraws the rejection once that section is
    written, which is finer than waiting for a whole file to appear."""
    root = _repo(tmp_path)
    (root / "d.md").write_text("# D\n\nx\n\n## Redis Plan\n\nwe will add redis.\n")
    mem = _remember(root, "no cache layer", "--concerns", "sym:code.py#f",
                    "--rejected", "add redis",
                    "--rejected-invalidated-when", "file:d.md#redis-plan")
    shown = runner.invoke(app, ["show", mem, "--repo", str(root)]).output
    assert "d.md#redis-plan" in shown
    assert "withdrawn" in shown.lower(), "the premise holds, so the rejection is withdrawn"


# ── Guidance: every message names a form that works (design law #1) ───────────────────────────────


def test_an_ambiguous_slug_is_refused_with_the_fix(tmp_path: Path):
    root = _repo(tmp_path)
    (root / "dup.md").write_text("# A\n\n## Dup\n\nx\n\n## Dup\n\ny\n")
    out = runner.invoke(app, ["remember", "x", "--repo", str(root), "--why", "w",
                              "--concerns", "file:dup.md#dup"]).output
    assert "names 2 headings" in out and "file:dup.md:L<a>-L<b>" in out
    assert "Captured" not in out, "an unaddressable locator must not land"


def test_a_non_markdown_path_is_guided_to_the_form_that_works(tmp_path: Path):
    root = _repo(tmp_path)
    (root / "cfg.txt").write_text("a\nb\n")
    out = runner.invoke(app, ["remember", "x", "--repo", str(root), "--why", "w",
                              "--concerns", "file:cfg.txt#top"]).output
    assert "not markdown" in out and "file:cfg.txt:L<a>-L<b>" in out and "Captured" not in out


def test_an_indexed_code_path_with_a_fragment_is_guided_to_sym(tmp_path: Path):
    """``file:code.py#f`` is a ``sym:`` typo, not a section — so the message names the locator meant."""
    root = _repo(tmp_path)
    out = runner.invoke(app, ["remember", "x", "--repo", str(root), "--why", "w",
                              "--concerns", "file:code.py#f"]).output
    assert "sym:code.py#f" in out and "Captured" not in out


def test_a_slug_typo_dangles_and_names_the_real_heading(tmp_path: Path):
    """A missing heading is a forward reference (D#3), so it warns and dangles rather than blocking —
    but the warning carries the did-you-mean, and calls the locus a section rather than a symbol."""
    root = _repo(tmp_path)
    out = runner.invoke(app, ["remember", "y", "--repo", str(root), "--why", "w",
                              "--concerns", "file:guide.md#drfit"]).output
    assert "no such section" in out and "Did you mean: file:guide.md#drift?" in out
    assert "Captured" in out, "a forward reference still lands"


def test_a_wrong_slug_with_no_near_match_lists_the_available_headings(tmp_path: Path):
    root = _repo(tmp_path)
    out = runner.invoke(app, ["remember", "y", "--repo", str(root), "--why", "w",
                              "--concerns", "file:guide.md#zzzzzz"]).output
    assert "Headings in guide.md:" in out and "drift" in out


def test_the_line_range_drift_line_names_the_section_exit_and_it_works(tmp_path: Path):
    """The executable-guidance discipline (feedback-v4 #15) applied to the new advice: the caveat on a
    drifting markdown line range names a ``reanchor`` to a section, so run it and assert it holds."""
    root = _repo(tmp_path)
    mem = _remember(root, "the Drift section is the moat claim", "--concerns", "file:guide.md:L5-L7")
    (root / "guide.md").write_text(DOC.replace("Intro text.", "Intro text.\n\nAdded later."))

    advice = runner.invoke(app, ["drift", str(root)]).output
    assert "a line range is positional" in advice
    assert f"reanchor {mem} file:guide.md:L5-L7 file:guide.md#<section>" in advice

    _run(root, "reanchor", mem, "file:guide.md:L5-L7", SECTION)
    assert _drift(root) == [], "the taught retry clears the signal"

    # And the belief is now anchored to its subject rather than to a position.
    (root / "guide.md").write_text((root / "guide.md").read_text()
                                   .replace("Drift is the moat of this tool.", "Drift is NOT the moat."))
    assert [(k, loc) for k, loc, _ in _drift(root)] == [("soft", SECTION)]


@pytest.mark.parametrize("label,flag,locus,break_it", [
    ("an inherited section became ambiguous", "--concerns", "file:guide.md#drift",
     lambda doc: doc.write_text(DOC + "\n## Drift\n\nsomething else entirely.\n")),
    ("an inherited section was deleted", "--concerns", "file:guide.md#drift",
     lambda doc: doc.write_text("# Guide\n\nIntro text.\n\n## Other\n\nUnrelated.\n")),
    ("a governed file was deleted", "--governs", "file:guide.md", lambda doc: doc.unlink()),
])
def test_an_inherited_locus_that_stopped_resolving_does_not_refuse_the_supersede(
        tmp_path: Path, label, flag, locus, break_it):
    """The hard guides check a locator the caller **typed**; against an inherited one they punish the
    wrong person.

    A supersede carries the predecessor's loci when neither flag is given, so someone else adding a
    second ``## Drift`` to a governed doc made ``#drift`` ambiguous and refused the supersede — losing a
    mind-change, to a message about heading titles, for a caller who touched no docs and cannot fix it
    without editing one. The deleted-governed-file case behaved the same way before sections existed.
    Unresolvable is the honest reading of a stored locus: the capture lands and drift says the rest.
    """
    root = _repo(tmp_path)
    mem = _remember(root, f"a belief about {locus}", flag, locus)
    break_it(root / "guide.md")

    out = runner.invoke(app, ["supersede", mem, "the restated claim", "--repo", str(root),
                              "--why", "the mind changed"]).output
    assert "Captured" in out, f"{label}: {out}"


def test_a_typed_ambiguous_section_is_still_refused_on_every_capture_verb(tmp_path: Path):
    """The other half: relaxing the guard for an inherited locus must not defeat it for a typed one."""
    root = _repo(tmp_path)
    (root / "guide.md").write_text(DOC + "\n## Drift\n\nsomething else entirely.\n")
    mem = _remember(root, "an unrelated belief", "--concerns", "sym:code.py#f")

    for args in (["remember", "x", "--why", "w", "--concerns", "file:guide.md#drift"],
                 ["supersede", mem, "restated", "--why", "w", "--concerns", "file:guide.md#drift"]):
        out = runner.invoke(app, [*args, "--repo", str(root)]).output
        assert "names 2 headings" in out and "Captured" not in out, args[0]


def test_a_sym_locator_is_never_read_as_a_doc_section(tmp_path: Path):
    """``#`` already separates a symbol from its path, so the section form requires the ``file:``
    prefix — without that guard every ``sym:`` guidance surface answers about headings instead."""
    root = _repo(tmp_path)
    out = runner.invoke(app, ["remember", "x", "--repo", str(root), "--why", "w",
                              "--concerns", "sym:code.py#ghost"]).output
    assert "no such symbol" in out and "heading" not in out


# ── Delivery: the edit hook, and the cache it reads ───────────────────────────────────────────────


@pytest.mark.parametrize("rel,locus", [
    ("cfg.txt", "file:cfg.txt"),
    ("Dockerfile", "file:Dockerfile"),  # mixed case — the example int:file-anchoring itself names
    ("cfg.txt", "file:cfg.txt:L1-L2"),
    ("guide.md", "file:guide.md#drift"),
])
def test_the_edit_hook_speaks_for_every_file_anchor_form(tmp_path: Path, rel, locus):
    """Design law #3: yigraf's value is delivered *at the moment of the edit*. It reached only a
    whole-file anchor on an all-lowercase path — the extractor casefolds a path into its node ids, but a
    ``file:`` anchor node keeps the locator's own spelling and its ``:L``/``#`` suffix, so a governed
    ``Dockerfile`` and every line range seeded nothing and the hook stayed silent.
    """
    from yigraf import retrieval

    root = _repo(tmp_path)
    (root / "cfg.txt").write_text("a\nb\nc\n")
    (root / "Dockerfile").write_text("FROM python:3.11\n")
    _remember(root, f"a belief about {locus}", "--concerns", locus)

    graph, _ = build_graph(root, default_config())
    assert retrieval.context_for_locus(graph, rel, default_config(), root=root) is not None


def test_a_governed_file_edit_invalidates_the_cached_view(tmp_path: Path):
    """A governed Dockerfile or doc is neither an extractable source file nor a yigraf artifact, so
    nothing in the fingerprint moved when one was edited: the cache-backed read paths served a stale
    hash for the very file just changed, so the edit hook was silent while ``status`` — which always
    rebuilds — reported the drift. ``graphdb.governed_file_paths`` closes that.
    """
    root = _repo(tmp_path)
    (root / "Dockerfile").write_text("FROM python:3.11\n")
    _remember(root, "the base image is pinned", "--concerns", "file:Dockerfile")
    _run(root, "context", "base image")  # materializes the view

    (root / "Dockerfile").write_text("FROM python:3.12\n")
    graph, was_cached = graphdb.load_or_build(root, default_config())
    assert not was_cached, "the governed file changed, so the view must be rebuilt"
    assert [(d.kind, d.locator) for d in compute_drift(graph)] == [("soft", "file:Dockerfile")]


def test_the_post_tool_use_hook_injects_the_section_belief_and_stays_silent_elsewhere(tmp_path: Path):
    """The end-to-end delivery path through the real hook entry point — and design law #4 alongside it:
    a *sibling section of the same file* that nothing governs must not be injected."""
    root = _repo(tmp_path)
    _remember(root, "the Drift section is the moat claim", "--concerns", SECTION)

    payload = json.dumps({"tool_name": "Edit", "cwd": str(root),
                          "tool_input": {"file_path": str(root / "guide.md")}})
    out = runner.invoke(app, ["hook", "post-tool-use"], input=payload).output
    assert "the Drift section is the moat claim" in out
    assert "file:guide.md#other" not in out, "only governed sections become nodes at all"

    (root / "scratch.md").write_text("# Scratch\n\n## Notes\n\nnothing governs this.\n")
    quiet = json.dumps({"tool_name": "Edit", "cwd": str(root),
                        "tool_input": {"file_path": str(root / "scratch.md")}})
    assert runner.invoke(app, ["hook", "post-tool-use"], input=quiet).output.strip() == ""
