---
edges:
  task:status-surface/1:
    implements:
    - anchor: 6fcfe7c9d86e8d08ea8285519798f14c67579749dd859716826bff195e13ebfd
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/status.py#compute_status
    - anchor: 8c219efc3498b031f797b7a1425e3de11fe3ff0f63f1ac0e11995f5e8a2264db
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/status.py#StatusSummary
    - anchor: c42031ccfdedcb19110abe91c718486cda6eda0128774a97d8911572c093a80a
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/cli.py#status_cmd
    - anchor: 59982f9b71548591d00f6c6e9bd2461aefeac1ef6be8fd45e6dff3caf742cf33
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/hooks.py#_ensure_statusline
    - anchor: c2ccf9296e8b36f1250f03901a9f79c1ef1bf153be03d1ee49bf55c55719bb1d
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/cli.py#statusline_cmd
    - anchor: 0a791e94b09fba66067ef629363c2176ddc84a8be781d9c37e91e1dd6304951d
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/cli.py#_claude_ctx
    - anchor: 011a806d0ea0c909c17d97ccf3f36bfbdd2d835f5ad25efe3f7e3481e61fa31c
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/update.py#refresh
    - anchor: 83f255232b206b3b9e0bdebdc2157e27819be47ebddca27dc2dfaf5751e376ca
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/update.py#available
    tracks: int:status-surface
family: plan
id: plan:status-surface
---
# Status surface

## Tasks
- [x] {#1} Host-agnostic status summary: StatusSummary value object + 'yigraf status' command (line/json) + per-host statusline adapter
