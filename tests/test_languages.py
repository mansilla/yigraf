"""Multi-language extraction through the languages/ framework — Go (the first non-Python extractor).

Exercises the same contracts test_extract.py pins for Python — node ids/kinds, the file/module/symbol
hierarchy, intra-file call resolution, recorded imports — plus the drift anchor (astnorm) on Go, all
via the suffix-dispatching ``extract_file`` so the registry is covered too.
"""
from yigraf.extract import extract_file

SAMPLE = '''package sample

import (
	"fmt"
	"strings"
)

type Greeter struct {
	prefix string
}

type Speaker interface {
	Speak() string
}

func New(p string) *Greeter {
	return &Greeter{prefix: p}
}

func (g *Greeter) Speak() string {
	return format(g.prefix)
}

func format(s string) string {
	return strings.ToUpper(s)
}

func main() {
	g := New("hi")
	fmt.Println(g.Speak())
}
'''


def _project(source: str = SAMPLE):
    return extract_file("pkg/m.go", source.encode())


def _edges(proj, relation: str) -> set[tuple[str, str]]:
    return {(s, d) for s, d, a in proj.edges if a["relation"] == relation}


def _hashes(source: str) -> dict[str, str]:
    proj = extract_file("pkg/m.go", source.encode())
    return {nid: a["content_hash"] for nid, a in proj.nodes.items() if "content_hash" in a}


def _changed(before: dict[str, str], after: dict[str, str]) -> set[str]:
    keys = set(before) | set(after)
    return {k for k in keys if before.get(k) != after.get(k)}


def test_emits_expected_node_ids_and_kinds():
    proj = _project()
    kinds = {nid: attrs["kind"] for nid, attrs in proj.nodes.items()}
    assert kinds == {
        "file:pkg/m.go": "file",
        "module:pkg/m.go": "module",
        "sym:pkg/m.go#Greeter": "type",
        "sym:pkg/m.go#Speaker": "type",
        "sym:pkg/m.go#New": "function",
        "sym:pkg/m.go#Greeter.Speak": "method",
        "sym:pkg/m.go#format": "function",
        "sym:pkg/m.go#main": "function",
    }


def test_nodes_carry_go_language_and_content_hash():
    proj = _project()
    for nid, attrs in proj.nodes.items():
        assert attrs["family"] == "structure"
        assert attrs["language"] == "go"
        assert attrs["confidence"] == "EXTRACTED"
        assert "content_hash" in attrs


def test_method_is_contained_by_its_receiver_type_when_local():
    proj = _project()
    assert _edges(proj, "contains") == {
        ("file:pkg/m.go", "module:pkg/m.go"),
        ("module:pkg/m.go", "sym:pkg/m.go#Greeter"),
        ("module:pkg/m.go", "sym:pkg/m.go#Speaker"),
        ("module:pkg/m.go", "sym:pkg/m.go#New"),
        ("module:pkg/m.go", "sym:pkg/m.go#format"),
        ("module:pkg/m.go", "sym:pkg/m.go#main"),
        ("sym:pkg/m.go#Greeter", "sym:pkg/m.go#Greeter.Speak"),
    }


def test_method_falls_back_to_module_when_receiver_type_is_foreign():
    # Receiver type declared elsewhere (not in this file) → method hangs off the module, not a phantom.
    src = "package p\n\nfunc (x *Other) M() int {\n\treturn 1\n}\n"
    proj = extract_file("pkg/m.go", src.encode())
    assert ("module:pkg/m.go", "sym:pkg/m.go#Other.M") in _edges(proj, "contains")
    assert "sym:pkg/m.go#Other" not in proj.nodes  # no phantom type node


def test_intra_file_calls_resolve_bare_names_and_drop_selectors():
    proj = _project()
    assert _edges(proj, "calls") == {
        ("sym:pkg/m.go#Greeter.Speak", "sym:pkg/m.go#format"),  # format(...) — bare identifier
        ("sym:pkg/m.go#main", "sym:pkg/m.go#New"),              # New("hi") — bare identifier
        # strings.ToUpper / g.Speak / fmt.Println are selectors → unresolved, no phantom edges
    }


def test_file_node_records_sorted_imports():
    proj = _project()
    assert proj.nodes["file:pkg/m.go"]["imports"] == ["fmt", "strings"]


def test_path_is_casefolded_but_symbol_name_is_preserved():
    proj = extract_file("Pkg/Mod.go", b"package p\n\ntype Foo struct{}\n")
    assert "file:pkg/mod.go" in proj.nodes
    assert "sym:pkg/mod.go#Foo" in proj.nodes  # type name keeps its case


def test_body_change_flips_exactly_that_symbol():
    edited = SAMPLE.replace("return format(g.prefix)", "return format(g.prefix) + \"!\"")
    assert _changed(_hashes(SAMPLE), _hashes(edited)) == {"sym:pkg/m.go#Greeter.Speak"}


def test_function_body_change_does_not_flip_the_module():
    edited = SAMPLE.replace("return strings.ToUpper(s)", "return strings.ToLower(s)")
    changed = _changed(_hashes(SAMPLE), _hashes(edited))
    assert changed == {"sym:pkg/m.go#format"}
    assert "module:pkg/m.go" not in changed and "file:pkg/m.go" not in changed


def test_comment_only_edit_changes_no_hash():
    edited = SAMPLE.replace("return format(g.prefix)", "return format(g.prefix) // speak it")
    assert _changed(_hashes(SAMPLE), _hashes(edited)) == set()


def test_rename_preserves_body_hash_for_reanchoring():
    # astnorm excludes a symbol's own name, so a pure rename keeps the body hash — the new id carries
    # the same hash as the old, which is how M3 re-anchors a rename instead of reporting a deletion.
    before = _hashes(SAMPLE)
    renamed = SAMPLE.replace("func format(s string) string", "func formatted(s string) string")
    after = _hashes(renamed)
    assert before["sym:pkg/m.go#format"] == after["sym:pkg/m.go#formatted"]


# ==================================================================================================
# TypeScript / JavaScript
# ==================================================================================================

TS = '''import { helper } from "./util";

export interface Speaker {
	speak(): string;
}

export type Name = string;

export const greet = (name: Name): string => {
	return helper(name);
};

export function shout(name: Name): string {
	return greet(name).toUpperCase();
}

export class Greeter {
	prefix: string;

	speak(): string {
		return this.format();
	}

	format(): string {
		return shout(this.prefix);
	}
}
'''


def _ts(source: str = TS):
    return extract_file("pkg/m.ts", source.encode())


def test_ts_emits_functions_arrows_classes_methods_and_types():
    kinds = {nid: a["kind"] for nid, a in _ts().nodes.items()}
    assert kinds == {
        "file:pkg/m.ts": "file",
        "module:pkg/m.ts": "module",
        "sym:pkg/m.ts#Speaker": "type",          # interface
        "sym:pkg/m.ts#Name": "type",             # type alias
        "sym:pkg/m.ts#greet": "function",        # exported arrow const
        "sym:pkg/m.ts#shout": "function",        # exported function decl
        "sym:pkg/m.ts#Greeter": "class",
        "sym:pkg/m.ts#Greeter.speak": "method",
        "sym:pkg/m.ts#Greeter.format": "method",
    }


def test_ts_language_label_and_arrow_signature():
    nodes = _ts().nodes
    assert nodes["sym:pkg/m.ts#greet"]["language"] == "typescript"
    # arrow const keeps a useful signature including its name (verbatim override)
    assert nodes["sym:pkg/m.ts#greet"]["signature"] == "export const greet = (name: Name): string =>"


def test_ts_calls_resolve_identifiers_and_this_methods():
    assert _edges(_ts(), "calls") == {
        ("sym:pkg/m.ts#shout", "sym:pkg/m.ts#greet"),            # greet(name)
        ("sym:pkg/m.ts#Greeter.speak", "sym:pkg/m.ts#Greeter.format"),  # this.format()
        ("sym:pkg/m.ts#Greeter.format", "sym:pkg/m.ts#shout"),  # shout(...)
        # helper(...) is imported (not in-file) and .toUpperCase() is a member call → no edges
    }


def test_ts_contains_nests_methods_under_class():
    contains = _edges(_ts(), "contains")
    assert ("sym:pkg/m.ts#Greeter", "sym:pkg/m.ts#Greeter.speak") in contains
    assert ("module:pkg/m.ts", "sym:pkg/m.ts#Greeter") in contains
    assert ("module:pkg/m.ts", "sym:pkg/m.ts#greet") in contains


def test_ts_records_imports():
    assert _ts().nodes["file:pkg/m.ts"]["imports"] == ["./util"]


def test_ts_quote_style_change_is_not_drift():
    def hashes(src):
        return {n: a["content_hash"] for n, a in extract_file("m.ts", src.encode()).nodes.items()}
    base = 'export const s = () => { return "hi"; };\n'
    edited = "export const s = () => { return 'hi'; };\n"
    assert hashes(base) == hashes(edited)


def test_ts_body_change_flips_exactly_that_symbol():
    def hashes(src):
        return {n: a["content_hash"] for n, a in extract_file("pkg/m.ts", src.encode()).nodes.items()}
    before, after = hashes(TS), hashes(TS.replace("return this.format();", "return this.format() + \"!\";"))
    assert {k for k in before | after.keys() if before.get(k) != after.get(k)} == {"sym:pkg/m.ts#Greeter.speak"}


def test_jsx_and_tsx_parse_with_the_right_grammar():
    # .tsx uses the tsx grammar (JSX + types); a component arrow becomes a function symbol.
    src = "export const App = () => <div>{greet()}</div>;\n"
    proj = extract_file("ui/App.tsx", src.encode())
    assert proj.nodes["sym:ui/app.tsx#App"]["kind"] == "function"
    assert proj.nodes["sym:ui/app.tsx#App"]["language"] == "typescript"


def test_js_arrow_const_is_a_function_and_resolves_calls():
    src = (
        "export const add = (a, b) => a + b;\n"
        "function mul(a, b) { return a * b; }\n"
        "const compute = () => mul(add(1, 2), 3);\n"
    )
    proj = extract_file("m.js", src.encode())
    assert proj.nodes["sym:m.js#add"]["kind"] == "function"
    assert proj.nodes["sym:m.js#add"]["language"] == "javascript"
    assert _edges(proj, "calls") == {
        ("sym:m.js#compute", "sym:m.js#mul"),
        ("sym:m.js#compute", "sym:m.js#add"),
    }


def test_relative_import_edges_resolve_across_suffixes():
    import networkx as nx

    from yigraf.languages.jsts import JsTsExtractor

    graph = nx.DiGraph()
    file_sources = {
        "file:app/a.ts": "app/a.ts",
        "file:app/util.ts": "app/util.ts",
        "file:app/c.tsx": "app/c.tsx",
    }
    file_imports = {
        "file:app/a.ts": ["./util", "../ext/lib", "react"],  # only ./util is in-repo
        "file:app/c.tsx": ["./util"],                         # cross-suffix .tsx → .ts
    }
    JsTsExtractor().add_import_edges(graph, file_imports, file_sources, root=None)
    assert graph.has_edge("file:app/a.ts", "file:app/util.ts")
    assert graph.has_edge("file:app/c.tsx", "file:app/util.ts")
    assert graph.number_of_edges() == 2  # bare "react" + unresolvable "../ext/lib" make no edge
