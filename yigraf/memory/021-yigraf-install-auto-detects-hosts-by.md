---
concerns:
- anchor: b2a115a667f9788bef6ae7fcc12a86204879f4b63313c1da795a001006db0a12
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/hooks.py#detect_hosts
family: memory
id: mem:021
maturity: working
provenance:
  source: cli
serves:
- int:multi-host
status: active
supersedes: []
type: decision
---
## yigraf install auto-detects hosts by config markers (repo-local + home dir), wires every detected one, and falls back to MCP when none of the three is found or an unsupported --host is given

**Why:** the user shouldn't have to know which install-X command matches their host. Markers (.claude/.codex/.agents in repo, or ~/.claude / ~/.codex / ~/.gemini on the machine) are a zero-config signal of which hosts are present; wiring ALL detected ones is more useful than guessing a single 'the' host on a multi-tool machine. MCP is the universal floor, so any unrecognized/other host degrades to printing the MCP config — consistent with 'MCP is the bet'. detect_hosts takes an injectable home for deterministic tests.

**Rejected:** pick a single host by precedence — wrong on a machine with several installed; or prompt the user to choose — defeats the one-command goal; or only honor explicit --host — no zero-config path
