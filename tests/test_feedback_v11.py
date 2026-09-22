"""The field's eighth report: the two one-line fixes, each pinned by the failure it closes.

Both are regressions of the same kind — a guard that cannot fail, so the defect it guards was invisible.
Each test below is written to fail on 1.14.2 and pass after the corresponding change, and each asserts
against a config or a store on DISK rather than against a dict assembled in the test, because that is
precisely the distinction the two defects hid behind.
"""
from pathlib import Path

import pytest
from typer.testing import CliRunner

from yigraf.cli import app
from yigraf.config import load_config

runner = CliRunner()


def _store(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    return tmp_path


# --- K#1 (was J#-series C.1's key): the packet budget's fallback must be reachable from a FILE ------

def test_an_upgraded_config_without_the_key_falls_back_to_the_query_budget(tmp_path):
    """A config file that predates `session_start.token_budget` must size its packet from the query budget.

    The regression this pins: a default for the key in `default_config` is never falsy, so
    `session_context`'s documented `or retrieval.query_token_budget` fallback was dead for every config a
    file can express — and a store that had raised the query budget was silently re-sized to 4000 on
    upgrade. Asserted on a file, because the merged dict is exactly what hid it.
    """
    root = _store(tmp_path)
    config_path = root / "yigraf" / "config.yaml"
    text = config_path.read_text()
    # the shape an upgraded store is in: no `token_budget`, and a query budget someone raised
    config_path.write_text(
        "\n".join(line for line in text.splitlines() if not line.startswith("  token_budget:"))
        .replace("query_token_budget: 4000", "query_token_budget: 9000")
    )
    config = load_config(config_path)
    assert config["session_start"].get("token_budget") is None, \
        "a default for this key makes the fallback below unreachable from any config FILE"
    effective = (config["session_start"].get("token_budget")
                 or config["retrieval"]["query_token_budget"])
    assert effective == 9000, "the packet is sized by a number the user's file does not contain"


def test_a_fresh_init_omits_the_key_and_still_renders_at_4000(tmp_path):
    """The counterpart: a fresh store must be unchanged by the fix, which is what makes it safe.

    The key is omitted from the template on the same ground as `preamble` — an omission inherits, so it
    cannot drift and an upgrade can reach it — and the value it inherits is `retrieval.query_token_budget`,
    4000 in a fresh config. So the packet a new store renders is the same size as before the change.
    """
    config = load_config(_store(tmp_path) / "yigraf" / "config.yaml")
    assert config["session_start"].get("token_budget") is None
    effective = (config["session_start"].get("token_budget")
                 or config["retrieval"]["query_token_budget"])
    assert effective == 4000


# --- K#2: the section offer must not fire where its own remedy is refused -------------------------

def test_no_section_offer_on_a_non_markdown_anchor(tmp_path):
    """An offer naming a `#section` of a non-markdown file hands over a `reanchor` `_anchor` refuses.

    `section_texts` gates on `is_file()` alone, so a YAML file's `#` comment lines parse as headings — the
    package's own shipped `config.yaml` yields 87. The offer is not merely noise: it writes a row into
    `section-offers.json`, and that row can never be scored accepted, because no verb will put
    `file:<non-markdown>#<slug>` on a node.
    """
    root = _store(tmp_path)
    (root / "probe.yaml").write_text(
        "# Retrieval budget and the packet\nbudget: 1\n\n# Drift detection thresholds\nsoft: 2\n"
    )
    out = runner.invoke(app, [
        "remember", "The retrieval packet budget governs the token budget of the packet we send",
        "--repo", str(root), "--type", "decision", "--why", "probe",
        "--concerns", "file:probe.yaml",
    ]).output
    assert "Captured mem:" in out
    assert "Offer" not in out, f"offered a #section of a non-markdown file:\n{out}"
    ledger = root / "yigraf" / ".local" / "section-offers.json"
    assert not ledger.exists() or "probe.yaml" not in ledger.read_text(), \
        "a candidate no margin could ever be right about was written to the offer ledger"


def test_the_offer_still_fires_on_markdown(tmp_path):
    """The gate must not cost the case the offer exists for."""
    root = _store(tmp_path)
    (root / "notes.md").write_text(
        "# Notes\n\n## Retrieval budget\n\nThe packet budget is separate.\n\n"
        "## Drift detection thresholds\n\nSoft drift is a body change.\n"
    )
    out = runner.invoke(app, [
        "remember", "Drift detection thresholds are set per anchor kind",
        "--repo", str(root), "--type", "learned-fact", "--why", "probe",
        "--concerns", "file:notes.md",
    ]).output
    assert "Offer" in out, f"the markdown case stopped being offered:\n{out}"
