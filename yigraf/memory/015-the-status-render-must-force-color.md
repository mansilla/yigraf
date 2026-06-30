---
concerns:
- anchor: c42031ccfdedcb19110abe91c718486cda6eda0128774a97d8911572c093a80a
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
