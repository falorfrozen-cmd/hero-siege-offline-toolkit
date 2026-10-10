# /workorder: how a verify runs, and what a fix round re-verifies

Read this in driver mode, before you dispatch a verifier yourself, or when a verify's scope is in question. In workflow mode `workorder-rounds.js` hands each verifier this procedure and its scope. It is part of `SKILL.md` (Step 3 and Step 4).

## The criteria runner

**The verifier starts with `tools/run_criteria.py <plan> --jobs auto`.** The
script runs every command-shaped criterion in one call, exactly as written,
once per distinct command, and skips gated ones. With `--jobs` it runs
independent commands at the same time by resource class: builds first and
alone, then at most one whole suite, two browser suites and any number of
file checks side by side, while a timing benchmark (`e2e:perf`) and any
command it does not recognise run alone in their place in the plan. It
prints criteria in plan order with the serial run's `cmd-<n>.log` numbers,
each exit code with the tail of the command's output, and judges nothing, so
the verifier still decides every criterion and reads the prose ones.
Verifiers spent about a third of their time on model turns between commands,
so this cuts per-command turns and nothing the verifier observes. A root
suite a criterion already ran is not run a second time for step 3 of
`verifier.md`.

**A whole-tree run goes to the background** (the rounds verifier, the reach
re-verify, the items gate). The verifier starts `run_criteria.py <plan>
--jobs auto --out <its scratchpad>/criteria` with `run_in_background: true`,
so no Bash limit can kill it, then re-issues `py -3 tools/run_criteria.py
--status <out> --wait 220` at a Bash timeout of 300000 while it exits 3, and
once it exits 0 judges from `py -3 tools/run_criteria.py --digest <out>`,
not from `report.txt` whole. The runner keeps
`<out>/status.json` current (each criterion's state and each command's exit
code and seconds) and writes everything it prints to `report.txt`. The
digest prints an exit-only criterion whose commands all exited as expected
as one line, and every other criterion's block exactly as `report.txt` has
it; it judges nothing. The verifier opens `cmd-<n>.log`, or a ranged read of
`report.txt`, only for a one-line criterion whose expectation needs output.
After 2026-10-02 verifiers read `report.txt` whole, 100-217 KB a run, and it
was the one figure of theirs that rose (docs/agents/workorder-calibration.md,
2026-10-03). Exit 4
means the run went stale (not finished, and not updated for 1,900 s): the
verifier re-runs the criteria not yet done in the background, with
`--start`. Exit 2 means there is no status file. `--wait` can never exceed
220 s, so a poll stays under audit R5's 240-second limit. The verifier still
runs every command itself and never reads an out directory it did not
start. One item's checks (`--item`) stay in the foreground: none took more
than 1.0 minute in the bug batch, so a poll would only add turns.

## Re-verify what the fix reaches

**Re-verify what the fix reaches.** The owner, 2026-09-27, as a one-file
panel fix in the ForgePact UI redesign's ship workorder was about to pay
another full verify behind a ~20-minute Python suite: *"run relevant tests
only if possible"*. A fix round, patch or ordinary, that follows a verify
which passed every criterion but the failed ones re-verifies only the
criteria the fix can reach, plus the failed ones. A criterion the earlier
verify deferred to the final gate counts as a known standing here, not an
unknown one (2026-10-02), and the runner defers it again unless `--failed`
names it:

```bash
py -3 tools/run_criteria.py <plan> --jobs auto --changed-since <hub base> \
    --changed-since <submodule>=<its base> --failed <k,...> --out <scratch>/criteria
```

The bases are this round's, from `round_delta.py heads <slug> <round>`.
The runner selects each criterion whose `(reads ...)` (planner.md, "Spend
each check once") a changed path matches, each failed one, each one that
declares no `(reads ...)` and each one a selected criterion runs `(after
...)`, and prints what it selected and skipped and why, so the report
shows the scope. The verifier reports a skipped criterion as
`not-selected`, never `pass`, and skips its step-3 root suite unless a
selected criterion runs it. `workorder-rounds.js` hands a round's verifier
this command itself (2j) and records `verify scope:` in the Log. The full
set still runs:

- **at the final gate before a push**, once: a PASS reached through a
  scoped verify is `PASS (scoped)` in step 5 until a full verify covers
  it, in this workorder or in the feature's final one;
- **when the delta is unknown**: `round_delta.py` exited 3, the base heads
  are missing, or the runner itself prints `scope: full -- delta unknown`;
- **when the change touches a shared contract**: the runner falls back by
  itself for `hs-game-sdk/`, `third_party/yytoolkit/`, `.gitmodules` and
  its own selection code, and for any glob on the plan's `## State`
  `shared contract:` line;
- **when a criterion's standing is not known**: it was unattempted for any
  reason but an unset gate, or the last verify reported it without its
  plan number;
- **when the verifier cannot tell** from the printed scope whether the
  fix could reach a criterion the runner skipped. It then runs the full
  set and says why.

Independence is unchanged: the verifier is still fresh, never sees the
implementer's reasoning, and runs every criterion it reports. The re-check
is smaller, not shared. In the ship workorder, run by hand, it saved about
40 minutes per fix round (evidence in
[`workorder-calibration.md`](../../../docs/agents/workorder-calibration.md#re-verifying-only-what-a-fix-reaches-2026-09-27)).

