---
concerns:
- anchor: 3366a112e423c1d2107d3b156b254bc20409862882b15e20aac8634505259f32
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/cli.py#status_cmd
family: memory
id: mem:015
maturity: working
promotable: true
provenance:
  source: cli
serves: []
status: active
supersedes: []
type: constraint
---
## The status render must force color through click (typer.echo(..., color=use_color)) — a statusline pipes stdout (non-TTY), and click strips ANSI on a pipe by default, which would silently drop all statusline color
