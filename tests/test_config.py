import yaml

from yigraf.config import (
    DEFAULT_CONFIG,
    DEFAULT_CONFIG_YAML,
    _deep_merge,
    default_config,
    load_config,
)


def test_default_config_yaml_matches_defaults():
    # The friendly, commented file and the in-code defaults must never drift apart. The file is
    # allowed to OMIT a key (an omission inherits the default and so cannot drift — `preamble` is
    # deliberately absent so no repo carries a copy that upgrades can't reach), but it must never
    # state a different value for one.
    assert _deep_merge(DEFAULT_CONFIG, yaml.safe_load(DEFAULT_CONFIG_YAML)) == DEFAULT_CONFIG


def test_load_config_missing_file_returns_defaults(tmp_path):
    assert load_config(tmp_path / "nope.yaml") == default_config()


def test_load_config_merges_over_defaults(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("maturity_k: 7\nretrieval:\n  seeds: 9\n")
    cfg = load_config(p)
    assert cfg["maturity_k"] == 7              # top-level override
    assert cfg["retrieval"]["seeds"] == 9      # nested override
    assert cfg["retrieval"]["max_hops"] == 2   # sibling default preserved
    assert cfg["languages"] == [  # untouched default
        "python", "go", "javascript", "typescript", "rust", "java", "c", "cpp",
        "ruby", "php", "c_sharp", "kotlin", "scala", "swift", "bash", "sql",
    ]
