# `.claude/` — the automated half of `AGENTS.md`

`AGENTS.md` holds this repository's rules in prose. This directory holds the
subset that a machine can enforce or execute, so they stop depending on whether
an agent happened to read the right section of a long file first. `AGENTS.md`
itself states each rule plus one sentence of why; the dated incident or review
finding that made a rule worth writing lives in `docs/agents/<section>.md`,
linked from the rule, so it stops being loaded into every subagent's context
on every turn.

Everything here is committed on purpose. Only `settings.local.json`
(per-machine overrides) is gitignored.

## Hooks — `settings.json` + `hooks/`

`settings.json` fires one `PostToolUse` command per call,
`.claude/hooks/post_tool_use.py`, which runs the four checks below in-process
against one shared `git status` (`_common.TreeState`, its explicit injection
point) instead of launching a separate `py -3`, and its own `git status`, per
check. Each check keeps its own `check(payload, tree) -> (rc, message)`
body and its own standalone `main()`, so `py -3
.claude/hooks/decompiled_output.py` still behaves exactly as it did before the
dispatcher existed; `tests/test_claude_hooks.py`'s `TestDispatcherEquivalence`
proves the two paths agree. A crash in one check is caught and reported as its
own non-blocking line rather than masking, or blocking for, the others. Every
check exits 0 silently when nothing is wrong and 2 with an explanation when
something is. They all run through `py -3`; on a non-Windows machine change
that to `python3` in `settings.json`.

| Check | Fires when | Catches |
|---|---|---|
| `catalog_signature.py` | `catalog/` differs from HEAD | `catalog/catalog.json` no longer verifying against its minisign signature, with CRLF called out by name when that is the cause |
| `tauri_command_guard.py` | a `.rs` under `hub/src-tauri/src/` differs from HEAD | `block_on` inside a `#[tauri::command]`, and `#[tauri::command(async)]` on an `async fn` |
| `hub_frontend_tests.py` | a top-level `hub/src/*.js` differs from HEAD | the hub's frontend tests failing |
| `decompiled_output.py` | any changed text file, in the hub **or in a dirty submodule** | Ghidra/IDA symbols, GameMaker VM pseudo-variables, GML positional arguments and bytecode mnemonics reaching a tracked file |

`leftover_processes.py` stays its own process at `PreToolUse` and `Stop` —
different in shape from the four above, as before — but its `post` half now
runs *inside* the dispatcher (imported lazily, so an Edit/Write call that
never needs it skips the load) instead of as a fifth hook entry, and runs
first, before the dispatcher spawns any git child of its own, since its
snapshot is time-sensitive. See "a per-call ledger" below.

**Adding a check now:** give it a `check(payload, tree: TreeState) -> (rc,
message)` function, add its module name to `post_tool_use.py`'s
`TREE_CHECKS` tuple, keep a standalone `main()` for its own CLI, and add a
positive/negative pair to both the check's own test class and
`TestDispatcherEquivalence` in `tests/test_claude_hooks.py`.

**The first four key off the working tree, not the tool payload**, and that is the
single most important thing to preserve when editing them. A payload-shaped
hook only sees `Edit` and `Write`, and only when it can resolve
`tool_input.file_path` against the repository root. Both halves leak: a `sed -i`
or heredoc under `Bash` never produces a `file_path`, and a path the hook cannot
resolve returns "not my file" — which is indistinguishable from "nothing
wrong". That is not theoretical. During development all three exited 0 against
a harness feeding them POSIX-style paths Windows Python could not resolve, and
looked installed and healthy while guarding nothing. `git status --porcelain`
costs ~40 ms and has neither hole. `.claude/hooks/_common.py` holds the shared
parts.

**Escape hatch: `HSTK_SKIP_HOOKS=1`.** Every blocking message names it. There
are legitimate states these would otherwise wedge — most clearly a catalog
rebuilt *unsigned* on a machine without `$HUB_MINISIGN_SECRET_KEY`, which
`skills/catalog-rebuild/SKILL.md` explicitly contemplates. Because the trigger
is the working tree, that state would otherwise fail *every* later tool call,
including the ones needed to finish or undo the work. A blocking hook with no
way out is worse than no hook.

Why these four and not others: each one guards a failure that has already
shipped, and each is cheap. The catalog check is a signature verification; the
command guard is a parse; the frontend tests are, in `hub/scripts/test.mjs`'s
own words, "a second of Node against a twelve-minute Windows build". **Nothing
here ever invokes `cargo`** — that is the twelve-minute path and it belongs in
`npm run check`, not in a hook that fires on every edit.

`decompiled_output.py` is the exception to "already shipped", and deliberately
so: the failure it guards is not a bug a later release fixes.
`ForgePact/CREDITS.md` claims AGPL-3.0 original work, and that claim holds only
while no game source text has reached any remote here — every submodule's own
origin included. `.gitignore` already excludes decompiler *artifact paths*
(`*.i64`, `*.gpr`, `ghidra_projects/`); this covers the likelier accident, a
listing pasted into a tracked `.md` or `.cpp` while writing up a finding. It is
the only hook that scans inside submodules, because the hub's `git status`
reports a dirty submodule as one changed pointer and `ForgePact/docs/` is where
research notes land.

It deliberately does **not** match `gml_Script_*` names or asset indices.
`AGENTS.md` names those as interoperability facts that are fine to commit — they
are what `hs-game-sdk` is for — so matching them would flag the SDK's own tables
and teach everyone to set `HSTK_SKIP_HOOKS`.

The catalog hook keys off the working tree rather than off which tool ran,
because a catalog can be rewritten by `Edit`, by a build script under `Bash`, or
by a rebuild this session never saw the path of.

### `leftover_processes.py` — a per-call ledger, not a descendant walk

Unlike the tree checks above, this one keys off the **live process table**,
not the working tree, because what it is guarding against — a `cargo` build
or a detached `npm` script still running after the reply ends — never touches
a file. `pre` runs as its own process, snapshotting every live process before
a `Bash`/`PowerShell`/`Monitor` call; `post` now runs inside
`post_tool_use.py` rather than as its own process, admitting whatever that
call can be blamed for into a per-session ledger file; `Stop` — still its own
process, once per reply — reports whichever ledger entries are still alive
and have not been reported before. A process is identified by `(pid, creation
time)`, never PID alone, because Windows reuses PIDs quickly.

Three simpler designs were rejected, and are worth recording so nobody
re-proposes them:

- **Walking every live descendant of the session's `claude.exe` at `Stop`.**
  This session's own MCP servers are exactly such descendants, and without
  command lines the only way to tell them apart from something like a
  `tauri-mcp driver-session` (which should be reported) is name matching on
  "mcp" — which the driver-session's own name defeats. It also cannot see a
  `Start-Process`-style detached child whose launcher has already exited,
  since no descendant walk from a living ancestor reaches it.
- **Attributing every orphan (dead parent) created since the session
  started.** Multiple sessions run at once on this machine, and timing alone
  cannot tell one session's orphan from another's — reporting a process a
  different session started is exactly what this hook must never do.
- **Reading another process's environment for a session marker.** That means
  `ReadProcessMemory` against a PEB layout this hook does not own, for a
  reporting tool that does not need it.

`stop_hook_active` is the loop guard: a hook that blocks Stop again while
`stop_hook_active` is true never lets the reply end. Every leftover is
reported at most once per ledger, in a `reported.json` next to it, so a dev
server the user asked to keep running does not re-block every later reply —
`AGENTS.md`'s "verify with a command" covers a process Claude claimed to kill
but did not.

Two environment variables, both documented in the hook's own docstring:
`HSTK_PROC_LEDGER_DIR` (default `%TEMP%/hstk-leftover-processes`, deliberately
never inside the repository, since `decompiled_output.py` scans every
untracked file and a ledger under the worktree would dirty `git status` on
every tool call) and `HSTK_PROC_SESSION_ROOT_PID` (overrides the nearest
`claude.exe` ancestor lookup; exists for tests).

**It never kills anything.** No `TerminateProcess`, no `kill`, no `taskkill`
run by the hook itself — it only prints what it found and suggests the command
a human or the reply should run.

**Known limitation, not observed to have happened yet:** if a whole parent
chain back to a ledger entry dies between two observations — `cargo` exits
while the `hub.exe` it started survives, with neither `post` nor `stop` having
run in between — the survivor cannot be attributed and will not be reported.
`AGENTS.md`'s "check with a command" is the backstop for exactly this gap.

**Known limitation, not observed (R1-A):** rule (b) (orphan admission) is
narrowed to `DETACHED_ORPHAN_IMAGES`, so a detached dev tool outside that
allowlist — an unusual build helper, say — is still missed by rule (b),
silently, the same as any other process that rule was never going to
attribute in the first place. See "Live checks" below for the incident that
motivated the narrowing. One allowlisted process is expected to show up: `git
fsmonitor--daemon run --detach` (seen 2026-09-16), which git starts detached
when `core.fsmonitor` is on. It is a shared, long-lived watcher that git
restarts on demand, so say so rather than treating it as a leak.

**Round 2 (2026-09-16), four small fixes on top of round 1:** rule (b)'s image
check now accepts every Python interpreter name the hook-invocation matcher
itself already recognises (`python[0-9.]*w?.exe`, plus `py.exe`/`pyw.exe`)
through one shared helper (`_is_python_interpreter_image`), not the three
literal names `DETACHED_ORPHAN_IMAGES` used to carry on its own, so a
versioned interpreter (`python3.exe`, `python3.14.exe`) is admitted the same
way `python.exe` always was (R2-1). `_load_snapshot_file`, `_load_pre_snapshot`
and `_read_reported_marker` now tolerate a hand-corrupted ledger or marker file
being the wrong shape throughout — a top-level list instead of a `{pid:
entry}` map, an entry that is not itself a dict, a missing or non-int `pid`/
`creation`/`ppid`, or a JSON `Infinity` that used to raise `OverflowError` out
of `int()` (including inside `_load_pre_snapshot`'s own `raw_pids` loop, not
only `reported.json`'s marker) — skipping what cannot be trusted instead of
crashing `post`/`stop` (R2-2). The CLI-level
`test_detached_orphan_with_dev_tool_image_is_admitted` duplicated
`test_orphan_started_during_call_is_reported` byte for byte and added no
coverage once R2-1 had its own unit-level pattern tests, so it was deleted
rather than kept as a second copy (R2-3).

**R2-4, fixed for real this round:** the first attempt at closing a PID-reuse
race in `_capture_new` — discard a captured command line whose `_creation_time`
no longer matched the pid's `new_procs` entry — left the discarded pid out of
`cmdlines` entirely. `_is_hook_chain`'s own `cmdlines and cur in cmdlines` check
then fell through to a fresh `_command_line(cur)` read for exactly that pid,
which is the recycled line the discard was meant to prevent from ever being
read at all — so R2-4 as shipped in round 2 did nothing. `_capture_new` now
reads a pid's creation time and command line through one handle
(`_process_identity`), and stores `None` — a real dict key, not a missing one —
for a pid whose creation no longer matches. `_is_hook_chain` treats membership
in `cmdlines` as authoritative even when the stored value is `None`, so the
recycled line is never re-read. Proven by
`test_hook_chain_does_not_reread_line_discarded_on_creation_mismatch`, which
fails against the pre-fix hook (one re-read, chain returns `True`) and passes
against this one (zero re-reads, chain returns `False`).

**Known limitation, not observed:** `_is_hook_chain`'s fallback
`_command_line(cur)` read — for a pid that is *not* a key in `cmdlines` at all
(an ancestor that predates the call, or any hop walked at Stop through
`_extend_ledger_with_live_descendants`, which passes no `cmdlines`) — is still
not tied to creation time the way `_process_identity`'s reads are. If a PID
were recycled into exactly a configured hook's command line there, a real
leftover could be hidden, which is the unsafe direction; this has not been
observed and would need a reuse into exactly a hook invocation's own command
line to happen.

Two more identity safeguards, each added after a live report misattributed
something and each proven by its own paired test in
`TestLeftoverProcessesAdmissionRules`:

- A PPID this hook cannot `OpenProcess` (a SYSTEM service, a protected
  process) is still counted as alive by consulting the raw, unfiltered
  Toolhelp32 PID list, not only the openable snapshot — otherwise an
  unopenable-but-live parent (`svchost.exe` under `dllhost.exe`/`audiodg.exe`)
  is indistinguishable from a dead one and its child looks like an orphan.
- Rule (c)'s "parent already has a ledger entry" check requires a *live*
  occupant of that PID to match the ledger entry's creation time exactly, not
  merely postdate it — `entry.creation <= proc.creation` is true for any later
  process once the ledger entry is dead, reused PID or not.

#### The structural hook matcher (F1)

A concurrent sibling `PostToolUse` hook spawns its own `bash -> bash -> py ->
python` chain during a call's window, which reaches the session root through
processes otherwise indistinguishable from a real leftover. Excluding it needs
to tell "this hop is actually running one of this repo's `.claude/hooks/*`
scripts" apart from "this hop's command line merely mentions one" — a
distinction two earlier versions of this check got wrong. The first matched
any command line containing the substring `.claude/hooks/` anywhere, which
also matched a Bash tool call that merely *talked about* that path and hid its
own `py`/`python` and every wrapping shell from the ledger (live A/B
confirmed). A second version narrowed the substring to the unexpanded
`$CLAUDE_PROJECT_DIR/.claude/hooks/...` fragment plus its two expanded
slash-style spellings — still a substring search. Calling that matcher's own
function directly against the three spellings (R1-B item 3: not itself a live
A/B — no real process tree was involved, just the pure function) found it
still hid all three whenever `CLAUDE_PROJECT_DIR` happened to be in
forward-slash form, because the fragment itself is a substring of a mention
that never invokes anything. The *replacement* matcher below was the one
actually put through a live A/B, against real hook processes — see the citation
after "This depends on two facts" below.

The replacement parses each hop's command line the way the OS itself split
it — `CommandLineToArgvW` via `ctypes` — and asks a narrower, shape-specific
question instead of a substring search:

- A shell hop (`bash.exe`/`sh.exe`): its `-c` argument, once parsed, equals
  one of the `command` strings configured in `.claude/settings.json` **or**
  `.claude/settings.local.json`, exactly.
- A `py`/`python` hop — any image `_is_python_interpreter_image` recognises
  (`py.exe`/`pyw.exe`, the two launchers, or `python[0-9.]*w?.exe`, an
  interpreter itself): its first non-flag argument — after the version
  selector, such as `-3`, only when the launcher itself (`py.exe`/`pyw.exe`)
  carries one, never on a bare `python*.exe` interpreter where `-3` is an
  option instead — is, once normalised (quotes stripped, backslashes to
  forward slashes, `posixpath.normpath`, lower case), one of the script paths
  those same `command` strings invoke. `-c`, `-m`, or any other leading
  interpreter flag is deliberately never a match — an unusual flag makes the
  hook over-report a real leftover, the safe direction, rather than hide one.

This depends on two facts a 45 s read-only poll of two live sessions measured
directly (2026-09-16): every configured hook ran as a four-hop
`bash -> bash -> py -> python` chain, both bash hops' `-c` argument was the
configured `command` string verbatim (checked against `CommandLineToArgvW`'s
own parse), and the `py`/`python` hops showed the expanded path with forward
slashes — the spelling of `CLAUDE_PROJECT_DIR` itself is never assumed,
only normalised before comparing. Only `.claude/settings.json` and
`.claude/settings.local.json` are read; a user-level (`~/.claude/settings.json`)
or plugin-provided hook is not, which stays in the over-report direction (its
chain is never excluded, so it can only be reported as a leftover it is not,
never hidden). `_configured_hooks` never raises on an unreadable file or an
oddly shaped `hooks` block — see "Fail-open" below.

**Live A/B (round-0 reviewer, 2026-09-16 ~15:03):** the replacement matcher
above was checked against a real, running session — 166/166 of that session's
own real hook processes matched, and 0/8 deliberately non-hook probe processes
did, where the substring-based matcher it replaced hid all 8 of those probes.
This is the citation R1-B item 3 asked to add here, in place of calling the
earlier paragraph's direct function call against three spellings a "live A/B"
— it never ran against a real process tree.

**F2 — capturing before anything slow.** `cmd_post`'s admission walk used to
run after `_load_ledger` parsed every `post-*.json` in the session directory —
hundreds of files, tens of milliseconds each — by which point a short-lived
sibling hook hop had often already exited, so its command line read back
`None` and the structural matcher above had nothing to match against. Measured
before the fix (2026-09-16, 357 files, 4,089 entries): a mean of 10.7 ledger
entries per call, almost all sibling `bash.exe`/`py.exe`/`python.exe`/`git.exe`
hops that had already exited by the time they were checked. The fix captures
each new pid's command line and liveness (`_capture_new`) immediately after
diffing against `pre`, before the ledger load or any admission rule runs, and
the captured line is what `_is_hook_chain` checks first (R1-B item 1: kept for
a since-exited hop too, whenever the line itself was readable, not only for a
hop still alive at capture time — the docstring said this from the start, the
code did not until R1-B).

Growth has not been observed after the fix, in two separate live measurements
(2026-09-16): a mean of 0.059 entries per file at 14:47 (34 files, 12+ separate
`Bash` calls after the final edit) and a mean of 0.353 across 99 files at
round-0 verification. Attributed to the liveness filter plus this early
capture together, not proven as a controlled before/after of one change in
isolation — see the recorded runs under "Live checks" below.

#### Fail-open, and what a session cannot see (F3/F4)

Both of the notes below go through `systemMessage` on stdout — the one channel
[the hooks docs](https://code.claude.com/docs/en/hooks) (fetched 2026-09-16)
say is shown to the user and that `Stop` does not discard — alongside the same
text on stderr. Plain stderr at exit 0 goes to Claude Code's debug log only,
never the transcript, so the hook's previous no-root stderr note was invisible
on every path that did not also report a leftover, which is most of them.

- **`no hook commands found in .claude/settings.json or
  .claude/settings.local.json`**: `_configured_hooks` found nothing to match
  against — the matcher above then cannot recognise any sibling hook chain, so
  leftovers may be over-reported. Shown **once per session**, not on every
  reply while the configuration stays broken (the user's own call), tracked in
  its own `hookwarn-reported.json` next to `reported.json`.
- **`found no claude.exe ancestor`**: at `stop`, this is
  `no claude.exe ancestor at Stop; not tracking this session`, said directly
  every time that lookup fails. At `post`, the call records nothing but leaves
  a `noroot-<tool_use_id>.json` marker; a later `stop` whose own lookup does
  succeed counts those markers and reports `N PostToolUse call(s) found no
  claude.exe ancestor and recorded nothing` once per newly blind call, in
  `noroot-reported.json` — the same report-once shape `reported.json` already
  uses for a leftover process.

#### The liveness gate's proof (F5)

`stop`'s liveness check trusts `GetExitCodeProcess` (`STILL_ACTIVE`) over
Toolhelp32 membership alone, since a just-terminated PID can still appear in a
snapshot for a brief window after it exits. This was previously unconfirmed,
not because the gate was wrong but because the CLI-level flaky test that
motivated it kept passing in local runs even with the gate removed —
Toolhelp32Snapshot does not list an exited process on demand in that test's
own timing, so it could not exercise the stale case either way, and a result
like that has to be written down as "not observed", never as "proven".
`TestLeftoverProcessesStaleToolhelp` proves it instead at unit level: a
fabricated ledger entry plus a stubbed `snapshot()`/`_command_line` that still
"sees" the pid, with `_is_still_active` stubbed both ways. Removing the gate
(`sed 's/if not _is_still_active(pid):/if False:/'`, run against an
`HSTK_HOOK_UNDER_TEST_DIR` copy so the live hook is
never touched) turns that test's pass into `FAILED (failures=1)`.

#### A/B without touching the live hook

Auto mode denies overwriting the live hook, and editing it mid-session changes
every hook call for the rest of that session. `HSTK_HOOK_UNDER_TEST_DIR` is
the accepted way around both: when set, `HookRig` and `_load_hook_module` in
`tests/test_claude_hooks.py` load hook scripts from that directory instead of
the repository's `.claude/hooks/` (`settings.json` is still always copied from
the repository, since F1 compares against it byte for byte). This is how F1's
negatives are proven to fail against the pre-fix hook (`git show <rev>:...`
into a scratch directory) and how F5's gate is proven to fail against a
mutant, without ever writing to `.claude/hooks/leftover_processes.py` itself
mid-session.

### Live checks

**Live positive control — run this by hand in a real session; it cannot be a
checkbox, because it needs a live session to end a reply:**

1. In a Bash tool call, run
   `powershell -NoProfile -Command "Start-Process py -ArgumentList '-3','-c','\"import time; time.sleep(600)\"'"`,
   which is detached and orphaned. The inner `\"...\"` is required: Windows
   PowerShell 5.1's `Start-Process` joins `-ArgumentList` with spaces without
   quoting, so an unquoted code string reaches Python as `-c import`, which
   exits at once with `SyntaxError`. Confirm the sleeper is alive, then let
   the reply end. Expect one Stop block naming `py.exe` and its `python.exe`
   child.
2. Kill that process, then send a trivial message. Expect no report.
3. Confirm no MCP `node.exe` and no process belonging to a second, separately
   open session was listed.
4. If step 1 shows nothing, look for a visible warning naming
   `no claude.exe ancestor at Stop` (F4's `systemMessage`, not a stderr-only
   note — see "Fail-open" above) before concluding there was no leak — that
   warning means the session-root lookup failed inside the hook, which is a
   defect in the lookup, not evidence nothing leaked.

Record the result here, with the date, next to the runs below.

**Recorded result (2026-09-16, one session):** step 1 blocked exactly once,
naming `py.exe` and its `python.exe` child and nothing else -- no MCP
`node.exe`. After `taskkill /T` the next two replies ended with no report.
The first attempt measured nothing: it hit exactly the unquoted-`-ArgumentList`
failure step 1 above warns about, so the sleeper never lived and the hook's
silence proved nothing until the code string was quoted and the sleeper's
liveness confirmed first. **Still not observed:** step 3, a second
concurrently open session's processes staying out of the report — do not
treat cross-session attribution as field proven until that is recorded here
with its date.

**Recorded result (2026-09-16 13:28, second run, separate session):** step 1
blocked exactly once, naming only `py.exe` 658720 and its `python.exe` 658676
-- no MCP `node.exe`, and nothing from the "forgepact-ci-build" session, which
had its last activity at 13:31 and was running builds and an implementer
subagent around that time. The detached sleeper was attributed even though
`Start-Process` orphaned it. The sleeper was deliberately left alive, and the
next reply ended with no report, which confirms report-once. Step 2's
"killed, then silent" variant was not repeated in this run. This is a positive
cross-session observation but a weak one: it was not confirmed that the other
session started a process inside the sleeper's exact call window.

**Live negative control, 2026-09-16 10:51 and 11:00 (recorded, not yet
positive):** the hook went live in its own driver session as soon as
`settings.json` changed, ahead of any planned live check. The first Stop, with
several background agents running, blocked and reported 12 processes; 11 were
false positives -- the hook's own concurrent sibling `PostToolUse` hook chains
and their `conhost.exe`s, all dead by the time they were checked. A second
Stop reported 8 more: a still-running background verifier's own acceptance
run, correctly attributed but not actually left behind. Both runs are false
positives this hook must not repeat, not evidence the mechanism works; they
are the reason rules (a)-(c) now also exclude any chain running a
`.claude/hooks/*` script and any `conhost.exe` reached through the Stop-time
ledger extension, and why the report and `AGENTS.md`'s section both say a
background task of this session still working is a reason to leave a process,
not a leftover. The one plausible true positive that day, a `vctip.exe` from a
C++ build, could not be killed with `taskkill` under auto mode's workload
classifier -- see `AGENTS.md`'s section for what to do instead (tell the user,
name the PID).

**F2 measured live (2026-09-16, driver session, workorder round 0):** 12
separate `Bash` tool calls (`true`) after the final edit to the hook, then the
criterion's own measurement script against this session's ledger directory.
34 `post-toolu_*.json` files were written after that edit, mean 0.059 entries
per file -- against the pre-fix baseline of a mean of 10.7 entries per call
(357 files, 4,089 entries, same date). Round-0 verification re-measured the
same way against a larger sample and found a mean of 0.353 across 99 files --
still well under the 10.7 baseline, growth not observed after the change in
either run. This is attributed to `_capture_new` reading each new pid's
command line before `_load_ledger`/the admission walk, together with the
liveness filter it feeds; neither run isolates the two as a controlled
before/after of one change alone.

**R1-A (rule (b) narrowed to `DETACHED_ORPHAN_IMAGES`):** live, 2026-09-16
15:05, before this round's fix. A Stop in this hook's own driver session
reported two `DiscordSystemHelper.exe` PIDs (182872, 183060, started
15:04:14) as leftovers. `Discord.exe` (179524) had just (re)started at
15:04:08, and each helper's own parent was a short-lived launcher already
dead by the time it was checked -- so the helpers were orphans whose launcher
happened to be born and die inside this session's own tool-call window, and
rule (b) admitted them exactly as designed. This is the accepted "another
session's orphan, rarely" risk the rule's docstring already named, just from
an image nobody's tool calls start rather than another session's. The report
suggested `taskkill` against the user's own Discord; it was not run.
`DETACHED_ORPHAN_IMAGES` bounds rule (b) to images a session plausibly starts
itself, so this shape no longer reaches it -- see `_is_orphan_admissible`'s
docstring for the list and its limitation.

**F2 re-measured live (2026-09-16, round 1, after this round's `_capture_new`
and `_is_orphan_admissible` changes):** 13 separate `Bash` tool calls (`true`)
after the final edit to the hook this round, then the same measurement
script. 34 `post-toolu_*.json` files were written after that edit, mean 0.029
entries per file -- still well under the 10.7 baseline, growth still not
observed after round 1's changes.

**F2 re-measured live (2026-09-16, round 2, after the R2-1/R2-2/R2-4 fixes
above -- none of which touch `_capture_new`'s early-capture ordering, so this
is mainly a check that nothing in this round regressed it):** 12 separate
`Bash` tool calls (`true`) after the final edit to the hook this round, then
the same measurement script. 35 `post-toolu_*.json` files were written after
that edit, mean 0.057 entries per file -- still well under the 10.7 baseline,
growth still not observed after round 2's changes.

**Not yet re-run after this round's changes:** the live positive control
(steps 1-3 above), and a check that the `systemMessage` note from a blind
`Stop` actually shows in the desktop app.

## Agents — `agents/`

There are two kinds here, and the distinction is the whole design.

**Phase agents run in sequence**, each at its own model tier, and each hands the
next one a document rather than a conversation. They are driven by
`/workorder`, never spawned by hand.

| Agent | Model | Does |
|---|---|---|
| `planner` | opus | researches the change and writes `.claude/workorders/<slug>-plan.md`, whose acceptance criteria are commands and files, never prose |
| `implementer` | sonnet | executes the steps; returns `PLAN-DEFECT` with evidence rather than improvising around a plan that turns out to be wrong |
| `verifier` | haiku | runs the acceptance criteria and reports what they actually printed; read-only, and judges nothing it cannot execute |
| `consultant` | opus | answers **one** narrow question from a phase that hit a decision above its tier, then stops; never implements, plans or reviews |

Why these tiers: planning carries the most judgement that is written down
nowhere, so it gets the strongest model. Implementation is *not* the easy part —
a plan never fully survives contact, and a weak model follows a wrong plan off
the cliff instead of stopping — so it gets a capable one. Verification against
mechanical criteria is genuinely cheap, so it gets the cheapest. The verifier
never sees the implementer's reasoning, because sharing that context would mean
sharing its blind spots.

### Getting a harder model onto a harder problem

Three mechanisms, because they cover three different failures. A pipeline with
only the last one learns that a task was hard by failing at it twice.

**Triage, before anything is spawned.** `/workorder` matches the request against
a table of observable properties — does it introduce concurrency, does it have
to establish an unknown mechanism rather than verify a suspected one, does it
change how a hook attaches, does it change a contract three bindings must agree
on — and starts the planner and implementer a tier up when it matches. The
signals are deliberately *properties of the task*, never a model's own sense of
how confident it feels: a model that cannot solve something is also poorly
calibrated about whether it can, which makes self-reported confidence the least
reliable signal available. The driver states which row it matched, so the user
can correct it for free.

**Consultation, mid-phase.** A phase can return `ADVICE-NEEDED` with one narrow
question; the driver spawns `consultant` (opus, read-only, `fable` for the
hardest rows), then re-enters the phase with the answer appended to the
workorder's `## Log`. Same-phase, same-tier re-entry is a `SendMessage` to
that phase's own agent id (recorded in `## State` › `agents:` when it was
spawned) — the send is what actually keeps its context and progress, not a
claim the driver makes about it. A fresh spawn happens only when that is not
possible (the id does not resolve, or the agent has already been resumed
twice), and carries a `PROGRESS SO FAR` block instead. Either way, one hard
decision costs one short answer rather than re-running the whole phase at a
higher tier. An agent cannot spawn another agent, so this is a
return-and-redispatch through the driver rather than a call.

The guardrail is one required field: **`WHAT I WOULD DO WITHOUT HELP`**. The
consultant confirms or corrects a position, which is fast and precise, instead
of solving from nothing — which is just the expensive model doing the phase's
job one question at a time. A question without it is sent back. Cap is two per
round; a third means triage was wrong and the *phase* escalates instead, which
makes the frequency itself the signal rather than an open tab.

**Escalation, on repeated failure.** The planner moves to `fable` on a second
`PLAN-DEFECT` and stops on a third. This is the backstop for what the first two
missed, not the router. It works because planning is the cheapest phase by token
volume — a plan is a few thousand output tokens against an implementation's
hundred thousand — so one Fable replan costs less than the implement round it
saves.

The reviewers never escalate and never consult: they run at high volume on every
change, where 2× is real money for no measured gain. Neither does the verifier,
and that one is a design choice rather than economy — it is scoped to what it
can execute, and a route to a judgement call would reopen the door that scoping
closes. An uncertain verifier reports `UNATTEMPTED` and lets a human decide.

**These are tier aliases, not pinned version IDs**, and deliberately. The tier
is the design decision; the version is not. Pinning `claude-opus-5` across eight
files would buy reproducibility this pipeline does not need — the acceptance
criteria are mechanical, so a model change that breaks something fails a *test*,
not a review — at the cost of a stale-ID sweep every generation, ending in a
retired model that breaks the agent outright. This is not the `*Rva*` case
`AGENTS.md` forbids: an alias is a documented moving pointer, where a hardcoded
address is a constant whose meaning moved underneath it.

**Every agent here sets `model:` explicitly — none inherits.** That is the
difference between a tier being a design decision and a tier being an accident
of whatever the operator last picked in `/model`. `sdk-contract-reviewer` and
`tauri-command-reviewer` originally omitted the field, which silently meant
"whatever the session is": running the session on Haiku would have quietly
dropped four rediscoveries' worth of review to the cheapest tier while still
printing a clean report, and running it on Fable would have doubled the cost of
every SDK-touching change without anyone choosing that. Neither is visible in a
diff, which is what makes it the same failure shape as the rest of this file —
something that reports itself working while doing something other than what it
says.

So: set `model:` on every new agent. `inherit` is a valid value when following
the session is genuinely the intent — but say why in the agent's **body**, not
as a YAML comment beside the value. A trailing ` # because …` makes the field
read as `inherit # because …`, which is neither a known tier nor quoted, and
fails both `test_every_pinned_model_is_a_known_tier` and
`test_no_unquoted_hash_in_any_definition`. That is the same ` #` trap described
further down, arriving through the field this page is about.

The one thing that cannot be pinned is the **`/workorder` driver itself** — a
skill runs in the main session, at the session's model. That is why its routing
is written as an explicit table of verdicts and destinations rather than as
judgement: the loop has to be followable at any tier, because the tier is not
ours to choose. If you run the session on Haiku, the phases still run at their
own pinned tiers; only the routing between them gets cheaper.

Note one hard limit behind the tiers: Haiku 4.5 has a 200K context where the
others have 1M. It is comfortable for acceptance criteria plus a diff, which is
all the verifier is given, and that is part of why the verifier's job is scoped
to what it can execute rather than to reviewing the change.

**Domain reviewers run in parallel**, are read-only, and each covers one bug
class that has recurred here. Wall-clock is one agent; only tokens add up.

| Agent | Model | Reviews |
|---|---|---|
| `sdk-contract-reviewer` | sonnet | `hs-game-sdk/`, `tests/cpp/`, and anything reading runtime values: identity-by-positive-signal, instance-handle kind gates, cross-binding parity and test-stub fidelity |
| `tauri-command-reviewer` | sonnet | `hub/src-tauri/src/`: command threading annotations, `announce()` after state changes, independent failure paths, and the debug-only MCP bridge gate |
| `decompile-output-guard` | sonnet | whether a change carries the game's own expression rather than facts about it — the judgement half of `decompiled_output.py` |
| `docs-sync-reviewer` | sonnet | which `instructions.md`, README, index entry, ADR or `release-notes-vX.Y.Z.md` the change just made wrong |
| `instrument-blindness-reviewer` | opus | table-only hook installs, hand-resolved addresses, struct-layout assumptions, and negatives recorded without a positive control |

**Delta-scoped from round 1 on.** No reviewer is given the workorder path —
each dispatch pastes `## Goal`, `## Out of scope`, the diff commands, and the
paths this round touched, found with
`.claude/skills/workorder/round_delta.py` (`snapshot <slug> <round>` before
the round, `delta <slug> <round>` after; exit 3 means the snapshot is missing
or unreadable, and everything is treated as changed). Round 0 runs every
applicable reviewer against the whole change. Round ≥ 1 runs `verifier`
always, plus every reviewer that was `BLOCKING` last round or whose own
trigger paths (stated in that reviewer's file) appear in the delta; a
reviewer skipped this way is recorded as `clean@round<n>, not re-run`.
`decompile-output-guard` is the one exception to being skippable — a legal
finding is always blocking, so it re-reads every added line every round
regardless of the delta.

`sdk-contract-reviewer` covers four separate rediscoveries of one defect;
`tauri-command-reviewer` covers three shipped hangs; `instrument-blindness-reviewer`
covers 34 hooks reporting zero calls against a game that was calling them. Each
agent's file records the incidents, because the reason these are hard to catch in
ordinary review is that the code reads as correct.

`docs-sync-reviewer` is the one whose bug class has not shipped as a crash. It
exists because of 2026-09-14 — the incident `CLAUDE.md` was written to prevent,
where two fixes went up for review with no documentation updates. That rule is
still enforced by nobody else.

Hooks and agents overlap deliberately, twice. On `hub/src-tauri/` the hook takes
the two violations that are a grep and the agent takes the judgement call ("does
this synchronous command touch disk or the network?"). On decompiled output the
hook takes text that is unmistakably a listing and the agent takes the question
no pattern answers: has a paraphrase crossed from describing behaviour into
reproducing expression?

## Skills — `skills/`

| Skill | Invocation | Purpose |
|---|---|---|
| `catalog-rebuild` | user-only (`/catalog-rebuild`) | rebuild → sign → verify → test, with the signing-key and CRLF rules attached |
| `workorder` | user-only (`/workorder`) | drives plan → implement → verify across the phase agents, routing defects back to the phase that caused them |
| `submodule-context` | Claude-only | loads the right `docs/submodules/<name>/instructions.md` before work starts |

`catalog-rebuild` is user-only because it has side effects and needs a signing
key that is deliberately not in this repository. `workorder` is user-only
because it spawns at least three agents and is the wrong tool for a one-line
fix — the cost should be a deliberate choice, not something that fires on a
typo. `submodule-context` is Claude-only because it is background knowledge, not
an action anyone invokes.

`workorder` owns the loop the phase agents cannot run themselves: an agent
returns a verdict to whoever spawned it, so the routing — `PLAN-DEFECT` back to
the planner, `IMPL-DEFECT` back to the implementer — lives in the driver. Two
caps keep that loop from burning tokens on a problem it has lost: **2 replans**
and **3 implement→verify rounds**, then it stops and asks a human.

A workorder is two files: `.claude/workorders/<slug>-plan.md` (frontmatter,
`## State`, `## Goal`, `## Out of scope`, `## Acceptance criteria`,
`## Steps` — what everyone who touches the workorder reads) and
`<slug>-context.md` (`## Context the implementer needs` by stable `###`
subsection, `## Needs human judgement`, `## Log` — read by section, only when
a step or a reviewer is pointed at it). `## State` carries `round:`, `phase:`,
`gates:` (the tokens a conditional criterion or step names, instead of
"while the Log lacks X"), `round base:` (the `round_delta.py` snapshot for
this round), `agents:` (each phase's agent id, for the resume mechanism
above), `reviewers:`, `open defects:` and `decisions in force:`. The nine plans written before this
split stay valid — same sections, single-file — located with
`grep -n '^## \|^### '` rather than assumed; nothing routes on which shape it
finds. Both files, and the `.claude/workorders/.rounds/` round snapshots, are
gitignored at any depth, for the reason `AGENTS.md` § "Documentation &
Instructions Maintenance" gives: they are working notes for the run, and what
is still true once the work lands belongs in `docs/` instead.

Three rules exist because the first real run — the panel-and-launcher
performance pass — hit the cap with seven items open and had to be finished by
hand, outside the phase separation:

- **Only `BLOCKING` findings spend a round.** Every reviewer labels each finding
  `BLOCKING` or `NON-BLOCKING`. That run reached its cap on a round whose
  instrument reviewer opened with *"nothing here blocks shipping"* and then
  listed eight improvements — polish consumed the last round and stopped eight
  findings that were already green. Non-blocking findings ride along as context
  and surface in the final report.
- **At the cap, split rather than raise.** The recovery is a new workorder
  carrying only the still-open findings, with its own fresh three rounds. The
  cap means the pipeline lost the thread, and that does not become untrue
  because the plan is large; raising it buys more of what was not working.
- **Triage warns on size.** The caps are per *workorder*, so an oversized plan
  puts unrelated work on one shared budget. Above 30 criteria, 3 independent
  findings, or one submodule, the driver says so before spawning. That run was
  116 criteria, 9 findings, 2 submodules, 1,524 lines — no individual finding
  was too hard, there were simply too many sharing one budget.

It has three modes: `/workorder <task>` runs everything, `/workorder plan
<task>` stops after the plan, and `/workorder resume <slug>` picks up at
implementation — in a **different session**, which is the point. Splitting there
buys two things the in-pipeline phase boundaries do not: a human checkpoint
where a plan can be argued with before any code exists, and a real test of
whether the plan is self-sufficient, since a fresh session has none of the
conversation that produced it. Context isolation is *not* one of the benefits —
planner and implementer are already separate subagents with separate contexts
either way.

**A fourth mode, opt-in and unproven — say so when offering it:**
`/workorder resume <slug> workflow`, or the user saying "use a workflow," runs
the implement → verify → route rounds (steps 2–4) as
`.claude/workflows/workorder-rounds.js` instead of driver turns: a fresh
implementer each round, `verifier` plus the delta-scoped reviewers above, and
a haiku scribe that writes the Log and State entries, looping under the same
3-round cap. It returns to the driver on anything needing judgement — `PASS`,
`PASS-PENDING-HUMAN`, `PLAN-DEFECT`, `ADVICE-NEEDED`, a human-needed
`UNATTEMPTED`, or the cap — so replans, consultations, human questions and the
step-5 report stay with the driver either way. What it trades away: every
re-entry inside the script is a fresh spawn, never the `SendMessage` resume
above, because the script has no agent id to send to. What it buys is the
driver's own tool calls for those rounds, not spent —
`skills/workorder/SKILL.md` § "Driver discipline" records the measured cost of
a driver that does that work itself.
`.claude/workflows/workorder-rounds.test.mjs`
(`node --test`) dry-runs its routing against stub agents, unproven meaning it
has not yet carried one real workorder end to end.

That makes the split a forcing function rather than just a workflow: a plan that
cannot survive a fresh session was never a plan, it was a conversation someone
was still holding in their head. `resume` checks for exactly that before
spawning anything, and routes `PLAN-DEFECT` if a step says "as discussed" or
leans on a decision that was never written down.

Because the skill cannot invoke itself (`disable-model-invocation: true` — three
agent spawns is the wrong answer to a typo), `AGENTS.md` § "Offer `/workorder`
When the Work Has Shape" carries the trigger list that makes Claude *suggest*
it. Suggest, wait, and drop it if the answer is no.

## MCP servers — `../.mcp.json`

| Server | For |
|---|---|
| `tauri-hub` | driving a running debug hub through its bridge on `127.0.0.1:9223` |
| `context7` | live library documentation; `AGENTS.md` § "YYToolkit Integration" already assumes it |
| `github` | releases, dispatches and pointer PRs across the eleven repositories |

`tauri-hub` is pinned to `@hypothesi/tauri-mcp-server@0.13.0` to match
`tauri-plugin-mcp-bridge = "0.13"` in `hub/src-tauri/Cargo.toml`. Keep those two
in step: some tools (the desktop `manage_window` actions) return a version error
against an older plugin.

The bridge only exists in a **debug** build with the `mcp-bridge` feature — an
optional dependency registered under
`#[cfg(all(debug_assertions, feature = "mcp-bridge"))]`, because it can invoke
any command in the application. A bare `cargo run` or `tauri dev` does not start
it. Start the hub with `npm start` in `hub/` (which passes `--features mcp-bridge`) and wait for `:9223` before expecting
`tauri-hub` to connect. `AGENTS.md` § "Drive a Tauri App Yourself Instead of
Asking Someone to Click It" has the rest, including the window label (`hub`, not
the `main` every tool defaults to).

`github` does **not** authenticate interactively. Claude Code tries OAuth
dynamic client registration, that endpoint does not support it, and the session
reports *"Incompatible auth server: does not support dynamic client
registration"*. Probing directly confirms what it wants: a POST with a bearer
token returns 200, without one 401. So `.mcp.json` sends
`Bearer ${GITHUB_MCP_PAT}`, expanded from the environment — no token in the
repository.

Set it once, piping so the value is never displayed:

```powershell
[Environment]::SetEnvironmentVariable('GITHUB_MCP_PAT', (gh auth token), 'User')
```

**Claude Code must be restarted afterwards.** A process reads its environment at
launch, so the session that sets the variable is never the session that can use
it.

Three things worth knowing about that arrangement:

- **It is a copy, and copies go stale.** That is the `gh` CLI's own OAuth token.
  `gh auth refresh`, `gh auth logout` or a re-login rotates it, and this copy
  then 401s while `gh` itself keeps working — so the symptom is "the MCP server
  broke for no reason". Re-run the command above to resync.
- **It is plaintext at rest**, in the user's registry environment, readable by
  anything running as that user. `gh` keeps its own copy in the OS keyring, so
  this is a deliberate downgrade accepted for convenience.
- **It is broadly scoped**: gist, read:org, repo and workflow across *every*
  repository the account can reach, not just this one. A fine-grained PAT
  restricted to the `falorfrozen-cmd` repos narrows the blast radius
  considerably and drops into the same variable.

Until the variable is set the entry simply fails to connect, which is harmless —
the `gh` CLI covers the same ground and keeps its token in the keyring.

## A trap worth knowing: `#` in frontmatter

An agent or skill `description:` is a **plain YAML scalar**, so a space followed
by `#` opens a comment and everything after it is silently dropped — no error,
no warning, and the file still loads. `tauri-command-reviewer` shipped with
`adds or edits a #[tauri::command]` in its description and lost the last 86
characters, which were the trigger conditions that make the agent get picked at
all. It is now written as a **double-quoted scalar**, which is the right fix:
the attribute stays readable in the trigger text, and the quoting stops YAML
treating the `#` as a comment. Do the same for any `description:` containing
attribute syntax, a shell flag, or a URL with a fragment — quote the value
rather than rewording around the character, and never put authoring notes in
`description:` itself, since that text is what gets matched against.

To check a file: strip the frontmatter and look for an unquoted ` #` in it.

## Changing any of this

Four suites cover this directory. Three are Python and run automatically
under the first command below; the workflow script's own routing is
JavaScript and runs separately, under Node:

```bash
py -3 -m unittest discover -s tests
py -3 -m unittest tests.test_claude_hooks -v      # the hooks actually block
py -3 -m unittest tests.test_claude_agents -v     # the definitions are well-formed
py -3 -m unittest tests.test_claude_workorder -v  # round_delta.py sees only this round's changes
node --test .claude/workflows/workorder-rounds.test.mjs   # workflow mode's routing
```

`test_claude_agents.py` enforces the two rules on this page that a machine can
check: every agent pins `model:` to a known tier alias, and no frontmatter
carries an unquoted ` #` that would silently truncate the value. Both are
invisible in a diff and neither had a check before. It self-tests its own
parser, for the same reason everything else here does.

`test_claude_workorder.py` drives `round_delta.py` as the subprocess
`settings.json` and the driver actually invoke, not by importing its
functions — the same discipline `test_claude_hooks.py` uses for the hooks.

Every test there is a **pair**: a positive control proving the hook fires on a
real violation, and a negative control proving it stays quiet on a clean tree.
A suite with only the negative half passes against hooks that do nothing, which
is exactly the failure this project keeps rediscovering — see `AGENTS.md`
§ "Prove the Instrument Before Trusting a Negative Result". If you add a check,
add both halves.

The rig builds a throwaway git repository in the system temp directory rather
than the session scratchpad, where `git init` fails with `Filename too long`.
