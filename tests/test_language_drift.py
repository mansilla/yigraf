"""Per-language drift enforcement — the moat, verified uniformly (plan:language-drift-coverage).

Structure breadth (symbols/calls/imports/inheritance) is covered in test_tags.py / test_languages.py.
This pins the thing that makes yigraf *governance* and not just an index: does the astnorm drift anchor
fire correctly on every extractor-backed language? For each language the same round-trip:

  1. **body edit → soft drift** — the symbol's content_hash changes (and the module/file do NOT: bodies
     are masked in the container hash).
  2. **comment-only edit → no drift** — the language's comment node types are in the astnorm knob.
  3. **rename → re-anchor** — the body hash is preserved on the new id (astnorm excludes the symbol's own
     name), so M3 re-anchors a rename instead of reporting a deletion.

Plus the Ruby/PHP quote-handling decision (#3) and the tested capability matrix (#2).
"""
import pytest

from yigraf.extract import extract_file


def _hashes(relpath: str, src: str) -> dict[str, str]:
    return {n: a["content_hash"] for n, a in extract_file(relpath, src.encode()).nodes.items()}


def _changed(before: dict, after: dict) -> set[str]:
    return {k for k in set(before) | set(after) if before.get(k) != after.get(k)}


# lang, path, src, sym_qualname, (body_old,body_new), (comment_old,comment_new), (rename_old,rename_new), new_qualname
_DRIFT_CASES = [
    ("rust", "m.rs", "fn helper() -> i32 {\n    1\n}\n", "helper",
     ("    1\n", "    2\n"), ("    1\n", "    1 // c\n"), ("fn helper(", "fn renamed("), "renamed"),
    ("java", "G.java", 'class G {\n    String helper() {\n        return "hi";\n    }\n}\n', "G.helper",
     ('return "hi"', 'return "bye"'), ('return "hi";', 'return "hi"; // c'),
     ("String helper()", "String renamed()"), "G.renamed"),
    ("ruby", "c.rb", "class C\n  def helper\n    1\n  end\nend\n", "C.helper",
     ("    1\n", "    2\n"), ("    1\n", "    1 # c\n"), ("def helper", "def renamed"), "C.renamed"),
    ("php", "a.php", "<?php\nfunction helper() {\n    return 1;\n}\n", "helper",
     ("return 1;", "return 2;"), ("return 1;", "return 1; // c"),
     ("function helper(", "function renamed("), "renamed"),
    ("kotlin", "m.kt", "fun helper(): Int {\n    return 1\n}\n", "helper",
     ("return 1", "return 2"), ("return 1", "return 1 // c"), ("fun helper(", "fun renamed("), "renamed"),
    ("cpp", "m.cpp", "int helper() {\n    return 1;\n}\n", "helper",
     ("return 1;", "return 2;"), ("return 1;", "return 1; // c"), ("int helper(", "int renamed("), "renamed"),
    ("c", "m.c", "int helper() {\n    return 1;\n}\n", "helper",
     ("return 1;", "return 2;"), ("return 1;", "return 1; // c"), ("int helper(", "int renamed("), "renamed"),
    ("csharp", "C.cs", 'class G {\n    string helper() {\n        return "x";\n    }\n}\n', "G.helper",
     ('return "x"', 'return "y"'), ('return "x";', 'return "x"; // c'),
     ("string helper()", "string renamed()"), "G.renamed"),
    ("scala", "G.scala", 'class G {\n  def helper(): String = "x"\n}\n', "G.helper",
     ('= "x"', '= "y"'), ('= "x"', '= "x" // c'), ("def helper(", "def renamed("), "G.renamed"),
    ("swift", "G.swift", 'class G {\n    func helper() -> String {\n        return "x"\n    }\n}\n', "G.helper",
     ('return "x"', 'return "y"'), ('return "x"', 'return "x" // c'), ("func helper(", "func renamed("), "G.renamed"),
    ("bash", "s.sh", "helper() {\n  echo hi\n}\n", "helper",
     ("echo hi", "echo bye"), ("echo hi", "echo hi # c"), ("helper()", "renamed()"), "renamed"),
]


@pytest.mark.parametrize("lang,path,src,sym,body,comment,rename,new_sym", _DRIFT_CASES,
                         ids=[c[0] for c in _DRIFT_CASES])
def test_drift_round_trip_per_language(lang, path, src, sym, body, comment, rename, new_sym):
    pid = path.casefold()
    sym_id, new_id = f"sym:{pid}#{sym}", f"sym:{pid}#{new_sym}"
    base = _hashes(path, src)
    assert sym_id in base, f"{lang}: fixture didn't yield {sym_id} (got {sorted(base)})"

    # 1. body edit → exactly that symbol drifts; the module/file do not (their hash masks bodies).
    changed = _changed(base, _hashes(path, src.replace(*body)))
    assert sym_id in changed, f"{lang}: body edit did not drift {sym_id}"
    assert f"module:{pid}" not in changed and f"file:{pid}" not in changed, f"{lang}: body edit leaked to container"

    # 2. comment-only edit → no drift at all (comment_types knob covers this language).
    assert _changed(base, _hashes(path, src.replace(*comment))) == set(), f"{lang}: comment edit drifted"

    # 3. rename → body hash preserved on the new id (own-name excluded → M3 re-anchors).
    after = _hashes(path, src.replace(*rename))
    assert after.get(new_id) == base[sym_id], f"{lang}: rename did not re-anchor"


# --- #3: Ruby/PHP astnorm quote handling — DECISION: keep semantically distinct (do NOT normalize) ---
# In both languages '...' (literal) and "..." (interpolating) are NOT interchangeable, so a quote flip
# is a real semantic change and MUST drift — unlike JS/TS/Python where Prettier/Black flip quote style
# cosmetically (those DO normalize; see test_languages.py::test_ts_quote_style_change_is_not_drift).

def test_ruby_quote_flip_is_drift_not_cosmetic():
    a = _hashes("q.rb", "def f\n  'x'\nend\n")
    b = _hashes("q.rb", 'def f\n  "x"\nend\n')
    assert a["sym:q.rb#f"] != b["sym:q.rb#f"]


def test_php_quote_flip_is_drift_not_cosmetic():
    a = _hashes("q.php", "<?php\nfunction f() { return 'x'; }\n")
    b = _hashes("q.php", '<?php\nfunction f() { return "x"; }\n')
    assert a["sym:q.php#f"] != b["sym:q.php#f"]


# --- #2: tested capability matrix — the truth behind "16 languages" (mirrors docs/language-support.md) ---
# Every row is asserted below. `symbols` + `drift` are universal (drift verified per-language above /
# in test_languages.py); this pins the two capabilities that VARY by module/type system: imports
# (does the language map to files?) and inheritance (does it have a type hierarchy?). Both directions
# are checked — a False cell must really be absent (no false breadth claim).
#   lang, ext, fixture, has_imports, has_inheritance
_MATRIX = [
    ("python",     ".py",    "import os\nclass C(Base):\n    def m(self):\n        return 1\n", True,  True),
    ("go",         ".go",    "package m\nimport \"fmt\"\ntype Base struct{}\ntype D struct {\n\tBase\n}\n", True, True),
    ("typescript", ".ts",    "import { x } from \"./u\";\nclass C extends Base {}\n", True,  True),
    ("rust",       ".rs",    "mod util;\nstruct S;\nimpl T for S {}\n",            True,  True),
    ("java",       ".java",  "import a.B;\nclass C extends Base {}\n",             True,  True),
    ("cpp",        ".cpp",   "#include \"u.h\"\nclass C : public Base {};\n",      True,  True),
    ("ruby",       ".rb",    "require_relative \"u\"\nclass C < Base\nend\n",      True,  True),
    ("php",        ".php",   "<?php\nrequire_once \"u.php\";\nclass C extends Base {}\n", True, True),
    ("kotlin",     ".kt",    "import a.B\nclass C : Base()\n",                      True,  True),
    ("scala",      ".scala", "import a.B\nclass C extends Base\n",                 True,  True),
    ("csharp",     ".cs",    "using System;\nclass C : Base {}\n",                 False, True),   # using → namespace, not file
    ("swift",      ".swift", "import Foundation\nclass C: Base {}\n",              False, True),   # import → module, not file
    ("c",          ".c",     "#include \"u.h\"\nint helper() { return 1; }\n",     True,  False),  # no type hierarchy
    ("bash",       ".sh",    "helper() {\n  echo hi\n}\n",                         False, False),
    ("sql",        ".sql",   "CREATE TABLE users (id INT);\n",                     False, False),
]


@pytest.mark.parametrize("lang,ext,src,has_imports,has_inheritance", _MATRIX, ids=[m[0] for m in _MATRIX])
def test_capability_matrix(lang, ext, src, has_imports, has_inheritance):
    pid = f"x{ext}".casefold()
    proj = extract_file(f"x{ext}", src.encode())
    fnode = proj.nodes[f"file:{pid}"]
    assert any(n.startswith("sym:") for n in proj.nodes), f"{lang}: produced no symbols"
    assert bool(fnode.get("imports")) == has_imports, f"{lang}: imports={fnode.get('imports')!r}"
    assert bool(fnode.get("inherits")) == has_inheritance, f"{lang}: inherits={fnode.get('inherits')!r}"
