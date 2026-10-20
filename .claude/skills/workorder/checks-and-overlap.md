# /workorder: spend each check once, and overlap what does not wait

Read this when several changes are ready at once, when a review runs as its own pass, when main moved, or before asking the owner anything. It is part of `SKILL.md`; the rules that apply to every launch are summarised there.

The owner, 2026-09-26: *"If some checks can be done once for 2 things it's
better than checking twice after each change"*, and *"Waiting for something
to end completely before picking it up sounds like a waste of time."* In the
ForgePact UI redesign (14 workorders over about 48 hours) a full panel verify
cost 25-35 minutes and was paid at least 15 times. The evidence is in
[`workorder-calibration.md`](../../../docs/agents/workorder-calibration.md#spending-each-check-once-the-forgepact-ui-redesign-2026-09-26).
Independence stays as it is: the verifier and every reviewer still run fresh
and never see the implementer's reasoning. A check is **shared** between
changes, never skipped.

**1. One round and one verify for everything that is ready together.**
Pending changes that are ready at the same time go into one implementer
round and one full verify: owner feedback, the findings a review produced,
a conflict-free main merge that touches none of the plan's files. Do not give
each its own implement-and-verify round. The patch route (Step 4) and the
3-round cap are unchanged; this is about not starting a second round while
the first one's input is still arriving.

The same goes for one verify's criteria: a check two criteria would both run
is run by one of them. ForgePact's Python suite re-runs the panel's browser
suites, so a plan whose criteria run those suites directly runs its full
Python suite with `--exclude-module` for the modules that wrap them
(`planner.md` § "Spend each check once", "Run each suite once per verify").

**2. Start independent work as soon as its input is committed.** A read-only
agent (`impeccable-finish-reviewer`, a design audit), a documenter writing
only to a scratch path, or a Figma mirror does not wait behind the verifier.
Launch it in the same message as the workflow or the verify, as a background
`Agent` call, pointed at the commit it reads. Work that edits files runs
alongside only when its files are disjoint from everything else in flight.

**3. Stream review findings into fixes.** When a review is its own pass
(a finish review, a design audit, owner feedback worked through by agents),
do not wait for the whole review before fixing:

- **Pin what the reviewer reads.** Fixers will be changing the tree, so the
  reviewer reads a snapshot of one commit: `git worktree add --detach
  <scratch>/review-<sha> <sha>`, or `git archive <sha> | tar -x -C <dir>`,
  with the scratch path outside every repository tree. Remove the worktree
  afterwards.
- **Split the review, run the parts at once.** Several narrower reviewers,
  one per dimension or per screen, in parallel, instead of one broad
  reviewer. Each one appends every finding to its own file in one scratch
  directory the moment it has it, as one JSON line: `{"id", "severity",
  "files": [...], "where", "problem", "fix"}`. A reviewer whose contract says
  it edits nothing writes only there, outside the repository trees; that is
  its report, not an edit.
- **Watch and dispatch.** The driver watches that directory with `Monitor`
  and hands each new finding to a fixer (`implementer`, the finding as its
  whole brief) at once. Fixers run one at a time, or in parallel only when
  their `files` are disjoint from every fixer in flight; a file several
  findings share (`app.css` and the like) serialises them. A fixer runs no
  git write while another fixer is in flight; when one finishes with none
  other running, it commits each finished finding's files as its own commit
  (`git add -- <files>`), the way a lane join does. A finding that needs a
  decision goes into the owner batch (5), never to a fixer.
- **Verify once, after the stream drains.** A fixer runs at most a test
  inside its own files. When every reviewer has returned and every fixer is
  done, one full verify (plus the reviewers that raised blocking findings,
  re-reading the fixed commit) covers every fix together, per rule 1.

A plan of items (Step 2, "Items") gets this from `workorder-rounds.js`
itself: reviewers read pinned commits, each finished reviewer's findings go
to a fixer at once, and one gate runs after the queue drains. The streaming
is per reviewer, not per finding, because `agent()` returns only when an
agent ends, so split a big review into narrower reviewers (`reviewScopes`)
to get findings sooner. The gate reads a tree nobody is editing, because it
runs only when no implementer is left. A plan with no items still runs in
rounds, where no fixer may touch the tree the round's verifier is reading;
for it, and for a review that is not a workorder's own reviewer pass, this
driver procedure is the way to stream.

**4. Main moved: merge it when it is clean and misses the plan's files.** A
plan's precondition is "main moved → merge it when `git merge-tree
--write-tree HEAD origin/main` shows no conflict and `git diff --name-only
HEAD...origin/main` names none of the plan's files; stop only otherwise"
(`planner.md`). The implementer does that merge and records it in `## Log`.
A separate main-merge workorder cost 1-2.5 hours each time in the redesign.

**5. Batch the owner's decisions.** After a round that changed what the owner
sees, serve a snapshot for them to look at, and collect every question the
next plan needs into one `AskUserQuestion` batch before that plan is
written, so the answers are plan inputs rather than mid-round replans. The
snapshot is built from `git archive <sha>` into a scratch directory, never
the working tree, and served through the module's own sandbox server with
its stdin held open (for example `tail -f /dev/null | <serve command>`, run
in the background), so the server does not exit when its input closes.

**6. A flaky test is fixed the round it is seen.** A test that fails once
without a code cause (a port the browser refuses, a timing race) is a defect
for this round's implementer, or a split right away; it is never re-run in
the hope of a green. The redesign's polish workorder spent its cap on a
Chromium `ERR_UNSAFE_PORT` flake.

**7. During development run the relevant subset; the full set runs once,
before the pull request.** A first verify and the items gate run `--dev`, a
fix round after a verify that passed every other criterion runs the
criteria the fix reaches plus the failed ones (`run_criteria.py
--changed-since`), and both defer the whole suites and `(final)` criteria.
In a deferred suite's place each runs that suite's contract tests
(`unittest discover -s <dir> -p "test_*contract*.py"`, when the directory
has any), numbered after the plan's criteria as a development companion:
in the first week after #485, 11 of 20 final gates failed, most on a whole
suite first run there, and ForgePact's 59 contract files take 44 s. The
full set runs once at the final gate before the push (Step 5). The
conditions and fallbacks are in `SKILL.md` Step 3 and [`verify-mechanics.md`](verify-mechanics.md), "Re-verify what the fix
reaches".

**7b. After a write, read the diff, not the file.** The owner, 2026-10-02:
after each write, agents *"spend lots of times on reads ... make sure only
difference or relevant things are read after every write instead"*. An agent
checks its own edit with `git diff -- <path>`, a grep or a ranged read, and
every agent downstream of a write reads the diff since its base: reviewers
already get `git diff <base> -- <paths>`, a re-entered implementer gets the
failed criteria, the evidence and `git diff <base> -- <path>` for what
earlier rounds changed, a replanning planner reads the Log since its last
plan and the sections the defect names, and State and the Log are written by
`tools/workorder_record.py`, which reads no agent's context at all (until
2026-10-11 a scribe agent wrote them). Measured over the 14 days before: scribes read
both workorder files whole every round (about 13 MB over 228 runs), and
fix-round implementers averaged 22 reads and 134 KB each, 105 of them the
whole plan. `tools/workorder_audit.py` R26 fails an implementer or planner
that reads a file it wrote whole more than twice.

**8. A question never idles the pipeline.** In the ForgePact UI redesign 19
of 60.75 hours passed with a question open and nothing running; the four
longest waits were 380, 273, 256 and 111 minutes, mostly overnight. Two of
those questions did not need the owner at all. So, before you ask:

- **Start everything the answer cannot change**, in the same message as the
  question: the other items or findings, a record round, the final gate on
  what is already settled, the next plan when its decisions are made. The
  answer then lands on finished work, not on an idle queue.
- **An out-of-scope bug is a spin-off, not a question.** Flag it as a
  separate task (the app's spawn-task chip, or a one-line note in the
  report) and carry on; the redesign waited 256 minutes on a port-fallback
  bug that was spun off anyway.
- **A reversible choice gets its default, not a wait.** A P2 or nit, or a
  choice where one option is plainly the plan's: apply it, say so in one line
  with how to undo it, and let the owner overrule it. The redesign's longest
  wait, 380 minutes, was a P2 icon question asked before the push.
- **Only a decision that changes what gets built, and cannot be undone
  cheaply, stops the work it gates** — and only that work, as an item's
  `owner:` line parks only its item.
- **Every owner question in a plan carries `default:` and `reversible:
  yes|no`**, an item's `owner:` and each `## Needs human judgement` entry
  alike, and `plan_lint.py` refuses one without them (`owner-no-default`,
  `owner-no-reversible`, `owner-reversible-no-default`). A legal or
  decompile-output question is `reversible: no` with a default of `none`
  (`owner-legal-default`). So is a wait on a live capture or on data that does
  not exist yet: the bug batch's three `owner:` items were of that kind. A
  reversible one runs on its default inside the launch and comes back under
  `defaulted`, with how to undo it; tell the owner in one line and move on.
- **Route `unblocked` before you ask.** A result that waits on a person lists
  under `unblocked` the parked work that does not wait on them, each with its
  route. Start those routes in the same message as the question.
- **Start what an `ASK` answer cannot change before relaying it.** A
  `live-operator`'s `NEEDS-HUMAN` or a phase's question for the person goes
  out with the independent work already started, not ahead of it. In the
  bug batch the owner answered a question the driver asked while a launch
  ran with *"Don't ask me, you can reserve live spot for hs drive mcp"*.

**9. Review the design before building it, not at ship.** For a chain of
UI workorders:

- Run the design tools on the direction comps before anything is bundled or
  downloaded: the impeccable detector (its overused-font check included) and
  a critique. The redesign bundled Geist, then the owner moved to IBM Plex,
  costing three replans across prep, buildout and restyle.
- Run `impeccable-finish-reviewer` after the first restyle round, not after
  the last workorder: the redesign's eight finish findings (F1-F8) arrived
  in ship and reopened a component choice already built.
- A design export gets a structure check against the current panel when it
  is made (its texts present in the page, its selectors inside the component
  they name, no runtime values such as a version baked in), not at restyle,
  where seven mismatches cost two restyle rounds and two Figma rounds.
- A design finding names its class and checks the class ("every text glyph
  on every tab"), not only the instances listed: PR #100's review found an
  icon the F6 fix had missed.
