---
family: intent
id: int:structure-index
status: proposed
type: requirement
---
## Requirement
yigraf SHALL project a repo's source — in any enabled language — into file/module/symbol nodes with a reformatting-stable, AST-normalized content hash.

## Scenarios
- Given a comment-only edit, When the repo is rebuilt, Then no symbol's content hash changes.
- Given a symbol's body is edited, When rebuilt, Then exactly that symbol's hash changes.
- Given a file in a non-Python enabled language (e.g. Go), When the repo is rebuilt, Then its symbols are projected with the same node/hash contract.

## Design (how)
Per-language extractors (a declarative core + bespoke ones, dispatched by file suffix — yigraf.languages) feed one astnorm-v1 hash that drops comments/docstrings, canon quotes, and excludes the symbol's own name. Language-specific astnorm knobs are empty where they don't apply (Go has no docstrings/quote-style ambiguity).
