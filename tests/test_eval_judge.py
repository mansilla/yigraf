"""The enforceable-axis judge (scripts/eval/judge.py).

Pins the deterministic scorer's contract offline (no `claude`): a transcript that re-verifies against
governance scores `re_verified`; one that edits blind doesn't; and the two-arm verdict fires only when
the hook actually changed behaviour (with re-verified, without blind).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "eval"))
import judge  # noqa: E402


def _t(tmp_path: Path, name: str, objects: list[dict]) -> Path:
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(o) for o in objects) + "\n", encoding="utf-8")
    return p


def _assistant(texts=(), tools=()):
    content = [{"type": "text", "text": t} for t in texts]
    content += [{"type": "tool_use", "name": n, "input": i} for n, i in tools]
    return {"type": "assistant", "message": {"role": "assistant", "content": content}}


def test_re_verified_when_agent_acknowledges_and_verifies(tmp_path: Path):
    t = _t(tmp_path, "with.jsonl", [
        {"type": "user", "message": {"content": [{"type": "tool_result",
            "content": "⚠ task:auth/1 → sym:auth/session.py#refresh changed since anchored — re-verify or relink."}]}},
        _assistant(
            texts=["The hook flags drift on int:session-expiry — let me re-verify before editing."],
            tools=[("Bash", {"command": "uv run yigraf context \"session expiry\""}),
                   ("Edit", {"file_path": "auth/session.py"})],
        ),
    ])
    s = judge.score_transcript(t)
    assert s.re_verified is True
    assert s.governance_mentions >= 1 and s.verification_actions >= 1
    assert s.edits == 1 and s.drift_injection_seen is True


def test_edited_blind_when_no_governance_or_verification(tmp_path: Path):
    t = _t(tmp_path, "without.jsonl", [
        _assistant(texts=["I'll tweak the refresh function."],
                   tools=[("Edit", {"file_path": "auth/session.py"})]),
    ])
    s = judge.score_transcript(t)
    assert s.re_verified is False
    assert s.governance_mentions == 0 and s.verification_actions == 0 and s.edits == 1


def test_reading_a_governance_artifact_counts_as_verification(tmp_path: Path):
    t = _t(tmp_path, "read.jsonl", [
        _assistant(tools=[("Read", {"file_path": "/repo/yigraf/intents/session-expiry.md"})]),
    ])
    assert judge.score_transcript(t).verification_actions == 1


def test_reading_the_graph_directly_counts_as_verification(tmp_path: Path):
    # Regression from the first live ENFORCED run: the agent guessed a non-existent `yigraf show`, then
    # re-verified by reading graph.json directly via Bash. That IS verification — the judge must catch it.
    t = _t(tmp_path, "graphread.jsonl", [
        _assistant(tools=[("Bash", {"command": "python -c \"import json; json.load(open('yigraf/graph.json'))\""})]),
    ])
    assert judge.score_transcript(t).verification_actions == 1


def test_verdict_enforced_only_when_with_reverifies_and_without_blind(tmp_path: Path):
    with_s = judge.score_transcript(_t(tmp_path, "w.jsonl", [
        _assistant(texts=["drift on int:x — re-verifying"], tools=[("Edit", {"file_path": "a.py"})])]))
    without_s = judge.score_transcript(_t(tmp_path, "wo.jsonl", [
        _assistant(texts=["just editing"], tools=[("Edit", {"file_path": "a.py"})])]))
    assert judge.verdict(with_s, without_s)["enforced"] is True
    # If neither re-verifies, the hook did NOT enforce.
    assert judge.verdict(without_s, without_s)["enforced"] is False
