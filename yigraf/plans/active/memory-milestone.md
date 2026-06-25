---
edges:
  task:memory-milestone/1:
    implements:
    - anchor: 154d8d28e1cd5dfbafefdd4d0e4d53c3cc73e5f61807e60e3ae4fd4bdcb7c4f1
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/memory.py#project_into
    - anchor: 3a0ffc70bdc2c78fe3d7fbd06ad3882773b521ab84488382ce078fa38959f52e
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/cli.py#remember
    tracks: int:memory-family
  task:memory-milestone/2:
    implements:
    - anchor: 0f6b3cddfcc37e03f0dd6183203c0f37ebc4f2368a7eb79c94b12b2f87c0634d
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/embeddings.py#refresh_index
    - anchor: 737eeb81b76e72bbb53f42c8b5ed0f771db736544b7e03bac548f7d140ab3951
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/embeddings.py#semantic_scores
    tracks: int:semantic-recall
  task:memory-milestone/3:
    tracks: int:memory-maturity
family: plan
id: plan:memory-milestone
---
# Memory milestone (post-v0)

## Tasks
- [x] {#1} M7 — memory node family + capture verbs (remember/note-constraint/supersede); concerns drift
- [x] {#2} M8 — embedding index + semantic seeder + write-time dedup (scoped hybrid)
- [ ] {#3} M9 — counters/maturity/GC + runtime telemetry (survival/usage/last_seen, union-merge driver)
