"""Shared test fixtures.

The embedding backend (M8) is an *optional* enhancement — retrieval must work identically without it
(the lexical fallback = v0). To keep the suite deterministic and fast regardless of whether the
``[embeddings]`` extra is installed, we disable the embedder by default; tests that specifically
exercise embeddings opt back in with ``@pytest.mark.embeddings``.
"""
import pytest

from yigraf import embeddings


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "embeddings: test exercises the real embedding backend (needs the [embeddings] extra)."
    )


@pytest.fixture(autouse=True)
def _disable_embeddings(request, monkeypatch):
    """Force the lexical fallback unless a test is marked ``embeddings`` (then leave the real backend)."""
    if request.node.get_closest_marker("embeddings"):
        return
    monkeypatch.setattr(embeddings, "get_embedder", lambda config: None)
