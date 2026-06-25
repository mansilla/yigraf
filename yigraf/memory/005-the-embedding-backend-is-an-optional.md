---
concerns:
- anchor: 847c43c6c2c79bf1601a2f5fd4c91cfff59b9a8a95be115a0af28d044b96fc06
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/embeddings.py#get_embedder
family: memory
id: mem:005
maturity: working
provenance:
  source: cli
serves:
- int:token-cheap-context
status: active
supersedes: []
type: decision
---
## the embedding backend is an optional extra with graceful lexical fallback, never a hard dependency

**Why:** no host exposes an embedding endpoint to a hook, so embeddings are yigraf's own responsibility; making them required would break the zero-config promise — absent backend degrades to the v0 lexical seeder

**Rejected:** require sentence-transformers in core deps — forces a torch install on every user for a feature that's an enhancement
