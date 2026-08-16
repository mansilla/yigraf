"""The eval harness's transcript parser (scripts/eval/parse_run.py).

The parser is the part that must be correct — it's offline-testable without the ``claude`` binary, so
we pin its contract here: tool-call bucketing, token accounting (the authoritative end-of-run
``result.usage``, with the per-turn sum only as a fallback), and median aggregation across runs.
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
    # Tokens come from the authoritative result.usage (999/999), NOT the per-turn sum (150/30). The
    # per-turn sum is wrong both ways on a real transcript: streaming turns carry partial
    # output_tokens (undercounts ~80×) and repeat cache_read_input_tokens (overcounts ~2.5×).
    assert m.input_tokens == 999 and m.output_tokens == 999
    assert m.num_turns == 2 and m.duration_ms == 4200 and m.cost_usd == pytest.approx(0.12)


def test_result_usage_counts_cache_tokens_and_wins_over_per_turn_sum(tmp_path: Path):
    """Cache reads/creation are input the model processed, so they count — and the end-of-run totals
    replace the per-turn estimate rather than adding to it."""
    t = _transcript(tmp_path, "cached.jsonl", [
        _assistant(["Read"], inp=2, out=3),
        _assistant(["Read"], inp=2, out=3),
        {"type": "result", "subtype": "success", "duration_ms": 100, "num_turns": 2,
         "total_cost_usd": 0.01,
         "usage": {"input_tokens": 4, "cache_read_input_tokens": 64354,
                   "cache_creation_input_tokens": 19687, "output_tokens": 814}},
    ])
    m = parse_run.parse_file(t)
    assert m.input_tokens == 4 + 64354 + 19687     # not 4 + the per-turn 4
    assert m.output_tokens == 814                  # not the streamed-partial 6


def test_per_turn_sum_is_the_fallback_when_result_usage_is_absent(tmp_path: Path):
    """A transcript with no final result.usage still reports something — the old per-turn path."""
    t = _transcript(tmp_path, "noresult.jsonl", [
        _assistant(["Read"], inp=100, out=20),
        _assistant(["Edit"], inp=50, out=10),
    ])
    m = parse_run.parse_file(t)
    assert m.input_tokens == 150 and m.output_tokens == 30


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
