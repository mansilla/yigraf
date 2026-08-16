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
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_run import RunMetrics, parse_file, summarize  # noqa: E402
import judge  # noqa: E402

#: The three arms. Two arms could not separate two different claims that were being conflated:
#:   * ``with``    — hooks wired + every yigraf instruction file present (the full install).
#:   * ``ambient`` — instruction files present, hooks OFF. Baseline for **Q1: does the HOOK change
#:                   behaviour?** (``with`` vs ``ambient`` isolates event-scoped push specifically.)
#:   * ``off``     — hooks OFF *and* AGENTS.md / CLAUDE.md / .claude/skills moved aside, so the agent has
#:                   no yigraf affordance at all. Baseline for **Q2: does INSTALLING yigraf change
#:                   behaviour?** (``with`` vs ``off``.)
#: ``off`` deliberately KEEPS the ``yigraf/`` workspace on disk: the knowledge (intents, decisions) is
#: still there as plain markdown the agent may grep/Read. Removing it would make the question
#: unanswerable and turn the comparison into a trivial win; the honest question is whether yigraf's
#: retrieval beats grepping the same facts, not whether facts beat no facts.
ARMS = ("with", "ambient", "off")


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


def _pull_shim(out: Path, hook_cmd: str) -> Path:
    """Write a ``yigraf`` shim and return its dir, to be PREPENDED to the agent's PATH.

    ``AGENTS.md`` tells the agent to run bare ``yigraf context``, so the *pull* path resolves to
    whatever ``yigraf`` happens to be on the developer's PATH — which is **not** the build ``--hook-cmd``
    points the *push* path at. On this machine that was a released 1.3.0 uv tool vs the working tree's
    1.3.1: ``ambient`` would have been pulling from one version of yigraf while ``with`` pushed from
    another, and the Q1 delta would have quietly absorbed the diff between them. The shim pins every
    arm's pull to the same interpreter as the hook, so the arms differ in the ONE thing they claim to.
    """
    d = out / "bin"
    d.mkdir(parents=True, exist_ok=True)
    shim = d / "yigraf"
    shim.write_text(f'#!/bin/sh\nexec {hook_cmd} "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    return d


def _run_one(arm: str, question: str, repo: Path, settings_path: Path, mcp_path: Path,
             model: str, effort: str, transcript: Path, timeout: int,
             permission_mode: str, shim_dir: Path | None = None) -> RunMetrics | None:
    """Run one arm once; capture the stream-json transcript; return parsed metrics (None on failure)."""
    cmd = _arm_command(arm, question, settings_path, mcp_path, model, effort, permission_mode)
    env = dict(os.environ)
    if shim_dir is not None:
        # Every arm, not just `ambient`: `off` has no instruction to use yigraf, but if it discovers the
        # CLI on its own it must still hit the same build, or the baseline stops being comparable.
        env["PATH"] = f"{shim_dir}{os.pathsep}{env.get('PATH', '')}"
    try:
        # Close stdin — headless claude otherwise waits ~3s for piped input before proceeding.
        proc = subprocess.run(cmd, cwd=repo, stdin=subprocess.DEVNULL, env=env,
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


#: Always moved aside for EVERY arm: ``--settings`` *merges* over these, so a committed ``hooks`` block
#: would wire the hook into the hookless arms too and erase the very difference being measured.
_SETTINGS_CHANNELS = (".claude/settings.json", ".claude/settings.local.json")

#: Moved aside for the ``off`` arm only — the channels that tell an agent to pull ``yigraf context``
#: *without any hook*. ``.claude/skills/`` was already known (yigraf's own SKILL.md says "run context
#: first"). The instruction files were NOT, and they are the bigger leak: on a live run the hookless arm
#: said "per the project's workflow" and ran ``yigraf context`` straight from AGENTS.md / CLAUDE.md, so
#: both arms converged and the measured delta was ~0 **by construction** on any yigraf-governed repo.
_AFFORDANCE_CHANNELS = (".claude/skills", "AGENTS.md", "CLAUDE.md")


def _isolate(repo: Path, channels: tuple[str, ...]):
    """Move ``channels`` aside for the duration of a run; returns a restore() for try/finally.

    Isolation is **per-arm**, not global: ``with``/``ambient`` hide only the settings, while ``off``
    also hides the instruction files and the Skill. A global isolation cannot express that difference —
    which is why the two-arm version could only ever measure one of the two claims, and silently
    measured neither on a repo whose own docs preach the tool.
    """
    moved: list[tuple[Path, Path]] = []
    for rel in channels:
        p = repo / rel
        if p.exists():
            bak = p.with_name(p.name + ".eval-bak")  # works for files and the skills/ dir alike
            shutil.move(str(p), str(bak))
            moved.append((p, bak))

    def restore() -> None:
        for orig, bak in moved:
            shutil.move(str(bak), str(orig))

    return restore


def _arm_channels(arm: str, isolate: bool) -> tuple[str, ...]:
    """Which channels this arm hides. ``off`` hides the affordance too; the rest hide only settings."""
    if not isolate:
        return ()
    return _SETTINGS_CHANNELS + (_AFFORDANCE_CHANNELS if arm == "off" else ())


def _fmt(label: str, w: dict, base: dict, baseline: str, question: str) -> str:
    """One comparison block: the ``with`` arm against one baseline, named by the claim it tests."""
    def delta(field: str, lower_better: bool = True) -> str:
        a, b = w.get(field, 0), base.get(field, 0)
        if not b:
            return f"{a} vs {b}"
        pct = (a - b) / b * 100
        arrow = "▼" if (pct < 0) == lower_better else "▲"
        return f"{a:g} vs {b:g} ({arrow}{abs(pct):.0f}%)"

    return (f"  {label:<14} with vs {baseline}   — {question}\n"
            f"    tool calls : {delta('tool_calls')}\n"
            f"    Read       : {delta('reads')}\n"
            f"    Grep       : {delta('greps')}\n"
            f"    time (ms)  : {delta('duration_ms')}\n"
            f"    tokens     : {delta('input_tokens')}  (input; +output {delta('output_tokens')})")


def _report_structural(label: str, arm_summary: dict[str, dict]) -> None:
    """Report both claims the three arms separate: the hook's effect, and the whole install's effect."""
    for baseline, question in (("ambient", "Q1: does the HOOK change behaviour?"),
                               ("off", "Q2: does INSTALLING yigraf change behaviour?")):
        if arm_summary.get("with") and arm_summary.get(baseline):
            print(_fmt(label, arm_summary["with"], arm_summary[baseline], baseline, question))


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
    Judged against BOTH baselines, because "enforced" means something different against each: vs
    ``ambient`` it is the hook's own effect (the moat), vs ``off`` it is the whole install's effect.
    """
    withs = arm_transcripts.get("with", [])
    for baseline in ("ambient", "off"):
        others = arm_transcripts.get(baseline, [])
        n = min(len(withs), len(others))
        if n == 0:
            print(f"  ENFORCED vs {baseline}: n/a — a run failed in one or both arms.")
            continue
        verdicts = [judge.verdict(judge.score_transcript(withs[i]), judge.score_transcript(others[i]))
                    for i in range(n)]
        enforced = sum(1 for v in verdicts if v["enforced"])
        print(f"  ENFORCED vs {baseline}: {enforced}/{n} run(s)")
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
                    help="Isolate the arms PER-ARM: every arm hides .claude/settings*.json (which would "
                         "otherwise merge committed hooks into the hookless arms), and the `off` arm "
                         "additionally hides .claude/skills/, AGENTS.md and CLAUDE.md so it has no "
                         "yigraf affordance at all. Effectively required — without it every arm can "
                         "read 'run yigraf context' from the repo's own docs and all deltas read ~0.")
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
    shim_dir = _pull_shim(out, args.hook_cmd)

    cases = _load_cases(args)
    print(f"A/B over {len(cases)} case(s) × {args.runs} run(s)/arm · model={args.model} · repo={repo}\n")

    if not args.isolate:
        print("  ! --isolate is OFF: committed hooks/skills/AGENTS.md leak into the hookless arms and\n"
              "    the deltas will read ~0 regardless of what yigraf does. Use --isolate.\n")
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
                # Per-arm isolation: `off` also hides AGENTS.md/CLAUDE.md/skills, so it is the only arm
                # with no yigraf affordance at all. Restored before the next arm starts.
                arm_restore = _isolate(repo, _arm_channels(arm, args.isolate))
                try:
                    for i in range(args.runs):
                        t = out / f"{label}__{arm}__{i}.jsonl"
                        # Enforceable cases introduce drift before each agent run, and restore after.
                        if kind == "enforceable":
                            _shell(case.get("setup"), repo, "setup")
                        print(f"    {arm} run {i + 1}/{args.runs} …", flush=True)
                        m = _run_one(arm, question, repo, settings, empty_mcp,
                                     args.model, args.effort, t, args.timeout, args.permission_mode,
                                     shim_dir)
                        if snap_restore is not None:
                            print("    [restore] working-tree snapshot", flush=True)
                            snap_restore()
                        elif kind == "enforceable":
                            _shell(case.get("teardown"), repo, "teardown")
                        if m is not None:
                            runs.append(m)
                            transcripts.append(t)
                finally:
                    arm_restore()
                arm_summary[arm] = summarize(runs)
                arm_transcripts[arm] = transcripts

            if kind == "enforceable":
                _report_enforceable(arm_transcripts)
            else:
                _report_structural(label, arm_summary)
            print()
    finally:
        # Safety net: per-arm isolation already restores in its own finally, but a hard crash (or a
        # SIGKILL between the move and the restore) would otherwise leave the repo's real
        # settings/skills/AGENTS.md parked at `.eval-bak` — a silently broken working tree.
        for rel in _SETTINGS_CHANNELS + _AFFORDANCE_CHANNELS:
            bak = (repo / rel).with_name(Path(rel).name + ".eval-bak")
            if bak.exists() and not (repo / rel).exists():
                print(f"  [recover] restoring stray {rel}", file=sys.stderr)
                shutil.move(str(bak), str(repo / rel))

    print(f"transcripts + per-arm settings in {out}")


if __name__ == "__main__":
    main()
