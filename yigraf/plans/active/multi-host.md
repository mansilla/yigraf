---
edges:
  task:multi-host/1:
    implements:
    - anchor: 0d2665ab922af1c2fa5ca0d01755f353af087f56bc67b219e2836333fe70523f
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/hooks.py#install_codex_hooks
    - anchor: 66d84a92cb40f0b0d635dde7fb52dd7f32bc827cec7269792cd31f6e32f63e4b
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/hooks.py#install_antigravity
    - anchor: ec6194bfc717e9c39d91d649db7212c247a86cbe47e16a44f114db025ee402bf
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/cli.py#_edited_file
    - anchor: b2a115a667f9788bef6ae7fcc12a86204879f4b63313c1da795a001006db0a12
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/hooks.py#detect_hosts
    - anchor: cf6c65147f5d30285a1cf93c539fa86c5125986fa7284706dc00313d993c0284
      anchor_algo: astnorm-v1
      sym: sym:src/yigraf/cli.py#install_cmd
    tracks: int:multi-host
family: plan
id: plan:multi-host
---
# Multi-host integration

## Tasks
- [x] {#1} Codex hooks (install-codex-hooks, reuse handlers, apply_patch path parse) + Antigravity rule installer (install-antigravity) + generalized _edited_file
