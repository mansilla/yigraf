---
edges:
  task:phase-3-structure-depth/1:
    implements:
    - anchor: 9ecd1eb082cd37061f3a8dde68ebb1a5a1ab7ce4d35f9090f96c175919a49631
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/extract.py#build_graph
    - anchor: 0d36307bc2451f04a2ec42024d4d6cc111c55e3f0bc667e5a46e7153416fd69a
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/languages/python.py#PythonExtractor.add_inheritance_edges
  task:phase-3-structure-depth/2:
    implements:
    - anchor: af66ea36662e5caae8d97b45b7b18fc597305bf48f0d9c850042d134510446ff
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/retrieval.py#_render
  task:phase-3-structure-depth/3:
    implements:
    - anchor: b89952930b359919a5c2618612f5f341b9e149ed68f24d767c0d22176c7fb67c
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/languages/tags.py#TagExtractor.add_inheritance_edges
    - anchor: 4761e47a2eeabb9d78f26d1ec804bf27e1f19bf6c337df47376488048f534318
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/languages/tags.py#_heritage_walk
  task:phase-3-structure-depth/4:
    implements:
    - anchor: d590f70ec3352f0a4f1b423462d55bf29f1e43c5971acc7e016694187733d536
      anchor_algo: astnorm-v1
      sym: sym:scripts/eval/render_ab.py#main
  task:phase-3-structure-depth/5:
    implements:
    - anchor: 4888beb70e6b354043e1f6abd14bcea9732c77e7dbbe7f7e5f2eebb73e684ea6
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/languages/go.py#GoExtractor.add_import_edges
    - anchor: 04b2a9de45b4da81272b61c3a528379e86389ba49712c89089c4675247f588d0
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/languages/tags.py#ScalaExtractor
family: plan
id: plan:phase-3-structure-depth
---
# Phase 3 — structure depth

## Tasks
- [x] {#1} Inheritance edges: import-aware (Python/TS) + package-aware (Go); Python relative imports (#16)
- [x] {#2} Ranking fix: suppress file:/module: containers from the render (gates source_for_seeds)
- [x] {#3} Inheritance edges for the tags-tier languages — all OO langs (Java/C#/Kotlin/Scala/Swift/C++/Rust/Ruby/PHP), name-resolved
- [x] {#4} Source-vs-signature A/B (n=4, 2 body-needing Qs): DECISION = do NOT flip — keep signature_only. Source bought 0 read/tool-call reduction; agent never called `yigraf context` (0/16) → the pull-path render knob is moot. `render_ab.py`.
- [x] {#5} Import edges: Go (go.mod package→dir), Kotlin/Scala (pkg→file by convention). C#/Swift N/A — `using` namespaces / module imports don't map to files. (Rust/Java/C/C++/Ruby/PHP already resolved imports.)
