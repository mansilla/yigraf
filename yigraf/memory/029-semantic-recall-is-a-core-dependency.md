---
concerns:
- anchor: d773341e72cb5611287c4478c97cb1bea4a26d0dbea793d2284c43ee49abfb3b
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/embeddings.py#get_embedder
family: memory
id: mem:029
maturity: working
provenance:
  source: cli
serves:
- int:token-cheap-context
status: active
supersedes:
- mem:005
type: decision
---
## semantic recall is a core dependency, on by default, via the fastembed (ONNX) backend

**Why:** the reason embeddings stayed opt-in was torch (~1GB); fastembed runs the same bge-small model on ONNX Runtime (~68MB, no torch) with measured ~0.9999 cosine parity on our memory/intent task, so full power by default is now affordable — sentence-transformers stays available behind [embeddings-torch] for MPS/fp32

**Rejected:** keep embeddings an opt-in extra (mem:005): unnecessary now that fastembed removes the torch tax that motivated it
