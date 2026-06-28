---
edges:
  task:status-surface/1:
    implements:
    - anchor: 0f9367e1084fbb8254e51e7c38f4a72d82bdab2759e1500e0423681e277964ca
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/status.py#compute_status
    - anchor: 5b2f9126fa156a78a65df7c0dd0b2d2f2960fa65a2dd2a25bb52fb061fb0ea67
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/status.py#StatusSummary
    - anchor: 3366a112e423c1d2107d3b156b254bc20409862882b15e20aac8634505259f32
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/cli.py#status_cmd
    tracks: int:status-surface
family: plan
id: plan:status-surface
---
# Status surface

## Tasks
- [ ] {#1} Host-agnostic status summary: StatusSummary value object + 'yigraf status' command (line/json) + per-host statusline adapter
