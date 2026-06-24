"""Query-driven retrieval (`yigraf context`) — the M4 done-test (docs/retrieval-design.md)."""
from pathlib import Path

from typer.testing import CliRunner

from yigraf import retrieval
from yigraf.cli import app
from yigraf.config import default_config
from yigraf.extract import build_graph

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"
SRC = "auth/session.py"


def _repo(tmp_path: Path, status: str = "active") -> Path:
    """Repo with an intent (status configurable), a task tracking it, linked to a symbol."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["intent", "session-expiry", "--repo", str(tmp_path),
                               "-s", "The system SHALL expire a session after 30m idle.",
                               "--scenario", "Given idle 30m, When a request arrives, Then 401.",
                               "--status", status]).exit_code == 0
    assert runner.invoke(app, ["plan", "auth", "--repo", str(tmp_path), "-t", "Auth",
                               "--task", "implement idle expiry"]).exit_code == 0
    assert runner.invoke(app, ["link", "task:auth/1", "int:session-expiry", "--repo", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["link", "task:auth/1", SYM, "--repo", str(tmp_path)]).exit_code == 0
    return tmp_path


def _ctx(root: Path, query: str, **kw):
    graph, _ = build_graph(root, default_config())
    return retrieval.context(graph, query, default_config(), **kw)


def test_terms_splits_identifiers_and_paths():
    assert retrieval.terms("auth/session.py#validateToken") == [
        "auth", "session", "py", "validate", "token"]


def test_context_returns_the_requirement_and_the_symbol_signature(tmp_path: Path):
    result = _ctx(_repo(tmp_path), "session expiry")
    assert "The system SHALL expire a session" in result.text  # the requirement
    assert "def refresh(token):" in result.text                # the implementer, as a signature
    assert "return token" not in result.text                   # signature, NOT the body/source


def test_context_token_estimate_is_small(tmp_path: Path):
    result = _ctx(_repo(tmp_path), "session expiry")
    assert result.nodes_rendered > 0
    assert 0 < result.token_estimate < 500  # a tiny map, not file dumps


def test_query_matches_a_code_identifier(tmp_path: Path):
    assert SYM in _ctx(_repo(tmp_path), "refresh").text


def test_editing_a_linked_symbol_surfaces_drift_in_context(tmp_path: Path):
    root = _repo(tmp_path)
    (root / SRC).write_text("def refresh(token):\n    return token + 1\n")
    text = _ctx(root, "session expiry").text
    assert "Drift" in text and SYM in text and "re-verify or relink" in text


def test_satisfied_but_drifted_intent_emits_reconcile(tmp_path: Path):
    root = _repo(tmp_path, status="satisfied")
    (root / SRC).write_text("def refresh(token):\n    return token + 1\n")
    text = _ctx(root, "session expiry").text
    assert "satisfied but not verified" in text


def test_satisfied_and_clean_intent_does_not_reconcile(tmp_path: Path):
    text = _ctx(_repo(tmp_path, status="satisfied"), "session expiry").text
    assert "not verified" not in text  # live, undrifted link → verified


def test_family_filter_restricts_to_one_family(tmp_path: Path):
    text = _ctx(_repo(tmp_path), "session expiry", family="intent").text
    assert "int:session-expiry" in text
    assert "sym:" not in text and "plan:" not in text


def test_tight_budget_truncates_and_notes_elision(tmp_path: Path):
    result = _ctx(_repo(tmp_path), "session expiry", budget_tokens=20)
    assert result.nodes_rendered < result.nodes_total
    assert "elided" in result.text


def test_context_cli_runs_and_reports_token_count(tmp_path: Path):
    result = runner.invoke(app, ["context", "session expiry", "--repo", str(_repo(tmp_path))])
    assert result.exit_code == 0, result.output
    assert "tokens" in result.output and "def refresh(token):" in result.output
