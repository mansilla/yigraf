---
concerns:
- anchor: 66d84a92cb40f0b0d635dde7fb52dd7f32bc827cec7269792cd31f6e32f63e4b
  anchor_algo: astnorm-v1
  sym: sym:src/yigraf/hooks.py#install_antigravity
family: memory
id: mem:020
maturity: working
provenance:
  source: cli
serves:
- int:multi-host
status: active
supersedes: []
type: decision
---
## Antigravity has no hooks, so its complement is an always-on .agents/rules file pointing at the MCP tools; the global mcp_config.json is printed, not auto-written

**Why:** verified: the Antigravity IDE has no lifecycle-hook/context-injection system, so there is no push channel to wire — MCP (pull) + an always-on rule that instructs the agent to call the MCP tools is the substitute. The global mcp_config.json path is version-specific (~/.gemini/antigravity/ vs ~/.gemini/config/), so auto-writing it risks the wrong location; printing the snippet for the in-app MCP editor is safer and is an outward/global change the user should apply deliberately.

**Rejected:** auto-write ~/.gemini/.../mcp_config.json — version-specific path, and a global/outward change better left to the user; or invent a hook for Antigravity — impossible, the IDE exposes none
