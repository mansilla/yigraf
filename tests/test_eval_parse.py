"""The eval harness's transcript parser (scripts/eval/parse_run.py).

The parser is the part that must be correct — it's offline-testable without the ``claude`` binary, so
we pin its contract here: tool-call bucketing, per-turn token summation (not the cumulative result
object), and median aggregation across runs.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "eval"))
import parse_run  # noqa: E402


def _transcript(tmp_path: Path, name: str, objects: list[dict]) -> Path:
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(o) for o in objects) + "\n", encoding="utf-8")
    return p


def _assistant(tools: list[str], inp: int, out: int) -> dict:
    content = [{"type": "tool_use", "name": t, "id": f"id_{i}", "input": {}} for i, t in enumerate(tools)]
    content.insert(0, {"type": "text", "text": "thinking"})
    return {"type": "assistant", "message": {"role": "assistant", "content": content,
                                             "usage": {"input_tokens": inp, "output_tokens": out}}}


def test_parses_tool_calls_and_buckets(tmp_path: Path):
    t = _transcript(tmp_path, "run.jsonl", [
        {"type": "system", "subtype": "init"},
        _assistant(["Read", "Grep", "Read"], inp=100, out=20),
        _assistant(["Edit", "mcp__codegraph__explore"], inp=50, out=10),
        {"type": "result", "subtype": "success", "duration_ms": 4200, "num_turns": 2,
         "total_cost_usd": 0.12, "usage": {"input_tokens": 999, "output_tokens": 999}},
    ])
    m = parse_run.parse_file(t)
    assert m.tool_calls == 5
    assert m.reads == 2 and m.greps == 1 and m.mcp_calls == 1
    assert m.by_tool["Read"] == 2 and m.by_tool["Edit"] == 1
    # Tokens are the per-turn SUM (100+20+50+10), never the cumulative result.usage (999/999).
    assert m.input_tokens == 150 and m.output_tokens == 30
    assert m.num_turns == 2 and m.duration_ms == 4200 and m.cost_usd == pytest.approx(0.12)


def test_skips_blank_and_unparseable_lines(tmp_path: Path):
    p = tmp_path / "noisy.jsonl"
    p.write_text("\n".join([
        "",
        "not json at all",
        json.dumps(_assistant(["Read"], inp=10, out=5)),
        "  ",
    ]) + "\n", encoding="utf-8")
    m = parse_run.parse_file(p)
    assert m.tool_calls == 1 and m.reads == 1 and m.input_tokens == 10


def test_summarize_is_the_median(tmp_path: Path):
    runs = [
        parse_run.parse_file(_transcript(tmp_path, "a.jsonl", [_assistant(["Read"], 1, 1)])),
        parse_run.parse_file(_transcript(tmp_path, "b.jsonl", [_assistant(["Read", "Read", "Read"], 1, 1)])),
        parse_run.parse_file(_transcript(tmp_path, "c.jsonl", [_assistant(["Read", "Read"], 1, 1)])),
    ]
    s = parse_run.summarize(runs)
    assert s["runs"] == 3 and s["reads"] == 2  # median of {1,3,2}
    assert parse_run.summarize([]) == {}
