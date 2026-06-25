---
edges:
  task:yigraf-v0/1:
    implements:
    - anchor: 88a5333cb3cfef7104603db098202009cae063394745e9a19ed0ef6764366cdc
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
    - anchor: f8b633dccc7ce4d90d66190c6bb9399cd383b1795ad2d792e0e3f0d6b54eb9a3
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/drift.py#compute_drift
    - anchor: e716cbe43024eaa7324bd553b48116ef692ad82ae9c0205465f80cddb018a9d4
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/drift.py#resolve_renames
    tracks: int:drift-detection
  task:yigraf-v0/4:
    implements:
    - anchor: bfd78227bf75a7c05485f844617cfe2cb98600b37e893e30f032e04f63367243
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/retrieval.py#context
    tracks: int:token-cheap-context
  task:yigraf-v0/5:
    implements:
    - anchor: 8a8da94d764d87cf24a36f543b43902ad894d0f6dd1f6c18a6f056adbf1963e1
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
