---
concerns:
- anchor: 0f6b3cddfcc37e03f0dd6183203c0f37ebc4f2368a7eb79c94b12b2f87c0634d
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/embeddings.py#refresh_index
- anchor: 737eeb81b76e72bbb53f42c8b5ed0f771db736544b7e03bac548f7d140ab3951
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/embeddings.py#semantic_scores
family: memory
id: mem:004
maturity: working
provenance:
  source: cli
serves:
- int:token-cheap-context
status: active
supersedes: []
type: decision
---
## embed only memory and intent with a local bge-small model and brute-force numpy cosine — no vector DB at this scale

**Why:** we embed tens-to-thousands of short statements, not the codebase, so N is tiny; a query is one matmul (exact, sub-ms). FAISS/hnswlib add a heavy native dep that buys nothing until N is very large

**Rejected:** a FAISS/vector-DB index — needless native dependency at this scale; revisit only past ~100k nodes
