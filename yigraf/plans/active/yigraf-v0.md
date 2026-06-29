---
edges:
  task:yigraf-v0/1:
    implements:
    - anchor: 9ecd1eb082cd37061f3a8dde68ebb1a5a1ab7ce4d35f9090f96c175919a49631
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/extract.py#build_graph
    - anchor: bc5b1b0af4cbc9e1b99f4837ee704931625ab7e3e01f0f34a0a043bfbe3486a5
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/astnorm.py#content_hash
    tracks: int:structure-index
  task:yigraf-v0/2:
    implements:
    - anchor: 0bdbe77b588a33fcc371cd499904d817f308a20139f505435ec81ab4f859b9bc
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
    - anchor: 2c27400fb9b425aac63c59f20b304b4cd6406e24055d2131391f4bf3caa6af27
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/retrieval.py#context
    tracks: int:token-cheap-context
  task:yigraf-v0/5:
    implements:
    - anchor: b3232318c4d1bc867a56349efef6921a892ed9177c67fda541bfa48495207c3c
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/retrieval.py#context_for_locus
    - anchor: 21ae4a812ee5f36f11307520f41f1ef3bde656927eacae88e00ad497bf8d1a61
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/hooks.py#install_claude_hooks
    tracks: int:hook-surfacing
family: plan
id: plan:yigraf-v0
---
# yigraf v0 spine

## Tasks
- [x] {#1} structure index + astnorm content hash
- [x] {#2} intent/plan artifacts + enforceable linking
- [x] {#3} drift detection + rename re-anchor
- [x] {#4} token-cheap retrieval (context)
- [x] {#5} Claude Code hooks + skill
