<!-- yigraf:start -->
## yigraf
This repo uses **yigraf** (a graph over code, intent, plan, and the *why*). Before changing code, run
`yigraf context "<topic>"` to see governing intents, prior decisions, and drift. After finishing a
task, run `yigraf link task:<plan>/<n> sym:<path>#<name>`, and `yigraf remember` the non-obvious
choices (with `--why` and `--concerns <sym>`). `yigraf drift` shows what needs re-verifying.
<!-- yigraf:end -->
