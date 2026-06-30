---
concerns:
- anchor: 34dd0c31d599827eb6420af1f6aef3b3aaeb10943a0ce9b3c2cafb8f04e23f3a
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/status.py#StatusSummary._pretty
family: memory
id: mem:022
maturity: working
provenance:
  source: cli
serves:
- int:status-surface
status: active
supersedes: []
type: decision
---
## The pretty statusline brand is a spinning [Yigraf]: the Y rotates through 0/90/180/270 (Y≻⅄≺) with 'igraf' in Mathematical-Monospace; the plain render stays ASCII 'yigraf'

**Why:** Design law #2: the styled render is a human-facing TTY flourish, but _plain is the byte-stable channel pipes/--json/tests/agent-injection depend on (test asserts startswith 'yigraf '), so the brand animation lives only in _pretty and SPIN[0]='Y' keeps the color test green

**Rejected:** Changing _plain to [Yigraf] too — breaks byte-stability and the startswith('yigraf ') test contract; or small-caps ɪɢʀᴀꜰ — kept Math-Monospace 𝚒𝚐𝚛𝚊𝚏 as the geekier terminal-font look (fallback if a terminal lacks the U+1D68A block)
