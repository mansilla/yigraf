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


def test_relative_imports_are_recorded_with_their_dots():
    # #16: relative imports keep their leading dots so they resolve against the importer's package later.
    src = b"from .b import g\nfrom ..c import h\nfrom . import d, e\n"
    proj = extract_file("pkg/a.py", src, Parser(_PY_LANGUAGE))
    assert set(proj.nodes["file:pkg/a.py"]["imports"]) == {".b", "..c", ".d", ".e"}


def test_unbound_base_records_a_same_file_inheritance_request():
    proj = _project()  # SAMPLE has `class C(Base)` and Base is not imported
    assert proj.nodes["file:pkg/m.py"]["inherits"] == [["sym:pkg/m.py#C", "", "Base"]]


def test_imported_base_records_its_module_spec():
    src = b"from .base import Base\n\n\nclass C(Base):\n    pass\n"
    proj = extract_file("pkg/a.py", src, Parser(_PY_LANGUAGE))
    assert proj.nodes["file:pkg/a.py"]["inherits"] == [["sym:pkg/a.py#C", ".base", "Base"]]


def test_aliased_imported_base_resolves_to_its_original_name():
    src = b"from .base import Base as B\n\n\nclass C(B):\n    pass\n"
    proj = extract_file("pkg/a.py", src, Parser(_PY_LANGUAGE))
    assert proj.nodes["file:pkg/a.py"]["inherits"] == [["sym:pkg/a.py#C", ".base", "Base"]]


def test_dotted_and_keyword_bases_are_skipped():
    # `abc.ABC` is dotted, `metaclass=` is a keyword arg — neither is a simple-name base, so nothing recorded.
    src = b"import abc\n\n\nclass C(abc.ABC, metaclass=abc.ABCMeta):\n    pass\n"
    proj = extract_file("pkg/a.py", src, Parser(_PY_LANGUAGE))
    assert "inherits" not in proj.nodes["file:pkg/a.py"]


def test_path_is_casefolded_but_symbol_name_is_preserved():
    proj = extract_file("Pkg/Mod.py", b"class Foo:\n    pass\n", Parser(_PY_LANGUAGE))
    assert "file:pkg/mod.py" in proj.nodes
    assert "sym:pkg/mod.py#Foo" in proj.nodes  # class name keeps its case
