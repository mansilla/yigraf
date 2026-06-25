---
family: intent
id: int:semantic-recall
status: active
type: requirement
---
## Requirement
yigraf SHALL recall memory and intent nodes by meaning — not only shared identifiers — and SHALL degrade to lexical retrieval when no embedding backend is available.

## Scenarios
- Given a query phrased differently from a decision's wording, When yigraf context runs with an embedding backend, Then the decision is seeded and surfaced.
- Given no embedding backend installed, When yigraf context runs, Then it returns lexical results identically to v0, with no error.

## Design (how)
Scoped hybrid: lexical/IDF over all families + a bge-small embedding index over memory+intent only; union-of-top-k seeds; ranking match = per-source-normalized max of lexical and cosine. numpy brute-force, no vector DB.
