"""The astnorm-v1 drift-anchor rule (docs/m1-notes.md §4), exercised through real extraction."""
from tree_sitter import Parser

from yigraf.astnorm import ANCHOR_ALGO, _canon_quote
from yigraf.extract import _PY_LANGUAGE, extract_file

BASE = '''"""module doc."""
import os


def foo(a):
    """fn doc."""
    x = 'hi'
    # a comment
    return a + 1


class C(Base):
    attr = 1

    def m(self):
        return foo(2)
'''


def _hashes(source: str) -> dict[str, str]:
    proj = extract_file("m.py", source.encode(), Parser(_PY_LANGUAGE))
    return {nid: attrs["content_hash"] for nid, attrs in proj.nodes.items() if "content_hash" in attrs}


def _changed(before: dict[str, str], after: dict[str, str]) -> set[str]:
    keys = set(before) | set(after)
    return {k for k in keys if before.get(k) != after.get(k)}


def test_anchor_algo_is_versioned():
    assert ANCHOR_ALGO == "astnorm-v1"


def test_comment_only_edit_changes_no_hash():
    edited = BASE.replace("return a + 1", "return a + 1  # new\n    # more")
    assert _changed(_hashes(BASE), _hashes(edited)) == set()


def test_docstring_edit_changes_no_hash():
    edited = BASE.replace('"""fn doc."""', '"""a wholly rewritten docstring."""')
    assert _changed(_hashes(BASE), _hashes(edited)) == set()


def test_quote_style_change_is_not_drift():
    edited = BASE.replace("x = 'hi'", 'x = "hi"')
    assert _changed(_hashes(BASE), _hashes(edited)) == set()


def test_body_change_flips_exactly_that_symbol():
    edited = BASE.replace("return a + 1", "return a + 2")
    assert _changed(_hashes(BASE), _hashes(edited)) == {"sym:m.py#foo"}


def test_method_body_change_does_not_flip_its_class_or_module():
    edited = BASE.replace("return foo(2)", "return foo(3)")
    assert _changed(_hashes(BASE), _hashes(edited)) == {"sym:m.py#C.m"}


def test_adding_a_member_flips_the_class_but_not_the_module():
    edited = BASE.replace(
        "    def m(self):",
        "    def n(self):\n        return 0\n\n    def m(self):",
    )
    changed = _changed(_hashes(BASE), _hashes(edited))
    assert changed == {"sym:m.py#C", "sym:m.py#C.n"}
    # the module/file see only the class's *name* (a marker), so they don't flip
    assert "module:m.py" not in changed and "file:m.py" not in changed


def test_decorator_change_flips_the_decorated_symbol():
    base = "@a\ndef f():\n    return 1\n"
    edited = "@b\ndef f():\n    return 1\n"
    assert _changed(_hashes(base), _hashes(edited)) == {"sym:m.py#f"}


def test_canon_quote_normalizes_prefix_case_and_quote_char_keeping_count():
    assert _canon_quote("'") == '"'
    assert _canon_quote("'''") == '"""'
    assert _canon_quote("R'''") == 'r"""'
    assert _canon_quote('F"') == 'f"'
