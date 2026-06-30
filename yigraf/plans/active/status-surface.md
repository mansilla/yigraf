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
    - anchor: 59982f9b71548591d00f6c6e9bd2461aefeac1ef6be8fd45e6dff3caf742cf33
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/hooks.py#_ensure_statusline
    - anchor: 71282160692f0b2895e966d4bd2c349c7f47ca913bcd8ea346cdcd9920360791
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/cli.py#statusline_cmd
    - anchor: 0a791e94b09fba66067ef629363c2176ddc84a8be781d9c37e91e1dd6304951d
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/cli.py#_claude_ctx
    tracks: int:status-surface
family: plan
id: plan:status-surface
---
# Status surface

## Tasks
- [x] {#1} Host-agnostic status summary: StatusSummary value object + 'yigraf status' command (line/json) + per-host statusline adapter
