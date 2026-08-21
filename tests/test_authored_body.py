"""A metadata verb re-stamps ONE field and must not delete the rest of the artifact.

Field report: `yigraf reaffirm mem:<id>` silently dropped 125 words — two paragraphs a human had added
by hand that morning, extending the belief with a second instance of the same trap and the escape it
implies. The verb re-read the file, rebuilt the body from (statement, why, alternatives) — the only
three things ``_parse_body`` recognizes — and wrote back the difference. It was caught by a diffstat
showing 5 deletions where sibling files showed 1; nothing in the output said anything was removed.

The blast radius was every verb that round-trips an artifact to edit its frontmatter: `reaffirm`,
`reanchor`, `attest`, `pin`, `unlink`, and `supersede` (which truncates the PREDECESSOR — the
historical record most worth keeping intact). `artifacts.update_intent_frontmatter` already had this
right for intents: mutate the parsed frontmatter, write the body back untouched. These tests hold the
memory family to the same invariant, in both halves of the file.
"""
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from yigraf import filelog, memory
from yigraf.cli import app

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"

#: What a human adds by hand: prose in a shape the canonical serializer does not model at all — a
#: bolded lead-in that is not `**Why:**`/`**Rejected:**`, and a closing paragraph with no marker.
EXTENSION = (
    "\n**Which escape depends on what the descendant is.** When it is your own mark, take the capture "
    "and decide the action yourself on pointerup.\n\n"
    "Anything interactive under a capturing ancestor hits this, and it fails silently every time.\n"
)


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _run(args: list[str]):
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result


def _extended(root: Path, statement: str = "the pointer is captured on pointerdown") -> tuple[str, Path]:
    """Capture a memory, then extend its body by hand the way a human does. Returns (id, path)."""
    res = _run(["remember", statement, "--repo", str(root), "--why", "a drag that leaves keeps tracking",
                "--rejected", "binding click on each mark", "--concerns", SYM])
    mem_id = res.output.split("Captured ")[1].split(" ")[0]
    path = memory.find_memory(root, mem_id)
    path.write_text(path.read_text() + EXTENSION)
    return mem_id, path


# --------------------------------------------------------------------------------------------------
# The serializer itself
# --------------------------------------------------------------------------------------------------


def test_render_round_trips_a_hand_extended_body_byte_for_byte(tmp_path: Path):
    root = _repo(tmp_path)
    _, path = _extended(root)
    before = path.read_text()
    assert memory.render_memory(memory.read_memory(path)) == before


def test_a_fresh_capture_still_gets_the_canonical_body(tmp_path: Path):
    """Nothing to carry ⇒ compose the canonical shape, exactly as before (no authored body yet)."""
    root = _repo(tmp_path)
    _run(["remember", "sessions refresh on the read path", "--repo", str(root),
          "--why", "the write path is hot", "--rejected", "a cron sweep", "--concerns", SYM])
    path = sorted((root / "yigraf" / "memory").glob("*.md"))[0]
    body = path.read_text().split("---\n", 2)[2]
    assert body == ("## sessions refresh on the read path\n\n"
                    "**Why:** the write path is hot\n\n"
                    "**Rejected:** a cron sweep\n")


def test_rendering_refuses_to_truncate_when_the_canonical_triple_changed(tmp_path: Path):
    """A changed belief is a `supersede`, not an edit — so an in-place body edit is a caller bug.

    Both ways out of it lose something the caller wanted (the prose, or the edit). Raise instead, and
    raise BEFORE any write: the artifact on disk stays whole and the message names the right verb.
    """
    root = _repo(tmp_path)
    _, path = _extended(root)
    node = memory.read_memory(path)
    node.statement = "a different belief entirely"
    with pytest.raises(ValueError, match="supersedes this one, not an edit"):
        memory.render_memory(node)
    assert "Anything interactive" in path.read_text()  # untouched on disk


def test_an_unrecognized_frontmatter_key_survives_a_re_stamp(tmp_path: Path):
    """Version skew: the store is committed and shared, so an older engine must not strip a newer
    engine's field while re-stamping one anchor. Anything outside `_MANAGED_META` rides through."""
    root = _repo(tmp_path)
    mem_id, path = _extended(root)
    path.write_text(path.read_text().replace("family: memory\n", "family: memory\nreviewed_by: rm\n", 1))
    _run(["reaffirm", mem_id, "--repo", str(root)])
    assert "reviewed_by: rm" in path.read_text()


def test_every_key_render_writes_is_a_key_render_owns():
    """The one way the carry-through can rot: a NEW frontmatter field added to `render_memory` and not
    to `_MANAGED_META` would be read back as unrecognized — and then a verb that *clears* it (a
    conditionally-written key like `pinned`, dropped by `pin --off`) would find the stale on-disk value
    riding through `extra_meta` and silently un-clear itself. Assert the containment instead of trusting
    two lists to be edited together."""
    everything = memory.Memory(
        id="mem:x", seq=1, slug="s", type="decision", statement="s", why="w", alternatives="a",
        rejected_valid_when=["int:i"], rejected_invalidated_when=["file:f"], serves=["int:i"],
        concerns=[memory.Concern(sym=SYM, anchor="h", anchor_algo="astnorm-v1")],
        evidence=[memory.Evidence(ref="commit:abc")], supersedes=["mem:o"],
        pending_supersedes=["mem:p"], equivalent_to=["mem:e"], superseded_by="mem:n",
        promotable=True, pinned=True, provenance={"source": "cli"},
    )
    written = yaml.safe_load(memory.render_memory(everything).split("---\n")[1])
    assert set(written) <= memory._MANAGED_META, set(written) - memory._MANAGED_META


# --------------------------------------------------------------------------------------------------
# Every verb that edits frontmatter on a standing artifact
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("verb", ["reaffirm", "attest", "pin", "reanchor", "unlink"])
def test_a_metadata_verb_keeps_what_a_human_added(tmp_path: Path, verb: str):
    root = _repo(tmp_path)
    mem_id, path = _extended(root, f"the pointer is captured for {verb}")
    args = {
        "reaffirm": [verb, mem_id, "--repo", str(root)],
        "attest": [verb, mem_id, "--repo", str(root)],
        "pin": [verb, mem_id, "--repo", str(root)],
        "reanchor": [verb, mem_id, SYM, SYM, "--repo", str(root)],
        "unlink": [verb, mem_id, SYM, "--repo", str(root)],
    }[verb]
    _run(args)
    after = path.read_text()
    assert "**Which escape depends on what the descendant is.**" in after
    assert "Anything interactive under a capturing ancestor hits this" in after


def test_supersede_keeps_the_predecessors_hand_extension(tmp_path: Path):
    """The predecessor is edited in place to stamp `superseded_by` — the one artifact whose body is
    pure history, and the one a truncation is least recoverable from."""
    root = _repo(tmp_path)
    old_id, old_path = _extended(root)
    _run(["supersede", old_id, "selection is decided on pointerup", "--repo", str(root),
          "--why", "capture retargets the compatibility mouse events", "--concerns", SYM])
    after = old_path.read_text()
    assert "superseded_by:" in after and "status: superseded" in after  # the re-stamp landed
    assert "**Which escape depends on what the descendant is.**" in after
    assert "Anything interactive under a capturing ancestor hits this" in after


# --------------------------------------------------------------------------------------------------
# The extension is carried, not asserted (mem:7ac9f8fae656db5f's reasoning, applied)
# --------------------------------------------------------------------------------------------------


def test_the_extension_never_re_identifies_the_node(tmp_path: Path):
    """Prose the canonical shape does not model changes nothing the belief ASSERTS, so it must stay
    out of the content-addressed id and off the wire — or a hand extension would fork the node from a
    teammate's byte-identical capture and re-key its assertion on every edit."""
    root = _repo(tmp_path)
    res = _run(["remember", "the pointer is captured on pointerdown", "--repo", str(root),
                "--why", "a drag that leaves keeps tracking", "--rejected", "binding click on each mark",
                "--concerns", SYM])
    mem_id = res.output.split("Captured ")[1].split(" ")[0]
    before = {a.id: a.body for a in filelog.assertions_from_repo(root)}

    path = memory.find_memory(root, mem_id)
    path.write_text(path.read_text() + EXTENSION)
    assert memory.read_memory(path).id == mem_id
    assert {a.id: a.body for a in filelog.assertions_from_repo(root)} == before
