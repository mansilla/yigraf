<!-- yigraf:start -->
## yigraf
This repo uses **yigraf** (a graph over code, intent, plan, and the *why*). Before changing code, run
`yigraf context "<topic>"` — the one read command: it surfaces governing intents, prior decisions, and
any drift to re-verify. Handed a node id by a warning, read it with `yigraf show <id>` (`context`
searches by meaning and cannot match an id). After finishing a task, run
`yigraf link task:<plan>/<n> sym:<path>#<name>`, and `yigraf remember` the non-obvious choices (with
`--why` and `--concerns <sym>`) — as the work lands, not as a closing ritual.

Before you report done, run `yigraf status`: "up to date" means **no drift AND no stale**, which is not
the same as no open tasks. `yigraf drift` explains the drift; `yigraf drift --stale` lists the stale
completions. `yigraf cheatsheet` prints every verb and flag.
<!-- yigraf:end -->
