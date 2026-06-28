"""Source-vs-signature render A/B — Phase-3 task #4 (the gate for flipping ``retrieval.render``).

Both arms are identical yigraf-on (ambient hooks + the yigraf Skill, so the agent reaches for
``yigraf context``); the ONLY variable is ``retrieval.render`` in ``yigraf/config.yaml``:

- ``signature_only`` (current default) — ``yigraf context`` returns locator + signature; the agent must
  open the file to read a body it needs.
- ``source_for_seeds`` — the top-ranked symbols come back as verbatim, line-numbered source, so the body
  is *already* in context ("treat as Read") and a follow-up Read should be unnecessary.

The decision rule (CodeGraph methodology, see ``docs/research/codegraph-analysis.md``): flip the default to
``source_for_seeds`` only if it **cuts Read/tool-calls** on body-needing questions **without** a
disproportionate token cost. Questions are chosen to *need the body* — a pure-signature answer is
insufficient, which is exactly where the two modes diverge. Floor model = Sonnet (same policy as run_ab).

Run (≥4 runs/arm, multi-question — the flip criteria):
    uv run python scripts/eval/render_ab.py --repo . --runs 4
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_ab  # noqa: E402
from parse_run import summarize  # noqa: E402

MODES = ("signature_only", "source_for_seeds")

#: Body-needing questions: the answer hinges on implementation detail a signature can't carry, so under
#: signature_only the agent must Read the file and under source_for_seeds it shouldn't. Targets real
#: Python symbols in yigraf's own (Python-only) index.
QUESTIONS = [
    "In this repo, what value does `survival_of` in src/yigraf/counters.py return when the file was "
    "introduced in the most recent commit, and how does it arrive at that — name the helper it delegates "
    "to and the exact fallback. Be specific about the implementation.",
    "What does `content_hash` in src/yigraf/astnorm.py exclude from the hash so that a pure rename "
    "re-anchors instead of reporting a deletion? Point to the specific mechanism in the code.",
]


def _set_render(repo: Path, mode: str):
    """Set ``retrieval.render`` in the workspace config; return restore() (comments are restored too)."""
    cfg_path = repo / "yigraf" / "config.yaml"
    bak = cfg_path.with_suffix(".yaml.render-bak")
    shutil.copy2(cfg_path, bak)
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    cfg.setdefault("retrieval", {})["render"] = mode
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return lambda: shutil.move(str(bak), str(cfg_path))


def _fmt_row(label: str, sig: dict, src: dict, lower_better: bool = True) -> str:
    a, b = src.get(label, 0), sig.get(label, 0)  # a = source arm, b = signature (baseline)
    delta = "" if not b else f" ({'▼' if (a < b) == lower_better else '▲'}{abs((a - b) / b * 100):.0f}%)"
    return f"    {label:<13} signature={b:g}  source={a:g}{delta}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--runs", type=int, default=4, help="Runs per question per arm (flip criteria: ≥4).")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    repo = args.repo.resolve()
    out = args.out or (Path(__file__).parent / "runs" / f"render-{time.strftime('%Y%m%d-%H%M%S')}")
    out.mkdir(parents=True, exist_ok=True)
    empty_mcp = out / "empty-mcp.json"
    empty_mcp.write_text(json.dumps({"mcpServers": {}}))
    settings = repo / ".claude" / "settings.local.json"  # the repo's real ambient yigraf hooks
    if not settings.exists():
        print("! no .claude/settings.local.json — run `yigraf install-claude-hooks` first.", file=sys.stderr)
        sys.exit(1)

    print(f"Render A/B · {len(QUESTIONS)} question(s) × {args.runs} run(s)/arm · model={args.model} · repo={repo}\n")
    summaries: dict[str, dict] = {}
    for mode in MODES:
        restore = _set_render(repo, mode)
        runs = []
        try:
            print(f"▶ render={mode}")
            for qi, q in enumerate(QUESTIONS):
                for r in range(args.runs):
                    t = out / f"{mode}__q{qi}__{r}.jsonl"
                    print(f"    q{qi} run {r + 1}/{args.runs} …", flush=True)
                    m = run_ab._run_one(mode, q, repo, settings, empty_mcp, args.model, args.effort,
                                        t, args.timeout, "bypassPermissions")
                    if m is not None:
                        runs.append(m)
        finally:
            restore()
        summaries[mode] = summarize(runs)

    sig, src = summaries[MODES[0]], summaries[MODES[1]]
    print("\n=== signature_only vs source_for_seeds (medians; ▼ = source better) ===")
    if not sig or not src:
        print("  ! a run arm produced no metrics — check transcripts in", out)
    else:
        for field in ("reads", "tool_calls", "greps", "duration_ms"):
            print(_fmt_row(field, sig, src))
        print(_fmt_row("input_tokens", sig, src, lower_better=True))
        print(_fmt_row("output_tokens", sig, src, lower_better=True))
        print("\n  Decision: flip default to source_for_seeds only if reads/tool-calls drop materially "
              "without a disproportionate token rise. n is small + nested — treat as directional.")
    print(f"\ntranscripts in {out}")


if __name__ == "__main__":
    main()
