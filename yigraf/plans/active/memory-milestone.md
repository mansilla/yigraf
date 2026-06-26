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
    implements:
    - anchor: a63c7f8f20cf0f98747c769a7a85ccdcd60bcb8a4b82f610340674ab52728ba7
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/counters.py#apply_maturity
    - anchor: 9963f92ba4614294c0bf682e772e229e8b0ce2e539c73162133009fc599237eb
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/counters.py#survival_of
    - anchor: 13745330abda48c7d5d674cc44a1bf46e39b0960655ad9ec2ec39c80cef3249c
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/counters.py#record_injection
    - anchor: 345dc85647e0255006c27566975147e536fa1046ab83b24a7c85560dee0c83d9
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/counters.py#classify_gc
    - anchor: 7ad1b54aa9f4b3e005f6c01c7423a7c2d00d47c51ee97c0e40020b55fcc41014
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/counters.py#merge_node_link
    tracks: int:memory-maturity
family: plan
id: plan:memory-milestone
---
# Memory milestone (post-v0)

## Tasks
- [x] {#1} M7 — memory node family + capture verbs (remember/note-constraint/supersede); concerns drift
- [x] {#2} M8 — embedding index + semantic seeder + write-time dedup (scoped hybrid)
- [x] {#3} M9 — counters/maturity/GC + runtime telemetry (survival/usage/last_seen, union-merge driver)
