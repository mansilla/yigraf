"""Judge the *enforceable* axis: did yigraf's drift hook change what the agent did?

The structural A/B (run_ab.py) measures legibility — fewer tool calls to the same answer. This judges
the thing only yigraf has: when a governed symbol drifts and the hook fires, does the agent **re-verify
against what governs the code** instead of editing blind? That's the moat; this is the only metric that
measures it.

The scorer is deterministic and **offline-testable** (it reads a captured transcript, no `claude`
needed) — same discipline as parse_run.py. It detects enforcement *behaviour* in the transcript
(acknowledging governance + taking a verification action), which is visible regardless of whether the
hook's injected text itself is logged. The verdict compares the two arms: the hook "enforced" iff the
WITH arm re-verified and the WITHOUT arm edited blind. An optional `--llm` pass adds a model judgment
for the nuanced call.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_run import _iter_objects  # noqa: E402

#: Agent reasoning that shows it registered *governance* (drift / a requirement / a decision / relinking).
_GOVERNANCE = re.compile(
    r"\b(drift|re-?verif|re-?anchor|re-?link|govern|supersed|anchored)\b|(?:int|mem|task):[\w./#-]+",
    re.IGNORECASE,
)
#: A yigraf verb that constitutes verification (re-reading the graph or re-anchoring the link). These
#: are the *real* read/anchor verbs (`yigraf --help`) — note there is no `show`/`query`; an agent that
#: guesses those falls back to reading the graph directly, which `_GOV_READ` (below) catches instead.
_YIGRAF_VERB = re.compile(r"\byigraf\s+(context|drift|link|remember|note-constraint|supersede)\b")
#: Reading *what governs the code* — an authored artifact (intent/memory/plan) OR the projected graph
#: itself. Agents that don't reach for a yigraf verb often inspect `graph.json` directly to check a
#: flagged node (a real verification we'd otherwise miss). Matches relative paths too, so it catches a
#: Bash `cat`/`grep`/`python … open('yigraf/graph.json')`, not just a Read-tool of an artifact path.
_GOV_READ = re.compile(r"yigraf/(?:intents|memory|plans)/|yigraf/graph\.json")
#: The drift-injection signature emitted by retrieval._drift_line — best-effort "did it reach the log".
_DRIFT_INJECTION = re.compile(r"changed since anchored|no longer found|re-verify or relink")
_EDIT_TOOLS = {"Edit", "Write", "MultiEdit"}


@dataclass
class EnforcementScore:
    re_verified: bool
    governance_mentions: int
    verification_actions: int
    edits: int
    drift_injection_seen: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _texts_and_tools(path: Path) -> tuple[list[str], list[tuple[str, dict]], bool]:
    texts: list[str] = []
    tools: list[tuple[str, dict]] = []
    drift_seen = False
    for obj in _iter_objects(path):
        blob = json.dumps(obj)
        if _DRIFT_INJECTION.search(blob):
            drift_seen = True  # injection may surface anywhere (hook output / tool result), so scan raw
        if obj.get("type") == "assistant":
            for block in (obj.get("message") or {}).get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    texts.append(block.get("text") or "")
                elif block.get("type") == "tool_use":
                    tools.append((block.get("name") or "", block.get("input") or {}))
    return texts, tools, drift_seen


def score_transcript(path: Path) -> EnforcementScore:
    """Detect enforcement behaviour in one arm's transcript (deterministic, offline)."""
    texts, tools, drift_seen = _texts_and_tools(path)
    governance = sum(1 for t in texts if _GOVERNANCE.search(t))
    verifications = 0
    edits = 0
    for name, inp in tools:
        if name == "Bash":
            cmd = str(inp.get("command") or "")
            if _YIGRAF_VERB.search(cmd) or _GOV_READ.search(cmd):  # a verb, or reading the graph/artifacts
                verifications += 1
        elif name == "Read" and _GOV_READ.search(str(inp.get("file_path") or inp.get("path") or "")):
            verifications += 1
        elif name in _EDIT_TOOLS:
            edits += 1
    return EnforcementScore(
        re_verified=bool(governance or verifications),
        governance_mentions=governance,
        verification_actions=verifications,
        edits=edits,
        drift_injection_seen=drift_seen,
    )


def verdict(with_score: EnforcementScore, without_score: EnforcementScore) -> dict:
    """The hook ENFORCED iff the WITH arm re-verified and the WITHOUT arm edited blind."""
    enforced = with_score.re_verified and not without_score.re_verified
    return {
        "enforced": enforced,
        "summary": (
            f"with-yigraf {'re-verified' if with_score.re_verified else 'edited blind'} "
            f"(governance×{with_score.governance_mentions}, verify-actions×{with_score.verification_actions}); "
            f"without-yigraf {'re-verified' if without_score.re_verified else 'edited blind'}"
        ),
        "with": with_score.as_dict(),
        "without": without_score.as_dict(),
    }


# --------------------------------------------------------------------------------------------------
# Optional LLM judge — a model verdict over a compact trace, for the nuanced call (gated behind --llm)
# --------------------------------------------------------------------------------------------------

_LLM_RUBRIC = """You are scoring whether a coding agent RE-VERIFIED a change against what governs the code.
The agent edited a symbol that a requirement/decision governs ("drift"). A PASS means: after editing,
the agent acknowledged the governing requirement/decision (or the drift) and confirmed the change still
satisfies it — rather than editing blind. Reply with ONLY a JSON object:
{"verdict": "pass" | "fail", "reason": "<one sentence>"}

Agent trace:
"""


def _compact_trace(path: Path, limit: int = 12000) -> str:
    texts, tools, _ = _texts_and_tools(path)
    lines = []
    for t in texts:
        if t.strip():
            lines.append("THOUGHT: " + " ".join(t.split()))
    for name, inp in tools:
        arg = inp.get("command") or inp.get("file_path") or inp.get("path") or ""
        lines.append(f"TOOL: {name} {arg}".rstrip())
    return "\n".join(lines)[:limit]


def llm_judge(path: Path, model: str = "sonnet") -> dict:
    """Ask a model whether the arm re-verified (optional; needs `claude` on PATH)."""
    prompt = _LLM_RUBRIC + _compact_trace(path)
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json", "--model", model],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180,
        )
        result = json.loads(proc.stdout)
        text = result.get("result") if isinstance(result, dict) else None
        match = re.search(r"\{.*\}", text or "", re.DOTALL)
        return json.loads(match.group(0)) if match else {"verdict": "error", "reason": "no JSON in reply"}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, AttributeError) as exc:
        return {"verdict": "error", "reason": f"{type(exc).__name__}: {exc}"}


def _main() -> None:
    ap = argparse.ArgumentParser(description="Judge the enforceable axis from arm transcripts.")
    ap.add_argument("with_transcript", type=Path, help="The WITH-yigraf arm's stream-json transcript.")
    ap.add_argument("without_transcript", type=Path, nargs="?", help="The WITHOUT arm's transcript.")
    ap.add_argument("--llm", action="store_true", help="Also run the optional model judge on the WITH arm.")
    ap.add_argument("--model", default="sonnet")
    args = ap.parse_args()

    ws = score_transcript(args.with_transcript)
    if args.without_transcript:
        wo = score_transcript(args.without_transcript)
        v = verdict(ws, wo)
        print(json.dumps(v, indent=2))
        print(f"\nENFORCED: {v['enforced']} — {v['summary']}")
    else:
        print(json.dumps(ws.as_dict(), indent=2))
    if args.llm:
        print("\nLLM judge (with arm):", json.dumps(llm_judge(args.with_transcript, args.model)))


if __name__ == "__main__":
    _main()
