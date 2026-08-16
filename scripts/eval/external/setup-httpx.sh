#!/usr/bin/env bash
# Recreate the external benchmark repo: encode/httpx @ 0.28.1 with an authored yigraf workspace.
#
# Why an external repo: yigraf's own repo cannot produce an honest number, because its CLAUDE.md and
# AGENTS.md tell any agent to run `yigraf context` — so even a hookless arm reaches for the tool and
# the delta collapses to ~0 by construction. httpx ships no such instructions, so the `off` arm is a
# real no-yigraf baseline.
#
# The three decisions authored below were each verified against httpx 0.28.1's source before being
# written (Timeout's connect/read/write/pool kwargs, BaseTransport.handle_request, and
# `follow_redirects: bool = False` on Client). The FACTS are visible in the source; the *why* and the
# *rejected alternatives* are not — that asymmetry is what the benchmark measures.
#
# Usage:  scripts/eval/external/setup-httpx.sh <dest-dir>
set -euo pipefail

DEST="${1:?usage: setup-httpx.sh <dest-dir>}"
YIGRAF_PY="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/.venv/bin/python3"
Y() { "$YIGRAF_PY" -m yigraf "$@" --repo "$DEST"; }

rm -rf "$DEST"
git clone --quiet --depth 1 --branch 0.28.1 https://github.com/encode/httpx.git "$DEST"
"$YIGRAF_PY" -m yigraf init "$DEST" >/dev/null

Y intent timeout-axes --status satisfied \
  -s "httpx SHALL express a request timeout as four independent axes — connect, read, write and pool — never a single scalar, so a caller can bound each distinct stall mode separately." \
  --scenario "Given a caller passing Timeout(5.0, connect=10.0), When a request runs, Then connect is bounded at 10s and read/write/pool at 5s." >/dev/null

Y intent transport-pluggable --status satisfied \
  -s "httpx SHALL route every network operation through a BaseTransport/AsyncBaseTransport handle_request seam, so the HTTP engine is swappable and tests can substitute a transport without patching sockets." \
  --scenario "Given a MockTransport passed to Client(transport=...), When a request is issued, Then no real network I/O occurs and the mock's handler returns the Response." >/dev/null

Y intent explicit-redirects --status satisfied \
  -s "httpx SHALL NOT follow redirects by default; follow_redirects MUST default to False and be opted into per-request or per-client." \
  --scenario "Given a GET to a URL returning 302, When follow_redirects is not set, Then httpx returns the 302 Response itself rather than transparently following it." >/dev/null

Y plan httpx-core -t "httpx core design invariants" \
  --task "TIMEOUTS: express the four timeout axes as one Timeout config object threaded to the transport" \
  --task "TRANSPORT: define the sync/async transport seam every request flows through" \
  --task "REDIRECTS: make redirect-following explicit and off by default" >/dev/null

# `build` takes the repo as a POSITIONAL path, not --repo (unlike intent/plan/link/remember), so it
# cannot go through Y(). With `set -e` the wrong form aborts the whole setup half-authored.
"$YIGRAF_PY" -m yigraf build "$DEST" >/dev/null

Y link task:httpx-core/1 sym:httpx/_config.py#Timeout >/dev/null
# ALSO anchor the constructor, not just the enclosing class. astnorm-v1 hashes a class by its member
# *names*, deliberately NOT its method bodies (astnorm.py: "a class hash captures its member names but
# not method bodies, and editing a method body flips only that method's hash"). So a class anchor does
# not drift when a method body changes — verified both ways on this clone: adding a member drifts the
# class anchor, a pure body insertion inside __init__ does not. The enforceable case edits __init__, so
# without this line the anchor never drifts, the hook has nothing to surface, and the case scores a
# false 0/N that looks like "the hook doesn't work" when it is really "nothing was governed here".
Y link task:httpx-core/1 sym:httpx/_config.py#Timeout.__init__ >/dev/null
Y link task:httpx-core/1 int:timeout-axes >/dev/null
Y link task:httpx-core/2 sym:httpx/_transports/base.py#BaseTransport >/dev/null
Y link task:httpx-core/2 sym:httpx/_transports/base.py#AsyncBaseTransport >/dev/null
Y link task:httpx-core/2 int:transport-pluggable >/dev/null
Y link task:httpx-core/3 sym:httpx/_client.py#Client >/dev/null
Y link task:httpx-core/3 int:explicit-redirects >/dev/null

Y remember "Timeout is four independent axes (connect, read, write, pool) carried by one Timeout config object, not a single scalar deadline." \
  --why "The four stalls are physically different failures and want different bounds: connect covers DNS+TCP+TLS and may legitimately be slow on a cold path; read covers waiting on the server to produce a byte; write covers a slow upload; pool covers contention for a free connection when the caller's own concurrency is the bottleneck. A single scalar forces the operator to size the whole request by its slowest legitimate phase, which means either a generous timeout that never fires on a hung read, or a tight one that spuriously kills slow connects. A pool timeout in particular is a CLIENT-side saturation signal, not a server problem, and collapsing it into the same number makes that diagnosis impossible." \
  --serves int:timeout-axes --concerns sym:httpx/_config.py#Timeout \
  --rejected "A single scalar timeout (the requests-style total) — cannot separate a hung read from a slow connect, and hides pool saturation entirely." \
  --rejected "A per-call deadline computed from a monotonic clock — composes badly with connection reuse and gives no way to bound pool acquisition distinctly." >/dev/null

Y remember "All network I/O goes through the BaseTransport/AsyncBaseTransport handle_request seam; the Client never touches sockets directly." \
  --why "The seam exists so the HTTP engine is replaceable without forking the client: httpcore is the default implementation, but WSGI/ASGI transports let httpx call an in-process app with no network at all, and MockTransport makes tests deterministic without monkeypatching sockets or spinning a local server. Keeping the seam at handle_request (one Request in, one Response out) rather than at the connection level is what makes those substitutions total — anything lower would leak connection lifecycle into every implementation." \
  --serves int:transport-pluggable --concerns sym:httpx/_transports/base.py#BaseTransport \
  --rejected "Patch sockets or requests-style adapters mounted on URL prefixes — prefix mounting conflates routing with transport substitution and cannot express 'this whole client is in-process'." \
  --rejected "Put the seam at the connection-pool level — every alternative implementation would then have to reimplement connection lifecycle just to answer one request." >/dev/null

Y remember "follow_redirects defaults to False — httpx deliberately diverges from requests, which follows redirects transparently." \
  --why "Transparent redirect-following makes three things invisible that callers usually need to see: a redirect can silently downgrade or re-target a request across origins (a credential-leak vector when headers are replayed), it hides that an API contract changed, and it turns one call into an unbounded chain whose cost the caller never authorized. Defaulting to False makes the redirect an explicit, per-request decision; callers who want the old behaviour opt in with follow_redirects=True. This is a known, intentional migration cost from requests, not an oversight." \
  --serves int:explicit-redirects --concerns sym:httpx/_client.py#Client \
  --rejected "Follow redirects by default for requests API compatibility — silently reintroduces the cross-origin header-replay hazard and hides contract changes." >/dev/null

# Install the host-agnostic AGENTS.md instruction block (+ the Claude skill). LOAD-BEARING for the
# three-arm design: without it the clone has no yigraf affordance for an agent to *pull* through, so
# run_ab's `off` arm hides nothing that exists and `ambient` and `off` collapse into the SAME
# configuration. Q1 ("does the hook beat a written instruction?") then becomes silently unaskable and
# the two baselines are merely replicates of each other — which is exactly what the first n=2 and n=4
# passes measured without noticing. The .claude/settings*.json this also writes is hidden in EVERY arm
# by the harness, so the `with` arm's hooks still come only from --settings.
"$YIGRAF_PY" -m yigraf install "$DEST" --host claude >/dev/null

# ...and mirror the block into CLAUDE.md, because AGENTS.md ALONE DOES NOT REACH THE AGENT. Verified
# live against this Claude Code build: with only AGENTS.md present, `claude -p` answers "no project
# instruction files are loaded in my context" and the ambient arm never reaches for yigraf — the
# affordance sits on disk unread, so `ambient` silently stays a copy of `off`. CLAUDE.md *is* auto-loaded
# (verified: the agent quotes the block back), which is what makes `ambient` a real pull arm and Q1 a
# real question. The harness already hides CLAUDE.md for the `off` arm.
# (Same reason the .claude/skills/yigraf skill can't carry this: headless `claude -p` does not register
# project skills at all — the init event's `skills` list is identical in every arm.)
cp "$DEST/AGENTS.md" "$DEST/CLAUDE.md"

git -C "$DEST" add -A
git -C "$DEST" -c user.email=eval@yigraf -c user.name=yigraf-eval commit -qm "yigraf workspace for benchmark"

cat <<EOF

Workspace ready at $DEST

Run the battery (note the ABSOLUTE --hook-cmd — the default 'uv run yigraf' resolves inside the
clone's own uv project, where yigraf is absent, so the hook fails and the 'with' arm silently
degrades into a copy of 'ambient'):

  uv run python scripts/eval/run_ab.py --repo "$DEST" \\
      --cases scripts/eval/cases-httpx.yaml --runs 2 --isolate \\
      --hook-cmd "$YIGRAF_PY -m yigraf"
EOF
