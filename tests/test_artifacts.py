"""Intent/plan artifact parsing, rendering, and frontmatter edge writes (docs/m2-notes.md §2)."""
from pathlib import Path

from yigraf.artifacts import (
    add_edge_to_plan,
    read_intent,
    read_plan,
    render_intent,
    render_plan,
)


def test_intent_roundtrips_through_render_and_read(tmp_path: Path):
    p = tmp_path / "session-expiry.md"
    p.write_text(
        render_intent(
            "session-expiry",
            "The system SHALL expire a session after 30m idle.",
            ["Given idle 30m, When a request arrives, Then respond 401.",
             "Given an active session, When a request arrives, Then refresh the timer."],
            "Optimistic-locked refresh; TTL in the session store.",
            status="active",
        )
    )
    intent = read_intent(p)
    assert intent.id == "int:session-expiry"
    assert intent.status == "active"
    assert intent.statement == "The system SHALL expire a session after 30m idle."
    assert len(intent.scenarios) == 2 and intent.scenarios[0].startswith("Given idle 30m")
    assert intent.design == "Optimistic-locked refresh; TTL in the session store."


def test_intent_without_design_has_none(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text(render_intent("x", "SHALL do a thing.", ["Given a, When b, Then c."], None))
    assert read_intent(p).design is None


def test_plan_roundtrips_with_task_numbers_and_states(tmp_path: Path):
    p = tmp_path / "auth-hardening.md"
    p.write_text(render_plan("auth-hardening", "Auth hardening", ["implement expiry", "add store"]))
    plan = read_plan(p)
    assert plan.id == "plan:auth-hardening" and plan.title == "Auth hardening"
    assert [t.id for t in plan.tasks] == ["task:auth-hardening/1", "task:auth-hardening/2"]
    assert all(t.state == "todo" for t in plan.tasks)
    assert plan.tasks[0].description == "implement expiry"


def test_done_checkbox_reads_as_done(tmp_path: Path):
    p = tmp_path / "p.md"
    p.write_text("---\nid: plan:p\nfamily: plan\nedges: {}\n---\n# P\n## Tasks\n- [x] {#1} done it\n")
    assert read_plan(p).tasks[0].state == "done"


def test_add_implements_edge_stamps_anchor_and_algo(tmp_path: Path):
    p = tmp_path / "auth.md"
    p.write_text(render_plan("auth", "Auth", ["do it"]))
    add_edge_to_plan(p, "task:auth/1", "implements", "sym:m.py#f", anchor="H1")
    impl = read_plan(p).tasks[0].implements
    assert len(impl) == 1
    assert impl[0].sym == "sym:m.py#f" and impl[0].anchor == "H1" and impl[0].anchor_algo == "astnorm-v1"


def test_relinking_a_symbol_restamps_rather_than_duplicating(tmp_path: Path):
    p = tmp_path / "auth.md"
    p.write_text(render_plan("auth", "Auth", ["do it"]))
    add_edge_to_plan(p, "task:auth/1", "implements", "sym:m.py#f", anchor="H1")
    add_edge_to_plan(p, "task:auth/1", "implements", "sym:m.py#f", anchor="H2")
    impl = read_plan(p).tasks[0].implements
    assert len(impl) == 1 and impl[0].anchor == "H2"


def test_add_tracks_edge(tmp_path: Path):
    p = tmp_path / "auth.md"
    p.write_text(render_plan("auth", "Auth", ["do it"]))
    add_edge_to_plan(p, "task:auth/1", "tracks", "int:session-expiry")
    assert read_plan(p).tasks[0].tracks == "int:session-expiry"
