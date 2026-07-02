---
concerns:
- anchor: 1b4675a69cacd5e82a622af19038966217128cc6443ca1fcce81adf53755cd47
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/cli.py#install_cmd
family: memory
id: mem:027
maturity: working
provenance:
  source: cli
serves:
- int:multi-host
status: active
supersedes: []
type: decision
---
## yigraf install wires full power by default: the generic host-independent channel (post-commit rebuild hook + graph.json merge driver + AGENTS.md + the MCP pull server) installs unconditionally, then detected hosts (Claude/Codex/Antigravity) layer their native push hooks on top; only the heavy embeddings backend stays opt-in, offered loudly (never silently degraded)

**Why:** real-project testing showed MCP, embeddings, and the git hooks each needed a separate explicit install, so a fresh install silently shipped the weak version — install now delivers everything host-agnostic by default and treats a missing capability as agent-actionable guidance, not a silent lexical fallback (design law #1)

**Rejected:** keep MCP+embeddings as opt-in extras and only wire the detected host channel — the pre-existing behavior that caused the silent-degradation complaint
