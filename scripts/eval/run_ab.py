"""A/B eval harness: does yigraf change how an agent works? (CodeGraph's methodology, adapted.)

Runs the same question through `claude -p` **with** yigraf's hooks and **without** them, on the same
repo, N times each, and tabulates the deltas the CodeGraph study said to track: **tool calls, Read,
Grep, wall-time** (not just tokens — a token-cheap answer that triggers a Read is more expensive
end-to-end). The model is pinned to the **floor model (Sonnet)** on purpose: an affordance that lands
on Sonnet generalizes up to stronger hosts; one that only works on Opus doesn't generalize down to the
agents most users actually run.

This is the instrument that turns yigraf's "legible + enforceable" claim from a design assertion into
a measured one — and the gate for the source-vs-signature experiment (A3): flip the render knob, re-run
this, compare. See ``scripts/eval/README.md`` for methodology, caveats, and the floor-model policy.

The two arms differ in exactly one thing — whether yigraf's PostToolUse/SessionStart hooks are wired —
so any delta is attributable to yigraf. Transcript parsing lives in :mod:`parse_run` (offline-testable).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_run import RunMetrics, parse_file, summarize  # noqa: E402
import judge  # noqa: E402

ARMS = ("with", "without")


def _with_settings(hook_cmd: str) -> dict:
    """Settings for the WITH-yigraf arm: the same PostToolUse + SessionStart hooks `install-claude-hooks`
    wires, but pointed at a configurable launcher (``--hook-cmd``, default ``uv run yigraf``)."""
    return {
        "hooks": {
            "PostToolUse": [
                {"matcher": "Edit|Write|MultiEdit",
                 "hooks": [{"type": "command", "command": f"{hook_cmd} hook post-tool-use"}]},
            ],
            "SessionStart": [
                {"matcher": "",
                 "hooks": [{"type": "command", "command": f"{hook_cmd} hook session-start"}]},
            ],
        }
    }


def _arm_command(arm: str, question: str, settings_path: Path, mcp_path: Path,
                 model: str, effort: str, permission_mode: str) -> list[str]:
    cmd = [
        "claude", "-p", question,
        "--output-format", "stream-json", "--verbose",
        "--model", model, "--effort", effort,
        "--settings", str(settings_path),
        # Neutralize ambient MCP servers so the only difference between arms is the yigraf hooks.
        "--strict-mcp-config", "--mcp-config", str(mcp_path),
        # Headless `claude -p` has no one to approve a Write/Edit prompt (stdin is /dev/null), so an
        # unattended permission mode is mandatory — otherwise edits never land. For the *enforceable*
        # case that's fatal: the agent's edit is what drifts the symbol, and PostToolUse only fires
        # after a *successful* edit, so a blocked edit means the hook never fires and BOTH arms look
        # "blind". Bypass (not just acceptEdits) so no yigraf verb the agent reaches for gets silently
        # denied — a blocked `yigraf context` would read as "didn't re-verify" and false-negative the
        # judge. Safe here: the harness only ever runs in a git-reversible sandbox (teardown is
        # `git checkout`), and both arms get the identical mode, so it can't bias the comparison.
        "--permission-mode", permission_mode,
    ]
    return cmd


def _run_one(arm: str, question: str, repo: Path, settings_path: Path, mcp_path: Path,
             model: str, effort: str, transcript: Path, timeout: int,
             permission_mode: str) -> RunMetrics | None:
    """Run one arm once; capture the stream-json transcript; return parsed metrics (None on failure)."""
    cmd = _arm_command(arm, question, settings_path, mcp_path, model, effort, permission_mode)
    try:
        # Close stdin — headless claude otherwise waits ~3s for piped input before proceeding.
        proc = subprocess.run(cmd, cwd=repo, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        print("  ! `claude` not on PATH — install Claude Code or adjust the harness.", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print(f"  ! timed out after {timeout}s", file=sys.stderr)
        return None
    transcript.write_text(proc.stdout, encoding="utf-8")
    if not proc.stdout.strip():
        print(f"  ! empty transcript (claude exited {proc.returncode}): {proc.stderr[:200]}", file=sys.stderr)
        return None
    return parse_file(transcript)


def _isolate(repo: Path):
    """Move aside ambient yigraf affordances during a run so the arms differ in *only* the hooks.

    Two channels would otherwise leak the governance affordance into *both* arms and confound the A/B:

    - ``.claude/settings{,.local}.json`` — ``--settings`` *merges* over these, so a committed ``hooks``
      block could wire the hook into the WITHOUT arm too.
    - ``.claude/skills/`` — a project Skill (yigraf's own ``SKILL.md`` is the canonical case) tells the
      agent to run ``yigraf context``/``link`` *regardless* of the hooks. The enforceable judge scores
      that as a verification action, so a Skill present in the WITHOUT arm makes it "re-verify" through
      a channel that isn't the hook — and the hook delta vanishes. The Skill must be absent from **both**
      arms for any re-verification in the WITH arm to be attributable to the hook. (The live run that
      first found this: both arms ran ``yigraf context`` straight from the Skill → confounded null.)

    Returns a restore() callable; use in try/finally.
    """
    moved: list[tuple[Path, Path]] = []
    for rel in (".claude/settings.json", ".claude/settings.local.json", ".claude/skills"):
        p = repo / rel
        if p.exists():
            bak = p.with_name(p.name + ".eval-bak")  # works for files and the skills/ dir alike
            shutil.move(str(p), str(bak))
            moved.append((p, bak))

    def restore() -> None:
        for orig, bak in moved:
            shutil.move(str(bak), str(orig))

    return restore


def _fmt(label: str, w: dict, wo: dict) -> str:
    def delta(field: str, lower_better: bool = True) -> str:
        a, b = w.get(field, 0), wo.get(field, 0)
        if not b:
            return f"{a} vs {b}"
        pct = (a - b) / b * 100
        arrow = "▼" if (pct < 0) == lower_better else "▲"
        return f"{a:g} vs {b:g} ({arrow}{abs(pct):.0f}%)"

    return (f"  {label:<14} with vs without\n"
            f"    tool calls : {delta('tool_calls')}\n"
            f"    Read       : {delta('reads')}\n"
            f"    Grep       : {delta('greps')}\n"
            f"    time (s)   : {delta('duration_ms')}\n"
            f"    tokens     : {delta('input_tokens')}  (input; +output {delta('output_tokens')})")


def _load_cases(args) -> list[dict]:
    """Case dicts from --question or a --cases YAML. Keeps both kinds: structural (legibility A/B) and
    enforceable (the drift-reverify judge). Each: {id, question, kind, setup?, teardown?}."""
    if args.question:
        return [{"id": "q1", "question": args.question, "kind": "structural"}]
    import yaml  # pyyaml is a dev dep already used by config.yaml

    cases = yaml.safe_load(Path(args.cases).read_text(encoding="utf-8"))
    return [c for c in cases.get("cases", []) if c.get("question")]


def _shell(cmd: str | None, repo: Path, label: str) -> None:
    """Run a case's setup/teardown shell step in the repo (enforceable cases introduce/restore drift)."""
    if not cmd:
        return
    print(f"    [{label}] {cmd}", flush=True)
    subprocess.run(cmd, cwd=repo, shell=True, stdin=subprocess.DEVNULL)


def _snapshot(paths: list[str], repo: Path, snap_dir: Path):
    """Capture the working-tree state of ``paths`` (files or dirs); return a restore() that puts them back.

    The enforceable case mutates more than the edited file: when the WITH arm *enforces* it re-anchors
    the link (``yigraf link``/``remember``), which writes to the ``yigraf/`` artifacts. ``git checkout``
    of just the source file leaves those re-anchored — so the symbol no longer drifts and every later run
    falsely reads as "edited blind" (the run-0-poisons-runs-1..N bug). Snapshotting the whole declared
    set and restoring it after each run keeps runs independent; restoring ``yigraf/`` also resets the
    telemetry sidecar. Working-tree copy (not ``git checkout``) so unrelated uncommitted WIP is preserved.
    """
    snap_dir.mkdir(parents=True, exist_ok=True)
    saved: list[tuple[Path, Path, bool]] = []
    for i, rel in enumerate(paths):
        src = repo / rel
        if not src.exists():
            continue
        dst, is_dir = snap_dir / f"{i}_{Path(rel).name}", src.is_dir()
        shutil.copytree(src, dst) if is_dir else shutil.copy2(src, dst)
        saved.append((src, dst, is_dir))

    def restore() -> None:
        for src, dst, is_dir in saved:
            if is_dir:
                if src.exists():
                    shutil.rmtree(src)
                shutil.copytree(dst, src)
            else:
                shutil.copy2(dst, src)

    return restore


def _report_enforceable(arm_transcripts: dict[str, list[Path]]) -> None:
    """Judge **every** paired run (with-i vs without-i) and report the enforcement RATE — not just run-0.

    Each run is an independent A/B, so ``--runs N`` actually buys N verdicts here. The rate (e.g. ``4/4``)
    is the robust signal the README asks for; judging only run-0 would leave the enforceable verdict at
    n=1 no matter how many runs were paid for (the bug this replaces). Pairs by index; arms are
    independent, so any pairing is equivalent.
    """
    withs, withouts = arm_transcripts.get("with", []), arm_transcripts.get("without", [])
    n = min(len(withs), len(withouts))
    if n == 0:
        print("  ENFORCED: n/a — a run failed in one or both arms (no paired transcripts to judge).")
        return
    verdicts = [judge.verdict(judge.score_transcript(withs[i]), judge.score_transcript(withouts[i]))
                for i in range(n)]
    enforced = sum(1 for v in verdicts if v["enforced"])
    print(f"  ENFORCED: {enforced}/{n} run(s)")
    for i, v in enumerate(verdicts):
        print(f"    run {i}: {v['enforced']} — {v['summary']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", type=Path, default=Path("."), help="Target repo (must have a yigraf/ workspace).")
    ap.add_argument("--question", help="A single question to A/B (overrides --cases).")
    ap.add_argument("--cases", type=Path, default=Path(__file__).parent / "cases.yaml")
    ap.add_argument("--runs", type=int, default=3, help="Runs per arm (≥2; variance is large).")
    ap.add_argument("--model", default="sonnet", help="Floor model — keep it Sonnet (see README).")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--hook-cmd", default="uv run yigraf", help="Launcher for the yigraf hooks.")
    ap.add_argument("--timeout", type=int, default=600, help="Per-run timeout (seconds).")
    ap.add_argument("--permission-mode", default="bypassPermissions",
                    help="Permission mode for the headless agent. Default bypassPermissions: edits must "
                         "land unattended for the enforceable case to drift the symbol (git-reversible "
                         "sandbox; applied identically to both arms). Use acceptEdits to restrict to "
                         "file edits only.")
    ap.add_argument("--isolate", action="store_true",
                    help="Move aside the repo's ambient yigraf affordances (.claude/settings*.json AND "
                         ".claude/skills/) for the run, so the arms differ in only the hooks. Required "
                         "for the enforceable case on a yigraf-skilled repo (recommended otherwise).")
    ap.add_argument("--out", type=Path, default=None, help="Transcript dir (default: scripts/eval/runs/<ts>).")
    args = ap.parse_args()

    repo = args.repo.resolve()
    out = args.out or (Path(__file__).parent / "runs" / time.strftime("%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=True)

    with_settings = out / "with-settings.json"
    without_settings = out / "without-settings.json"
    empty_mcp = out / "empty-mcp.json"
    with_settings.write_text(json.dumps(_with_settings(args.hook_cmd), indent=2))
    without_settings.write_text(json.dumps({"hooks": {}}, indent=2))
    empty_mcp.write_text(json.dumps({"mcpServers": {}}))

    cases = _load_cases(args)
    print(f"A/B over {len(cases)} case(s) × {args.runs} run(s)/arm · model={args.model} · repo={repo}\n")

    restore = _isolate(repo) if args.isolate else (lambda: None)
    try:
        for case in cases:
            label, question, kind = case["id"], case["question"], case.get("kind", "structural")
            print(f"▶ {label} [{kind}]: {question}")
            # Snapshot once, pristine, and restore after EVERY run so each run starts un-drifted. The
            # agent mutates the source file AND (when it enforces) the yigraf/ artifacts; a case declares
            # what to restore via `restore_paths`. Falls back to the shell `teardown` if none is given.
            snap_restore = None
            if kind == "enforceable" and case.get("restore_paths"):
                snap_restore = _snapshot(case["restore_paths"], repo, out / f"_snap_{label}")
            arm_summary: dict[str, dict] = {}
            arm_transcripts: dict[str, list[Path]] = {}  # arm → its successful run transcripts (for the judge)
            for arm in ARMS:
                settings = with_settings if arm == "with" else without_settings
                runs: list[RunMetrics] = []
                transcripts: list[Path] = []
                for i in range(args.runs):
                    t = out / f"{label}__{arm}__{i}.jsonl"
                    # Enforceable cases introduce drift before each agent run, and restore after.
                    if kind == "enforceable":
                        _shell(case.get("setup"), repo, "setup")
                    print(f"    {arm} run {i + 1}/{args.runs} …", flush=True)
                    m = _run_one(arm, question, repo, settings, empty_mcp,
                                 args.model, args.effort, t, args.timeout, args.permission_mode)
                    if snap_restore is not None:
                        print("    [restore] working-tree snapshot", flush=True)
                        snap_restore()
                    elif kind == "enforceable":
                        _shell(case.get("teardown"), repo, "teardown")
                    if m is not None:
                        runs.append(m)
                        transcripts.append(t)
                arm_summary[arm] = summarize(runs)
                arm_transcripts[arm] = transcripts

            if kind == "enforceable":
                _report_enforceable(arm_transcripts)
            elif arm_summary["with"] and arm_summary["without"]:
                print(_fmt(label, arm_summary["with"], arm_summary["without"]))
            print()
    finally:
        restore()

    print(f"transcripts + per-arm settings in {out}")


if __name__ == "__main__":
    main()
