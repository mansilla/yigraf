---
edges:
  task:yigraf-v0/1:
    implements:
    - anchor: a9ff8ea649f658e0c13bc77b46a58f373fa1aa115fc5565e04bfda5c51e33c6f
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/extract.py#build_graph
    - anchor: e72df3f4d2eb54a0236068cc3df68860bff3f0de6bc225204c88cd5901ebb42c
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/astnorm.py#content_hash
    tracks: int:structure-index
  task:yigraf-v0/2:
    implements:
    - anchor: e8c1fe579a17cc4a857787b6b3590c551f6605c25bbeb351f0e0faf0c8d01cb4
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/extract.py#symbol_content_hash
    - anchor: 06b11a96d735a11dcc998f5fd2d16c66c191e54288c6b7db2c9592d4c1c61b28
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/artifacts.py#add_edge_to_plan
    tracks: int:enforceable-link
  task:yigraf-v0/3:
    implements:
    - anchor: c7ae285a4357e06d486fc0b8212b2cfcbe8737528098b88febdc0dfe10ad2e3d
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/drift.py#compute_drift
    - anchor: 59de8a53d92c87f92bc96430017ed3d5634a5e0d5b21fb7ea5d4d08398faeca0
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/drift.py#resolve_renames
    tracks: int:drift-detection
  task:yigraf-v0/4:
    implements:
    - anchor: 1d96bebeff547d7af30322c5cddeabc8ecc6de879dc0a5fb7c149dc399e31956
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/retrieval.py#context
    tracks: int:token-cheap-context
  task:yigraf-v0/5:
    implements:
    - anchor: a69f41391790fa81c55ef6ead28f82937326d8341d8fdc196910e5d10ce29f9e
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/retrieval.py#context_for_locus
    - anchor: 93a7507c388ed929cc1e72cc180de4c11c01c98a938f9390f24b012ebbeec5fe
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/hooks.py#install_claude_hooks
    tracks: int:hook-surfacing
family: plan
id: plan:yigraf-v0
---
# yigraf v0 spine

## Tasks
- [ ] {#1} structure index + astnorm content hash
- [ ] {#2} intent/plan artifacts + enforceable linking
- [ ] {#3} drift detection + rename re-anchor
- [ ] {#4} token-cheap retrieval (context)
- [ ] {#5} Claude Code hooks + skill
