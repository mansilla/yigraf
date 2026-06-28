---
edges:
  task:language-drift-coverage/1:
    tracks: int:drift-detection
  task:language-drift-coverage/2:
    tracks: int:structure-index
  task:language-drift-coverage/3:
    tracks: int:drift-detection
family: plan
id: plan:language-drift-coverage
---
# Language drift coverage — verify enforcement on every extractor-backed language

## Tasks
- [ ] {#1} Parametrized drift round-trip tests (body-edit→soft drift, comment/reformat→no drift, rename→re-anchor) for representative Tier B/C languages: Rust, Java, Ruby, PHP, Kotlin, C++
- [ ] {#2} Tested capability matrix per language (structure/signature/imports/inheritance/calls/drift-verified), asserted by a test and surfaced in docs (replaces the '16 languages' ambiguity)
- [ ] {#3} Decide Ruby/PHP astnorm quote handling (normalize vs keep semantically-distinct) and pin the choice with a test
