"""Per-file structure extraction: nodes, ids, and contains/calls edges (docs/m1-notes.md §2)."""
from tree_sitter import Parser

from yigraf.extract import _PY_LANGUAGE, extract_file

SAMPLE = '''import os
from yigraf.config import load_config


def bar(x):
    return x


def foo(a):
    return bar(a)


class C(Base):
    attr = 1

    def helper(self):
        return 2

    def m(self):
        return self.helper()
'''


def _project(source: str = SAMPLE):
    return extract_file("pkg/m.py", source.encode(), Parser(_PY_LANGUAGE))


def _edges(proj, relation: str) -> set[tuple[str, str]]:
    return {(s, d) for s, d, a in proj.edges if a["relation"] == relation}


def test_emits_expected_node_ids_and_kinds():
    proj = _project()
    kinds = {nid: attrs["kind"] for nid, attrs in proj.nodes.items()}
    assert kinds == {
        "file:pkg/m.py": "file",
        "module:pkg/m.py": "module",
        "sym:pkg/m.py#bar": "function",
        "sym:pkg/m.py#foo": "function",
        "sym:pkg/m.py#C": "class",
        "sym:pkg/m.py#C.helper": "method",
        "sym:pkg/m.py#C.m": "method",
    }


def test_every_structure_node_carries_a_content_hash_except_the_pure_file_artifact():
    proj = _project()
    for nid, attrs in proj.nodes.items():
        assert attrs["family"] == "structure"
        assert attrs["confidence"] == "EXTRACTED"
        assert "content_hash" in attrs


def test_contains_edges_form_the_file_module_symbol_hierarchy():
    proj = _project()
    assert _edges(proj, "contains") == {
        ("file:pkg/m.py", "module:pkg/m.py"),
        ("module:pkg/m.py", "sym:pkg/m.py#bar"),
        ("module:pkg/m.py", "sym:pkg/m.py#foo"),
        ("module:pkg/m.py", "sym:pkg/m.py#C"),
        ("sym:pkg/m.py#C", "sym:pkg/m.py#C.helper"),
        ("sym:pkg/m.py#C", "sym:pkg/m.py#C.m"),
    }


def test_intra_file_calls_resolve_bare_names_and_self_methods():
    proj = _project()
    assert _edges(proj, "calls") == {
        ("sym:pkg/m.py#foo", "sym:pkg/m.py#bar"),
        ("sym:pkg/m.py#C.m", "sym:pkg/m.py#C.helper"),
    }


def test_external_calls_are_not_phantom_nodes():
    proj = extract_file("m.py", b"def f():\n    return open('x')\n", Parser(_PY_LANGUAGE))
    assert _edges(proj, "calls") == set()  # open() isn't in the file, so no edge


def test_file_node_records_sorted_imports():
    proj = _project()
    assert proj.nodes["file:pkg/m.py"]["imports"] == ["os", "yigraf.config"]


def test_path_is_casefolded_but_symbol_name_is_preserved():
    proj = extract_file("Pkg/Mod.py", b"class Foo:\n    pass\n", Parser(_PY_LANGUAGE))
    assert "file:pkg/mod.py" in proj.nodes
    assert "sym:pkg/mod.py#Foo" in proj.nodes  # class name keeps its case
