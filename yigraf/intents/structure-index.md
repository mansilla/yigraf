---
family: intent
id: int:structure-index
status: proposed
type: requirement
---
## Requirement
yigraf SHALL project a Python repo into file/module/symbol nodes with a reformatting-stable, AST-normalized content hash.

## Scenarios
- Given a comment-only edit, When the repo is rebuilt, Then no symbol's content hash changes.
- Given a symbol's body is edited, When rebuilt, Then exactly that symbol's hash changes.

## Design (how)
tree-sitter extraction; astnorm-v1 hash drops comments/docstrings, canon quotes, excludes the symbol's own name.
