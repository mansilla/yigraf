"""Parse a Claude Code headless transcript into agent-behaviour metrics.

The eval harness measures what the CodeGraph study said to measure: **tool-call count, Read/Grep
counts, wall-time** — not just tokens (a token-cheap answer that triggers a Read is *more* expensive
end-to-end). Tokens are summed **per assistant turn**, not read off the final ``result`` object,
because that last-turn ``usage`` undercounts a multi-turn run.

Input is a file of ``claude -p --output-format stream-json`` output: one JSON object per line, each
tagged with a ``type`` (``system`` | ``assistant`` | ``user`` | ``result``). Tool calls live as
``tool_use`` content blocks inside ``assistant`` messages; per-turn tokens live on each assistant
message's ``usage``. This module has **no dependency on the ``claude`` binary** — it parses a captured
file — so it's unit-testable offline (that's deliberate: the parser is the part that must be correct).
"""
from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass, field, asdict
from pathlib import Path

#: Built-in tools we bucket explicitly — the discovery loop the index is meant to displace.
_DISCOVERY_TOOLS = ("Read", "Grep", "Glob", "Bash")


@dataclass
class RunMetrics:
    """One agent run, reduced to the numbers an A/B arm compares."""

    tool_calls: int = 0
    by_tool: dict[str, int] = field(default_factory=dict)
    reads: int = 0
    greps: int = 0
    globs: int = 0
    bashes: int = 0
    mcp_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    num_turns: int = 0
    duration_ms: int = 0
    cost_usd: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


def _iter_objects(path: Path):
    """Yield each JSON object from a stream-json file, skipping blanks and unparseable lines."""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue  # a stray log line never aborts the parse


def parse_file(path: Path) -> RunMetrics:
    """Reduce one stream-json transcript to :class:`RunMetrics`."""
    m = RunMetrics()
    for obj in _iter_objects(path):
        kind = obj.get("type")
        if kind == "assistant":
            _account_assistant(obj.get("message") or {}, m)
        elif kind == "result":
            # Final summary line — authoritative for wall-time / turns / cost only.
            m.duration_ms = int(obj.get("duration_ms") or m.duration_ms)
            m.num_turns = int(obj.get("num_turns") or m.num_turns)
            m.cost_usd = float(obj.get("total_cost_usd") or m.cost_usd)
    return m


def _account_assistant(message: dict, m: RunMetrics) -> None:
    """Tally tool calls + per-turn tokens from one assistant message (the per-turn sum, not result.usage)."""
    for block in message.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            name = block.get("name") or "<unknown>"
            m.tool_calls += 1
            m.by_tool[name] = m.by_tool.get(name, 0) + 1
            if name == "Read":
                m.reads += 1
            elif name == "Grep":
                m.greps += 1
            elif name == "Glob":
                m.globs += 1
            elif name == "Bash":
                m.bashes += 1
            elif name.startswith("mcp__"):
                m.mcp_calls += 1
    usage = message.get("usage") or {}
    # Cache reads/creation are still input the model processed — count them so the comparison is honest.
    m.input_tokens += int(usage.get("input_tokens") or 0)
    m.input_tokens += int(usage.get("cache_read_input_tokens") or 0)
    m.input_tokens += int(usage.get("cache_creation_input_tokens") or 0)
    m.output_tokens += int(usage.get("output_tokens") or 0)


# --------------------------------------------------------------------------------------------------
# Aggregation across runs (median is the headline — run-to-run variance is large; CodeGraph uses n≥4)
# --------------------------------------------------------------------------------------------------

_MEDIAN_FIELDS = ("tool_calls", "reads", "greps", "globs", "bashes", "mcp_calls",
                  "input_tokens", "output_tokens", "num_turns", "duration_ms", "cost_usd")


def summarize(runs: list[RunMetrics]) -> dict:
    """Median of each field across an arm's runs (median, not mean — tails are real, see README)."""
    if not runs:
        return {}
    out = {"runs": len(runs)}
    for f in _MEDIAN_FIELDS:
        out[f] = statistics.median(getattr(r, f) for r in runs)
    return out


def _main() -> None:
    ap = argparse.ArgumentParser(description="Parse a claude stream-json transcript into metrics.")
    ap.add_argument("files", nargs="+", type=Path, help="One or more stream-json transcript files.")
    ap.add_argument("--json", action="store_true", help="Emit JSON (default: a short table).")
    args = ap.parse_args()

    runs = [parse_file(p) for p in args.files]
    if args.json:
        print(json.dumps({"runs": [r.as_dict() for r in runs], "summary": summarize(runs)}, indent=2))
        return
    for p, r in zip(args.files, runs):
        print(f"{p.name}: {r.tool_calls} tools "
              f"(Read {r.reads}, Grep {r.greps}, Glob {r.globs}, Bash {r.bashes}, mcp {r.mcp_calls}) · "
              f"{r.num_turns} turns · {r.duration_ms/1000:.1f}s · "
              f"{r.input_tokens + r.output_tokens} tok · ${r.cost_usd:.3f}")
    if len(runs) > 1:
        s = summarize(runs)
        print(f"\nmedian of {s['runs']}: {s['tool_calls']} tools "
              f"(Read {s['reads']}, Grep {s['greps']}, Bash {s['bashes']}) · "
              f"{s['duration_ms']/1000:.1f}s · {int(s['input_tokens'] + s['output_tokens'])} tok")


if __name__ == "__main__":
    _main()
