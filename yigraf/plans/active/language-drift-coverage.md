---
edges:
  task:language-drift-coverage/1:
    implements:
    - anchor: 07989db5694077c55600578713f2c4a7189ca5fb62989039149ddc020b407722
      anchor_algo: astnorm-v1
      sym: sym:tests/test_language_drift.py#test_drift_round_trip_per_language
    tracks: int:drift-detection
  task:language-drift-coverage/2:
    implements:
    - anchor: 246089e93acd3bc40a36f55abe6e1075d559e409e1adf3d69ea9c76f9737d1b2
      anchor_algo: astnorm-v1
      sym: sym:tests/test_language_drift.py#test_capability_matrix
    tracks: int:structure-index
  task:language-drift-coverage/3:
    implements:
    - anchor: 1a43cc443a17836460b43c9876ad7ea37a6d95fcb87f2f714d9ab1c75efc26a1
      anchor_algo: astnorm-v1
      sym: sym:tests/test_language_drift.py#test_ruby_quote_flip_is_drift_not_cosmetic
    tracks: int:drift-detection
family: plan
id: plan:language-drift-coverage
---
# Language drift coverage — verify enforcement on every extractor-backed language

## Tasks
- [x] {#1} Parametrized drift round-trips (body→soft drift, comment→no drift, rename→re-anchor) — done for ALL 16 langs (11 in test_language_drift.py: Rust/Java/Ruby/PHP/Kotlin/C++/C/C#/Scala/Swift/Bash; Go/TS in test_languages, Python in test_extract, SQL schema-drift in test_tags)
- [x] {#2} Tested capability matrix (symbols/calls/imports/inheritance/drift) asserted by test_capability_matrix (imports+inheritance both directions) + surfaced in docs/language-support.md
- [x] {#3} Ruby/PHP astnorm quote handling DECIDED: keep semantically-distinct (not normalized — `'` literal vs `"` interpolating differ), pinned by test_{ruby,php}_quote_flip_is_drift_not_cosmetic
