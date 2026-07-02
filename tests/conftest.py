"""Shared test fixtures.

Semantic recall (M8) is on by default (fastembed is a core dep), but retrieval must still work
identically without it (the lexical fallback = v0). To keep the suite deterministic, fast, and
offline (no first-run model download), we disable the embedder by default; tests that specifically
exercise the real backend opt back in with ``@pytest.mark.embeddings`` and are deselected by default
(see ``addopts`` in pyproject) — run them with ``pytest -m embeddings``.
"""
import pytest

import yigraf

# The repo root holds a `yigraf/` *workspace* dir (config/memory/plans) that Python can pick up as a
# namespace package. With a healthy editable install the real regular package in `src/yigraf` wins, but
# if that install breaks (e.g. after a botched reinstall) only the namespace portion remains — and
# every test then fails during collection with a confusing `ModuleNotFoundError: yigraf.<submodule>`.
# Detect that here and fail once with the one-line fix instead of a wall of phantom failures.
if getattr(yigraf, "__file__", None) is None:  # namespace package ⇒ the workspace dir is shadowing us
    raise RuntimeError(
        "yigraf resolved to a namespace package — the repo-root `yigraf/` workspace is shadowing the "
        "installed `src/yigraf` (the editable install is broken). Fix: `rm -rf .venv && uv sync`."
    )

from yigraf import embeddings


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "embeddings: test exercises the real embedding backend (downloads a model; "
                   "deselected by default — run with `pytest -m embeddings`)."
    )


@pytest.fixture(autouse=True)
def _disable_embeddings(request, monkeypatch):
    """Force the lexical fallback unless a test is marked ``embeddings`` (then leave the real backend)."""
    if request.node.get_closest_marker("embeddings"):
        return
    monkeypatch.setattr(embeddings, "get_embedder", lambda config: None)
