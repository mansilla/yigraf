"""The generic tags-query extractor (yigraf.languages.tags) — Rust + Java as representatives.

Covers what the tags path must get right beyond "it parses": kind mapping, containment/qualnames
derived from ancestry, intra-file call resolution from ``@reference.call``, and the astnorm drift
anchor — including the per-language comment-type fix (Rust/Java use ``line_comment``/``block_comment``,
so a comment-only edit must NOT drift).
"""
from yigraf.config import default_config
from yigraf.extract import extract_file
from yigraf.languages import available_extractors, extension_map


def _edges(proj, relation):
    return {(s, d) for s, d, a in proj.edges if a["relation"] == relation}


def _kinds(proj):
    return {nid.split("#", 1)[1]: a["kind"] for nid, a in proj.nodes.items() if nid.startswith("sym:")}


def _hashes(relpath, src):
    return {n: a["content_hash"] for n, a in extract_file(relpath, src.encode()).nodes.items()}


def _changed(before, after):
    return {k for k in set(before) | set(after) if before.get(k) != after.get(k)}


# --- Rust -----------------------------------------------------------------------------------------

RUST = '''struct Stack {
    n: i32,
}

impl Stack {
    fn push(&mut self) {
        helper();
    }
}

fn helper() -> i32 {
    1
}
'''


def _rs(src=RUST):
    return extract_file("m.rs", src.encode())


def test_rust_symbols_and_kinds():
    # struct → class, impl method → method (nested under its receiver type), free fn → function.
    assert _kinds(_rs()) == {"Stack": "class", "Stack.push": "method", "helper": "function"}


def test_rust_impl_method_nests_under_its_type():
    assert ("sym:m.rs#Stack", "sym:m.rs#Stack.push") in _edges(_rs(), "contains")


def test_rust_calls_resolve_intra_file():
    assert _edges(_rs(), "calls") == {("sym:m.rs#Stack.push", "sym:m.rs#helper")}


def test_rust_comment_edit_is_not_drift():
    # Rust comments are line_comment/block_comment — the comment_types knob must cover them.
    edited = RUST.replace("helper();", "helper(); // call the helper")
    assert _changed(_hashes("m.rs", RUST), _hashes("m.rs", edited)) == set()


def test_rust_body_change_flips_exactly_one_symbol():
    edited = RUST.replace("    1\n}", "    2\n}")
    assert _changed(_hashes("m.rs", RUST), _hashes("m.rs", edited)) == {"sym:m.rs#helper"}


def test_rust_method_body_change_does_not_flip_the_module():
    # The method nests under Stack *logically* but lives in an impl block syntactically; editing its
    # body must flip only the method, not the module (syntactic vs logical containment).
    edited = RUST.replace("helper();", "helper(); helper();")
    changed = _changed(_hashes("m.rs", RUST), _hashes("m.rs", edited))
    assert changed == {"sym:m.rs#Stack.push"}
    assert "module:m.rs" not in changed and "file:m.rs" not in changed


# --- Java -----------------------------------------------------------------------------------------

JAVA = '''class Greeter {
    String speak() {
        return helper();
    }

    String helper() {
        return "hi";
    }
}
'''


def test_java_nests_methods_under_class_and_resolves_calls():
    proj = extract_file("Greeter.java", JAVA.encode())
    assert _kinds(proj) == {
        "Greeter": "class",
        "Greeter.speak": "method",
        "Greeter.helper": "method",
    }
    assert ("sym:greeter.java#Greeter", "sym:greeter.java#Greeter.speak") in _edges(proj, "contains")
    assert _edges(proj, "calls") == {
        ("sym:greeter.java#Greeter.speak", "sym:greeter.java#Greeter.helper"),
    }


def test_java_comment_edit_is_not_drift():
    edited = JAVA.replace("return helper();", "return helper(); // delegate")
    assert _changed(_hashes("X.java", JAVA), _hashes("X.java", edited)) == set()


def test_java_rename_preserves_body_hash_for_reanchoring():
    before = _hashes("Greeter.java", JAVA)
    renamed = JAVA.replace("String helper()", "String helper2()")
    after = _hashes("Greeter.java", renamed)
    assert before["sym:greeter.java#Greeter.helper"] == after["sym:greeter.java#Greeter.helper2"]


# --- Registry -------------------------------------------------------------------------------------


def test_generic_languages_are_enabled_by_default():
    exts = extension_map(available_extractors(default_config()))
    for suffix in (".rs", ".java", ".c", ".cpp", ".rb", ".php"):
        assert suffix in exts, suffix


def test_vendored_languages_are_enabled():
    # c_sharp/kotlin/scala/swift/bash/sql ship no usable TAGS_QUERY, so yigraf vendors one for each.
    exts = extension_map(available_extractors(default_config()))
    for suffix in (".cs", ".kt", ".scala", ".swift", ".sh", ".sql"):
        assert suffix in exts, suffix


# --- Vendored-query languages (c#, kotlin, scala, swift) ------------------------------------------


def test_csharp_symbols_and_calls():
    src = (b"namespace N {\n  interface I { string Speak(); }\n"
           b"  class C : I {\n    public string Speak() { return Helper(); }\n"
           b"    string Helper() { return \"x\"; }\n  }\n}\n")
    proj = extract_file("C.cs", src)
    kinds = _kinds(proj)  # keyed by qualname (nested under the namespace)
    assert kinds["N"] == "module"
    assert kinds["N.I"] == "interface"
    assert kinds["N.C"] == "class"
    assert kinds["N.C.Speak"] == "method"
    assert ("sym:c.cs#N.C.Speak", "sym:c.cs#N.C.Helper") in _edges(proj, "calls")


def test_kotlin_class_and_methods_nest():
    src = b"class Greeter {\n    fun speak(): String { return helper() }\n    fun helper(): String = \"hi\"\n}\n"
    proj = extract_file("g.kt", src)
    assert _kinds(proj) == {
        "Greeter": "class", "Greeter.speak": "function", "Greeter.helper": "function",
    }
    assert ("sym:g.kt#Greeter", "sym:g.kt#Greeter.speak") in _edges(proj, "contains")


def test_scala_symbols_and_calls():
    src = b"class G {\n  def speak(): String = helper()\n  def helper(): String = \"hi\"\n}\n"
    proj = extract_file("G.scala", src)
    assert _kinds(proj) == {"G": "class", "G.speak": "method", "G.helper": "method"}
    assert ("sym:g.scala#G.speak", "sym:g.scala#G.helper") in _edges(proj, "calls")


def test_swift_class_protocol_and_methods():
    src = (b"protocol P { }\nclass G {\n    func speak() -> String { return helper() }\n"
           b"    func helper() -> String { return \"x\" }\n}\n")
    proj = extract_file("G.swift", src)
    kinds = _kinds(proj)  # keyed by qualname
    assert kinds["P"] == "interface"
    assert kinds["G"] == "class"
    assert kinds["G.speak"] == "function"
    assert ("sym:g.swift#G", "sym:g.swift#G.speak") in _edges(proj, "contains")


def test_kotlin_comment_edit_is_not_drift():
    base = b"fun f(): Int {\n    return 1\n}\n"
    edited = b"fun f(): Int {\n    return 1 // one\n}\n"
    h1 = {n: a["content_hash"] for n, a in extract_file("m.kt", base).nodes.items()}
    h2 = {n: a["content_hash"] for n, a in extract_file("m.kt", edited).nodes.items()}
    assert h1 == h2


def test_kotlin_calls_resolve():
    src = b'class Repo {\n    fun find(): String { return load() }\n    fun load(): String = "x"\n}\n'
    assert ("sym:r.kt#Repo.find", "sym:r.kt#Repo.load") in _edges(extract_file("r.kt", src), "calls")


def test_swift_calls_resolve():
    src = b'class V {\n    func render() -> String { return layout() }\n    func layout() -> String { return "v" }\n}\n'
    assert ("sym:v.swift#V.render", "sym:v.swift#V.layout") in _edges(extract_file("v.swift", src), "calls")


# --- Bash + SQL -----------------------------------------------------------------------------------


def test_bash_functions_and_calls():
    src = b"helper() {\n  echo hi\n}\nmain() {\n  helper\n}\n"
    proj = extract_file("s.sh", src)
    assert _kinds(proj) == {"helper": "function", "main": "function"}
    # `helper` invocation resolves to the in-file function; `echo` (external) is dropped.
    assert _edges(proj, "calls") == {("sym:s.sh#main", "sym:s.sh#helper")}


def test_sql_schema_symbols_and_drift():
    src = (b"CREATE TABLE users (id INT);\n"
           b"CREATE VIEW active AS SELECT id FROM users;\n"
           b"CREATE FUNCTION addone(a INT) RETURNS INT AS $$ SELECT a+1 $$ LANGUAGE sql;\n")
    proj = extract_file("schema.sql", src)
    kinds = _kinds(proj)
    assert kinds["users"] == "table"
    assert kinds["active"] == "view"
    assert kinds["addone"] == "function"

    # A schema change (new column) drifts the table — the useful migration signal.
    edited = b"CREATE TABLE users (id INT, name TEXT);\n"
    h1 = {n: a["content_hash"] for n, a in extract_file("t.sql", b"CREATE TABLE users (id INT);\n").nodes.items()}
    h2 = {n: a["content_hash"] for n, a in extract_file("t.sql", edited).nodes.items()}
    assert h1["sym:t.sql#users"] != h2["sym:t.sql#users"]


# --- Import + call enrichment (the per-language "extra layer") -------------------------------------


def _import_edges(extractor, file_imports, file_sources):
    import networkx as nx

    graph = nx.DiGraph()
    extractor.add_import_edges(graph, file_imports, file_sources, root=None)
    return set(graph.edges())


def test_rust_mod_import_edges():
    from yigraf.languages.tags import RustExtractor

    assert proj_imports("lib.rs", b"mod util;\nfn main() {}\n") == ["util"]
    edges = _import_edges(
        RustExtractor(),
        {"file:src/lib.rs": ["util"]},
        {"file:src/lib.rs": "src/lib.rs", "file:src/util.rs": "src/util.rs"},
    )
    assert edges == {("file:src/lib.rs", "file:src/util.rs")}


def test_java_import_edges_resolve_by_package_path():
    from yigraf.languages.tags import JavaExtractor

    edges = _import_edges(
        JavaExtractor(),
        {"file:com/foo/App.java": ["com.foo.Util", "java.util.List"]},  # only the in-repo one resolves
        {"file:com/foo/App.java": "com/foo/App.java", "file:com/foo/Util.java": "com/foo/Util.java"},
    )
    assert edges == {("file:com/foo/App.java", "file:com/foo/Util.java")}


def test_c_extracts_calls_and_include_edges():
    src = b'#include "util.h"\nint helper() { return 1; }\nint main() { return helper(); }\n'
    proj = extract_file("m.c", src)
    assert proj.nodes["file:m.c"]["imports"] == ["util.h"]
    assert ("sym:m.c#main", "sym:m.c#helper") in _edges(proj, "calls")

    from yigraf.languages.tags import CExtractor

    edges = _import_edges(
        CExtractor(),
        {"file:src/m.c": ["util.h"]},
        {"file:src/m.c": "src/m.c", "file:src/util.h": "src/util.h"},
    )
    assert edges == {("file:src/m.c", "file:src/util.h")}


def test_c_body_change_drifts_after_declarator_promotion():
    # C tags capture the function_declarator; promotion to function_definition means the *body* is in
    # the hash, so a body edit must drift (it wouldn't if we hashed only the declarator).
    base = b"int helper() { return 1; }\n"
    edited = b"int helper() { return 2; }\n"
    h1 = {n: a["content_hash"] for n, a in extract_file("m.c", base).nodes.items()}
    h2 = {n: a["content_hash"] for n, a in extract_file("m.c", edited).nodes.items()}
    assert h1["sym:m.c#helper"] != h2["sym:m.c#helper"]


def test_ruby_require_relative_recorded():
    proj = extract_file("app.rb", b'require_relative "util"\nclass C\n  def m\n    1\n  end\nend\n')
    assert proj.nodes["file:app.rb"]["imports"] == ["util"]


def test_php_require_recorded():
    proj = extract_file("a.php", b'<?php\nrequire_once "util.php";\nfunction f() { return 1; }\n')
    assert proj.nodes["file:a.php"]["imports"] == ["util.php"]


def proj_imports(relpath, src):
    return extract_file(relpath, src).nodes[f"file:{relpath.casefold()}"]["imports"]
