<!-- yigraf:start -->
## yigraf
This repo uses **yigraf** (a graph over code, intent, plan, and the *why*). Before changing code, run
`yigraf context "<topic>"` — the one read command: it surfaces governing intents, prior decisions, and
any drift to re-verify. Handed a node id by a warning, read it with `yigraf show <id>` (`context`
searches by meaning and cannot match an id). After finishing a task, run
`yigraf link task:<plan>/<n> sym:<path>#<name>` then `yigraf close task:<plan>/<n>` (the checkbox is
written by a verb, never by hand; `yigraf tasks --open` lists what is left), and `yigraf remember` the
non-obvious choices (with
`--why` and `--concerns <sym>`) — as the work lands, not as a closing ritual.

Before you report done, run `yigraf status`: "up to date" means **no drift, no stale and no unsettled
rename**, which is not the same as no open tasks. Settle the rename first — it is the only one of the
three that expires. `yigraf drift` explains the drift and lists any pending rename; `yigraf gc --apply`
settles them (`⚠ n rename`); `yigraf drift --stale` lists the stale completions; `yigraf conflicts`
lists the open knowledge-conflicts (`⚠ n conflict`) with the verbs that resolve them. `yigraf cheatsheet` prints every verb and flag; `yigraf changelog --since <version>` says what changed
under you after an upgrade.
<!-- yigraf:end -->
