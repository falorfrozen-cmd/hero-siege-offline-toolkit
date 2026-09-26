export const meta = {
  name: 'workorder-rounds',
  description: 'Run one workorder\'s implement -> verify -> route rounds as code; hands back to the driver on anything that needs judgement',
  whenToUse: 'Opt-in from /workorder (workflow mode). Replaces the driver\'s own turns for steps 2-4; replans, consultations, human questions and the final report stay with the driver.',
  phases: [
    { title: 'Implement', detail: 'fresh implementer per round at the triaged tier; on a laned plan\'s first round, one implementer per lane in parallel, then the join; a patch round applies reviewer-stated fixes only; a plan of items streams: one implementer per item as its files free up, and a fixer per reviewer finding' },
    { title: 'Verify', detail: 'verifier + delta-scoped reviewers, in parallel; for items, a targeted check per item, reviewers on pinned commits as they land, and one whole-tree gate at the end' },
    { title: 'Record', detail: 'haiku scribe: round snapshot/delta, Log entry, State' },
  ],
}

// Contract: .claude/skills/workorder/SKILL.md, "Workflow mode". The reviewer
// trigger table below is that skill's round >= 1 table as code; change both
// together.
//
// args: {
//   slug, planPath, contextPath,        // contextPath === planPath for a legacy single-file plan
//   checkoutRoot,                       // this session's `git rev-parse --show-toplevel`; the scribe is handed
//                                       // planPath/contextPath joined under it (2g below). Required unless both are absolute.
//   goalExcerpt,                        // '## Goal' + '## Out of scope', pasted by the driver
//   implementerModel,                   // 'opus' (the default) | 'sonnet' | 'fable', from step 0.5 triage
//   round,                              // the round to start at (State's `round:`)
//   reviewers: { '<name>': 'never' | 'clean' | 'blocking' },   // applicable reviewers and their last verdict
//   submodules: ['ForgePact', ...],     // dirs whose own diff the reviewers must read, relative to repoRoot
//   researchHeadings,                   // '###' heading(s) in the context file recording a research finding, for instrument-blindness-reviewer
//   repoRoot,                           // still accepted, and nothing passes it: it re-points the git commands agents are
//                                       // handed, never where Edit lands, so it cannot make another checkout workable
//                                       // (SKILL.md Step 0.25)
//   baseHeads,                          // { '.': sha, 'ForgePact': sha, ... }, copied from '## State' > 'round base:'
//                                       // -- the WORKORDER's own starting heads, for a reviewer that has never run
//   priorFindings,                      // { '<name>': [{ where, problem }, ...] } for a reviewer entering as 'blocking',
//                                       // copied from the Log -- a fresh launch has no memory of what it found
//   state,                              // the '## State' section as `section.py <plan> 'State'` printed it, so the
//                                       // Record pass hands the scribe the whole block, every line it does not
//                                       // own (gates:, round base:, agents:, ...) already in it (2e below)
//   lanes,                              // [{ name, files: [...] }, ...] and
//   join,                               // true -- both pasted from `py -3 tools/plan_lint.py <plan> --lanes-json`,
//                                       // and only for a first implementation of the plan's steps (round 0, or the
//                                       // relaunch after a replan; never after an IMPL-DEFECT). Absent or [] runs
//                                       // exactly as a plan without lanes (2h below)
//   items,                              // [{ id, title, files, checks, after, shares, owner }, ...] pasted from
//                                       // `plan_lint.py <plan> --items-json`: the launch streams (3b below) instead
//                                       // of running rounds. Absent or [] runs in rounds exactly as before
//   streaming, answered,                // items mode: the planner is still releasing items; ids whose owner: question
//                                       // is answered under '### Decisions'
//   reviewScopes,                       // items mode: { '<reviewer>': [{ label, paths }] } splits a reviewer by scope
//   maxParallel, maxAgents,             // items mode budgets: implementers at once (4), agents per launch (120),
//   tokenCeiling, itemAttempts,         // output tokens per launch (none), implement attempts per item (3)
//   reviewPassCap                       // passes a reviewer makes before it waits for the final catch-up (4)
// }
//
// The count of patch rounds already spent (2i below) is read from `state`'s
// `patch rounds:` line, which this script writes; there is no separate arg.

const A = args || {}
const ROUND_CAP = 3
const SLUG = A.slug
const REPO_ROOT = A.repoRoot || ''
const SUBMODULES = A.submodules || []
// A submodule entry that is already absolute (drive letter, POSIX root, or
// UNC) is used as-is rather than joined under repoRoot, so a caller that
// already resolved one submodule's path does not get `C:/a/b/C:/c/d`.
const isAbsolutePath = p => /^([a-zA-Z]:[\\/]|[\\/]{1,2})/.test(p)
const underRoot = p => isAbsolutePath(p) ? p : `${REPO_ROOT.replace(/[\\/]+$/, '')}/${p.replace(/^[\\/]+/, '')}`
// `--root` and `-C` targets are double-quoted only in repoRoot mode -- the
// path may contain spaces (this machine's paths do), and quoting a value
// that is never used (repoRoot absent) would change today's exact strings.
const DELTA = `py -3 .claude/skills/workorder/round_delta.py`
const DELTA_ROOT_ARG = REPO_ROOT ? ` --root "${REPO_ROOT}"` : ''
const MODELS = { 'instrument-blindness-reviewer': 'opus' }

const isTest = p => /(^|\/)tests?\//.test(p) || /\.test\.[jt]sx?$/.test(p) || /(^|\/)test_[^/]+\.py$/.test(p)
const TRIGGERS = {
  'docs-sync-reviewer': d => d.paths.some(p => !isTest(p)),
  'decompile-output-guard': d => d.paths.some(p => /\.(md|cpp|hpp|py|rs|ts|js)$/.test(p)),
  'sdk-contract-reviewer': d => d.sdkContent || d.paths.some(p => /^hs-game-sdk\//.test(p) || /^tests\/cpp\//.test(p)),
  'tauri-command-reviewer': d => d.paths.some(p => /^hub\/src-tauri\/src\//.test(p) || /updater/i.test(p)),
  'instrument-blindness-reviewer': d => d.instrumentContent || d.paths.some(p =>
    /^ForgePact\/plugin\//.test(p) || /^hs-game-sdk\/.*(hook|install)/i.test(p) || /-research\.md$/.test(p) ||
    /^docs\/submodules\/[^/]+\/instructions\.md$/.test(p) || /(^|\/)docs\/.*\.md$/.test(p)),
}

// @scheduler-begin
// --- 3a: the items scheduler, as pure functions ------------------------------
//
// Items mode (3b below) runs a plan's `### Item:` groups as parallel
// implementers. Which item may start is decided here and nowhere else, from
// the item table and each item's status alone, so the policy is tested
// without spawning anything: workorder-rounds.test.mjs cuts this block out
// between the two @scheduler markers and calls it directly.
//
// Statuses: pending, running, done, parked (it stopped and needs someone --
// the owner, a consultant, a replan, or its budget ran out), held (it cannot
// start because something it depends on is parked). `touched` says whether
// an implementer ever worked on the item: an item parked before it started
// (an owner question) left its files alone, one parked mid-way may have left
// them half-edited.
//
// Two items may run at once only when their file sets are disjoint. Items
// sharing a file run one at a time in plan order, which is the per-file
// queue: an item waits while an earlier item on the same files is pending, or
// parked or held after touching them. `files: '*'` is a fix whose files are
// unknown (a finding without a path, a failed whole-tree criterion): it runs
// alone, after everything before it.
const SCHED_GLOB = /[*?[]/
const schedLiteralPrefix = g => { const i = g.search(SCHED_GLOB); return i < 0 ? g : g.slice(0, i) }
// fnmatch, as tools/plan_lint.py uses it: `*` crosses `/`.
const schedGlobRe = g => new RegExp('^' + g.replace(/[.+^${}()|\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.') + '$')
// Whether two declared paths can name the same file -- plan_lint's
// `_overlap`, conservative on purpose.
const pathsOverlap = (a, b) => {
  if (a === b) return true
  const ga = SCHED_GLOB.test(a), gb = SCHED_GLOB.test(b)
  if (ga && gb) { const pa = schedLiteralPrefix(a), pb = schedLiteralPrefix(b); return pa.startsWith(pb) || pb.startsWith(pa) }
  if (ga || gb) {
    const [glob, literal] = ga ? [a, b] : [b, a]
    if (schedGlobRe(glob).test(literal)) return true
    const p = schedLiteralPrefix(glob)
    return literal.endsWith('/') && (p.startsWith(literal) || literal.startsWith(p))
  }
  return (a.endsWith('/') && b.startsWith(a)) || (b.endsWith('/') && a.startsWith(b))
}
const filesOverlap = (fa, fb) => fa === '*' || fb === '*' || fa.some(a => fb.some(b => pathsOverlap(a, b)))

// Whether `item` waits, through its `after:` chain, on the item `id`.
function waitsOn(byId, item, id, seen = new Set()) {
  for (const d of item.after || []) {
    if (d === id) return true
    if (seen.has(d) || !byId[d]) continue
    seen.add(d)
    if (waitsOn(byId, byId[d], id, seen)) return true
  }
  return false
}

// The ids to start now, in plan order, at most `maxParallel` running in all.
function nextToStart(items, st, maxParallel) {
  const byId = Object.fromEntries(items.map(it => [it.id, it]))
  const running = items.filter(it => st[it.id].status === 'running')
  if (running.some(it => it.files === '*')) return []
  let slots = maxParallel - running.length
  const out = []
  for (let i = 0; i < items.length && slots > 0; i++) {
    const it = items[i]
    if (st[it.id].status !== 'pending') continue
    if (!(it.after || []).every(d => st[d] && st[d].status === 'done')) continue
    const busy = running.concat(out.map(id => byId[id]))
    if (busy.some(o => filesOverlap(o.files, it.files))) continue
    // An earlier item that itself waits on this one (`after:`, directly or
    // through others) is not ahead of it in the queue: holding this one for
    // it would leave both pending forever.
    const queuedAhead = items.slice(0, i).some(o => filesOverlap(o.files, it.files) && !waitsOn(byId, o, it.id) &&
      (st[o.id].status === 'pending' || ((st[o.id].status === 'parked' || st[o.id].status === 'held') && st[o.id].touched)))
    if (queuedAhead) continue
    if (it.files === '*' && busy.length) continue
    out.push(it.id)
    slots--
    if (it.files === '*') break
  }
  return out
}

// Pending items that can now never start, each with why: an `after:` item
// that is parked or held, or a file shared with an item parked or held after
// touching it. Repeated to a fixed point by the caller's loop; returns
// [{ id, reason }] and changes nothing itself.
function newlyHeld(items, st) {
  const stuck = s => s.status === 'parked' || s.status === 'held'
  const out = []
  for (let i = 0; i < items.length; i++) {
    const it = items[i]
    if (st[it.id].status !== 'pending') continue
    const dep = (it.after || []).find(d => st[d] && stuck(st[d]))
    if (dep) { out.push({ id: it.id, reason: `after ${dep}, which is ${st[dep].status}` }); continue }
    const sharer = items.slice(0, i).find(o => stuck(st[o.id]) && st[o.id].touched && filesOverlap(o.files, it.files))
    if (sharer) out.push({ id: it.id, reason: `shares files with ${sharer.id}, which is ${st[sharer.id].status} after editing them` })
  }
  return out
}

// The pending items a PLAN-DEFECT on `id` may invalidate: those that name it
// in `after:`/`shares:`, that it names, whose files overlap its own, or that
// run one of the same check commands. They are held for the replan; the rest
// keep flowing.
function invalidatedBy(items, st, id) {
  const bad = items.find(it => it.id === id)
  if (!bad) return []
  const links = it => (it.after || []).concat(it.shares || [])
  const cmds = it => new Set((it.checks || []).flatMap(c => [...String(c).matchAll(/`([^`]+)`/g)].map(m => m[1].trim())))
  const badCmds = cmds(bad)
  return items.filter(it => it.id !== id && st[it.id].status === 'pending' && (
    links(it).includes(id) || links(bad).includes(it.id) || filesOverlap(it.files, bad.files) ||
    [...cmds(it)].some(c => badCmds.has(c)))).map(it => it.id)
}

// Nothing left that could run: every item is done, parked or held.
const drainedItems = (items, st) => items.every(it => !['pending', 'running'].includes(st[it.id].status))
// @scheduler-end

const IMPL_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['IMPL-DONE', 'PLAN-DEFECT', 'ADVICE-NEEDED'] },
    report: { type: 'string' },
    evidence: { type: 'string' },
    progress_so_far: { type: 'string' },
    question: { type: 'string' },
  },
  required: ['verdict', 'report', 'evidence', 'progress_so_far'],
}
// A lane may also return STOPPED: another lane wrote the round's stop marker (2h).
const LANE_SCHEMA = {
  ...IMPL_SCHEMA,
  properties: {
    ...IMPL_SCHEMA.properties,
    verdict: { type: 'string', enum: [...IMPL_SCHEMA.properties.verdict.enum, 'STOPPED'] },
    lane: { type: 'string' },
  },
}
// The snapshot agent runs both `snapshot` (content hashes, for `delta` later)
// and `heads` (this round's per-repo base shas, for the reviewer read
// commands below) and reports both in one round trip.
const SNAPSHOT_SCHEMA = {
  type: 'object',
  properties: {
    exit_code: { type: 'number' },
    heads: { type: 'array', items: { type: 'object', properties: {
      repo: { type: 'string' }, sha: { type: 'string' },
    }, required: ['repo', 'sha'] } },
    raw_output: { type: 'string' },
  },
  required: ['exit_code', 'heads', 'raw_output'],
}
const DELTA_SCHEMA = {
  type: 'object',
  properties: {
    exit_code: { type: 'number' },
    paths: { type: 'array', items: { type: 'string' } },
    instrumentContent: { type: 'boolean' },
    sdkContent: { type: 'boolean' },
    files_checked: { type: 'number' },
    files_missing: { type: 'number' },
    raw_output: { type: 'string' },
    // Patch rounds only (2i): `round_delta.py size`'s exit code and totals.
    size_exit_code: { type: 'number' },
    lines_changed: { type: 'number' },
    new_files: { type: 'number' },
  },
  required: ['exit_code', 'paths', 'instrumentContent', 'sdkContent', 'files_checked', 'files_missing', 'raw_output'],
}
const VERIFIER_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['PASS', 'PASS-PENDING-HUMAN', 'IMPL-DEFECT', 'PLAN-DEFECT'] },
    criteria: { type: 'array', items: { type: 'object', properties: {
      criterion: { type: 'string' }, status: { type: 'string', enum: ['pass', 'fail', 'unattempted'] }, evidence: { type: 'string' },
      gate: { type: 'string' }, // the gate token(s) the criterion names, e.g. 'live1: complete'; '' when ungated (2f)
    }, required: ['criterion', 'status', 'evidence'] } },
    pending_human: { type: 'array', items: { type: 'string' } },
    // STRUCTURAL FINDINGS and a non-empty NOT DONE/DEVIATIONS: an IMPL-DEFECT
    // that is not a failed criterion, which 2f must never reclassify.
    other_defects: { type: 'array', items: { type: 'string' } },
  },
  required: ['verdict', 'criteria', 'pending_human'],
}
// `fix` is the exact change that resolves a BLOCKING finding, when the reviewer
// can state one; a round whose every BLOCKING finding carries one may be
// followed by a patch round (2i).
const FINDING = { type: 'object', properties: { where: { type: 'string' }, problem: { type: 'string' }, evidence: { type: 'string' }, fix: { type: 'string' } }, required: ['where', 'problem', 'evidence'] }
const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    blocking: { type: 'array', items: FINDING },
    non_blocking: { type: 'array', items: FINDING },
    plan_defect: { type: 'boolean' },
    summary: { type: 'string' },
  },
  required: ['blocking', 'non_blocking', 'plan_defect', 'summary'],
}
// --- 2g: the scribe gets absolute paths -------------------------------------
//
// Measured 2026-09-24 (hs-drive-game-lease, wf_949ed012-a02, run from the
// worktree .claude/worktrees/workorder-parallelization-2d890c): told its two
// relative paths were "relative to your current working directory", the
// haiku scribe resolved them against the MAIN checkout, found neither file,
// and returned written: false with state_before "N/A - files do not exist".
// The Record pass then compared that against the driver's State and reported
// STATE-LOST listing every driver-owned line -- nothing had been lost, nothing
// had been written. So the scribe is handed paths already joined under the
// checkout the driver is in, and a scribe that wrote nothing is SCRIBE-FAILED,
// never STATE-LOST (recordState below).
const CHECKOUT_ROOT = String(A.checkoutRoot || '').replace(/[\\/]+$/, '')
const inCheckout = p => isAbsolutePath(p) ? p : `${CHECKOUT_ROOT}/${String(p).replace(/^(\.[\\/])+|^[\\/]+/, '')}`
const SCRIBE_PLAN = A.planPath && inCheckout(A.planPath)
const SCRIBE_CONTEXT = A.contextPath && inCheckout(A.contextPath)

const SCRIBE_SCHEMA = {
  type: 'object',
  properties: { written: { type: 'boolean' }, note: { type: 'string' }, state_before: { type: 'string' }, state_after: { type: 'string' } },
  required: ['written', 'note', 'state_before', 'state_after'],
}

if (!SLUG || !A.planPath || !A.contextPath || !A.goalExcerpt || !A.reviewers) {
  return { outcome: 'BAD-ARGS', detail: 'need slug, planPath, contextPath, goalExcerpt, reviewers' }
}
if (!CHECKOUT_ROOT && !(isAbsolutePath(A.planPath) && isAbsolutePath(A.contextPath))) {
  return { outcome: 'BAD-ARGS', detail: 'need checkoutRoot (`git rev-parse --show-toplevel` in this session) or absolute planPath and contextPath: the scribe resolves a relative path against the wrong checkout' }
}
// Lanes are only ever what a clean `plan_lint.py --lanes-json` printed, and
// that output always pairs lanes with `"join": true` and valid, distinct,
// non-empty lanes. Anything else was typed by hand, so it is refused before a
// single agent spawns rather than fanned out on trust.
const LANES = Array.isArray(A.lanes) ? A.lanes : []
if (LANES.length) {
  const bad = LANES.find(l => !l || !/^[a-z0-9-]+$/.test(l.name || '') || l.name === 'join' ||
    !Array.isArray(l.files) || !l.files.length || LANES.filter(o => o && o.name === l.name).length > 1)
  if (A.join !== true || bad) {
    return { outcome: 'BAD-ARGS', detail: `lanes must be pasted from \`plan_lint.py --lanes-json\`: ${A.join !== true ? 'join is not true' : `lane ${JSON.stringify(bad)} has a bad or duplicate name or no files`}` }
  }
}

// --- 2a: reviewers diff from the recorded base, not `HEAD` -----------------
//
// `<repo>` is repoRoot-joined and quoted when repoRoot is given, else the
// bare relative path -- same convention as the legacy `diffCommands` below,
// so an unset repoRoot keeps producing exactly the same strings it always
// has for a caller that never opts into heads.
const repoTarget = key => {
  if (key === '.') return REPO_ROOT ? `"${REPO_ROOT}"` : '.'
  return REPO_ROOT ? `"${underRoot(key)}"` : key
}
const repoWords = key => key === '.' ? "the hub checkout (this repository's root)" : `the ${key} submodule checkout`
const CAUTION = 'Review this checkout only; do not go looking in other worktrees.'
const HEADS_UNKNOWN = "the round's base commit is unknown — find this round's commits with `git log` before reading."

// `snap.heads` (or `args.baseHeads`) arrives as [{repo, sha}, ...]; index it
// by repo for the command builders. Anything not a non-empty array counts as
// "heads could not be obtained".
const headsMap = h => (h && Array.isArray(h) && h.length) ? Object.fromEntries(h.map(x => [x.repo, x.sha])) : null

const wholeChangeScope = heads => Object.keys(heads).map(k => {
  const t = repoTarget(k), sha = heads[k]
  return `Reviewing ${repoWords(k)}: run \`git -C ${t} log --oneline ${sha}..HEAD\`, \`git -C ${t} diff ${sha}\`, \`git -C ${t} status --porcelain -uall\`. ${CAUTION}`
}).join(' ')

// A delta path that starts with a declared submodule's own dir belongs to
// that submodule's repo (with the prefix stripped for its own -C command);
// everything else is the hub's.
const splitPathsByRepo = paths => {
  const byRepo = { '.': [] }
  for (const s of SUBMODULES) byRepo[s] = []
  for (const p of paths) {
    const owner = SUBMODULES.find(s => p === s || p.startsWith(`${s}/`))
    if (owner) byRepo[owner].push(p.slice(owner.length + 1) || '.')
    else byRepo['.'].push(p)
  }
  return byRepo
}

const rerunScope = (heads, paths) => Object.entries(splitPathsByRepo(paths)).filter(([, ps]) => ps.length).map(([k, ps]) => {
  const t = repoTarget(k), sha = heads[k]
  return `Reviewing ${repoWords(k)}: run \`git -C ${t} diff ${sha} -- ${ps.join(' ')}\`. ${CAUTION}`
}).join(' ')

// Legacy whole-change commands: `HEAD`-relative, no per-repo base sha. Used
// only when heads could not be obtained at all (agent returned none, or
// `heads` exited 3) -- pinned by three tests that predate baseHeads, so kept
// byte-for-byte rather than folded into wholeChangeScope.
const diffCommands = (REPO_ROOT
  ? [`git -C "${REPO_ROOT}" status --porcelain -uall`, `git -C "${REPO_ROOT}" diff HEAD`]
  : ['git status --porcelain -uall', 'git diff HEAD'])
  .concat(SUBMODULES.flatMap(s => {
    const target = REPO_ROOT ? `"${underRoot(s)}"` : s
    return [`git -C ${target} status --porcelain -uall`, `git -C ${target} diff HEAD`]
  })).join(' ; ')

// --- 2b: the scribe pastes, it does not compose -----------------------------
//
// The exact markdown is built here in JS; the scribe's only job is to paste
// it verbatim under '## Log' and swap in the exact '## State' lines. Counts
// live in the headings themselves so a relabel (BLOCKING absorbing
// NON-BLOCKING, as measured 2026-09-17) is visible on sight.
//
// The scribe runs as the restricted `scribe` agent type (`.claude/agents/scribe.md`,
// `tools: Read, Edit` only) rather than the unrestricted `workflow-subagent`
// every other Record-phase agent here still is. On 2026-09-19 an unrestricted
// scribe read the harness's relayed user message ("fix these first, tell me
// when the DLL is ready") next to a round's findings and acted on it instead
// of only recording it: it resolved this prompt's relative paths against the
// user's home directory (creating files there), edited ForgePact source and
// docs with tools it had no business having, and ran `git add`/`git commit`.
// `tools/workorder_audit.py` R16 audits this.
const findingLine = f => `- [${f.reviewer}] ${f.where}: ${f.problem} — evidence: ${f.evidence}${f.fix ? ` — fix: ${f.fix}` : ''}`
// A NON-BLOCKING line goes in without its evidence. Every later round's
// implementer and driver re-reads the Log, and across forgepact-issue-14's 16
// context files NON-BLOCKING text was 154 KB, 52 KB of it evidence tails, for
// findings the round is told not to spend itself on. BLOCKING lines keep
// theirs: the next implementer works from it.
const nonBlockingLine = f => `- [${f.reviewer}] ${f.where}: ${f.problem}`
const roundBlock = (n, record) => {
  const lines = [`### Round ${n}`, '', `verifier: ${record.verifier}` +
    (record.verifierSaid ? ` (the verifier said ${record.verifierSaid}; every failed criterion is gated on a gate not set in \`gates:\`)` : '')]
  for (const c of record.failed) lines.push(`- FAILED ${c.criterion}: ${c.evidence}`)
  for (const c of record.gatePending || []) lines.push(`- PENDING (gate ${c.gate} not set) ${c.criterion}`)
  lines.push('', `BLOCKING (${record.blocking.length})`)
  for (const f of record.blocking) lines.push(findingLine(f))
  lines.push('', `NON-BLOCKING (${record.nonBlocking.length})`)
  for (const f of record.nonBlocking) lines.push(nonBlockingLine(f))
  lines.push('', `not re-run: ${record.notReRun.join(', ') || 'none'}`)
  if (record.patch) lines.push(`patch: ${record.patch}`)
  if (record.next) lines.push(`next: ${record.next}`)
  return lines.join('\n')
}
const stateBlock = (n, record, clean, planDefect, patchRounds) => [
  `round: ${clean || planDefect ? n : n + 1}`,
  `phase: ${clean ? 'pass' : planDefect ? 'blocked' : record.next ? 'patch' : 'implement'}`,
  `reviewers: ${Object.entries(record.reviewerState).map(([k, v]) => `${k}: ${v}${record.notReRun.includes(k) ? ', not re-run' : ''}`).join('; ')}`,
  `open defects: ${record.blocking.map(f => `${f.reviewer}: ${f.problem}`).join('; ') || 'none'}`,
  ...(patchRounds ? [`patch rounds: ${patchRounds}`] : []),
].join('\n')
const implBlock = (n, impl) => [`### Round ${n}`, '', impl.verdict, '', impl.evidence || impl.question || ''].join('\n')

// --- 2e: State is merged, never replaced ------------------------------------
//
// Measured 2026-09-23 (forgepact-issue-14-phaseA, -phaseA-record, -phase1h;
// phase1c and phase1d the same week): handed only the four lines stateBlock
// computes and told to "replace the round/phase/reviewers/open-defects
// lines", the haiku scribe took the whole '## State' block as its Edit's
// old_string -- those four lines are not contiguous, `gates:` and
// `round base:` sit between them -- and wrote back only the four, dropping
// the driver-owned `gates:`, `round base:`, `agents:` and
// `decisions in force:`. phase1h's round-2 verifier then read no `gates:`
// and reported gated criteria 7-12 pending instead of running them. The
// implementer-verdict scribe (`round:` + `phase: blocked` only) dropped
// `reviewers:` and `open defects:` the same way.
//
// So the script owns the whole block: it merges this round's keys into the
// State the driver passed (args.state), or the one the previous Record pass
// left, and the scribe pastes every line. Whatever the scribe did, it reports
// the State lines it read before and after its Edits, and an entry that was
// there before, is not one this round replaces, and is gone after stops the
// launch as STATE-LOST -- before a verifier can read the damaged block.
const STATE_KEY = /^([a-z][a-z0-9 _-]*?):(\s|$)/i
// One entry per key. A hand-written line carrying two keys
// (`round: 0        phase: plan`, measured) splits at the second; a line with
// no key continues the entry before it.
const stateEntries = text => {
  const out = []
  for (const raw of String(text || '').split(/\r?\n/)) {
    const line = raw.replace(/\s+$/, '')
    if (!line.trim() || /^#/.test(line)) continue
    if (!STATE_KEY.test(line)) {
      if (out.length) out[out.length - 1].text += '\n' + line
      else out.push({ key: '', text: line })
      continue
    }
    for (const seg of line.split(/\s{2,}(?=[a-z][a-z0-9 _-]*?:\s)/i)) out.push({ key: seg.match(STATE_KEY)[1].toLowerCase(), text: seg })
  }
  return out
}
const normEntry = t => t.split('\n').map(l => l.replace(/\s+$/, '')).join('\n').trim()
// Old order kept; an updated key replaces its entry in place (a duplicate of
// it is dropped); a key the old block lacked goes at the end.
const mergeState = (old, updates) => {
  const byKey = new Map(updates.map(u => [u.key, u]))
  const placed = new Set()
  const out = []
  for (const e of old) {
    if (!byKey.has(e.key)) { out.push(e); continue }
    if (!placed.has(e.key)) { out.push(byKey.get(e.key)); placed.add(e.key) }
  }
  for (const u of updates) if (!placed.has(u.key)) out.push(u)
  return out
}
const stateText = entries => entries.map(e => e.text).join('\n')
let knownState = stateEntries(A.state)

// --- 2f: a criterion gated on a gate not set is pending, never a defect -----
//
// Measured 2026-09-24 (forgepact-issue-14-phase1j): the planner wrote
// `gates:` as a template listing every gate and every possible value
// ("build: complete | live1: complete | record: complete | ..."). The verifier
// read it as all set, ran the criteria gated on `live1`/`record`, which only
// a live session can satisfy, and failed them. Rounds 1 and 2 had no BLOCKING
// finding and no other failure, and the launch still ended at CAP. So the
// script reads `gates:` itself. Only the tokens literally on that line count
// as set. A value holding `|` or "or" alternatives, or a `<placeholder>`, is a template
// and sets nothing, and a legacy "not yet: ..." tail is cut off. A round whose
// every failure names a gate that is not set, with no BLOCKING finding, routes
// as PASS-PENDING-HUMAN. When State has no `gates:` line at all, nothing is
// reclassified: an unknown gate set must not hide a real failure.
const normGate = t => String(t).replace(/`/g, '').replace(/\s+/g, ' ').trim().toLowerCase()
const gateTokens = text => {
  const ticked = [...String(text || '').matchAll(/`([^`]+)`/g)].map(m => m[1])
  const toks = ticked.length ? ticked : String(text || '').split(/[;,]|\band\b/i)
  return toks.map(t => normGate(t.replace(/\([^)]*\)/g, ''))).filter(t => t && t !== 'none')
}
const gatesSet = entries => {
  const e = entries.find(x => x.key === 'gates')
  if (!e) return null
  const value = e.text.replace(/^gates:\s*/i, '').replace(/\n/g, ' ').replace(/\([^)]*\)/g, '')
  // `|`, a `<placeholder>`, or an "or" outside a backticked token: alternatives, not gates set.
  if (/\||<[^>]*>/.test(value) || /\bor\b/i.test(value.replace(/`[^`]*`/g, ''))) return new Set()
  return new Set(gateTokens(value.split(/\bnot yet\b/i)[0]))
}

const scribe = (n, block, updates) => {
  const keys = updates.map(u => `\`${u.key}:\``).join(', ')
  const stateAsk = knownState.length
    ? `In ${SCRIBE_PLAN}, replace the lines under '## State' with exactly these lines. They are the whole State: this round's ${keys} values merged into the lines already there, so every other line (\`gates:\`, \`round base:\`, \`agents:\`, \`decisions in force:\` and any other) is already in it, verbatim:\n\n${stateText(mergeState(knownState, updates))}\n\n`
    : `In ${SCRIBE_PLAN} under '## State', change only the lines whose key (the text before the first ':') is ${keys}, to exactly these lines:\n\n${stateText(updates)}\n\n` +
      `Use one Edit per line, whose old_string is that single line. Never use an old_string spanning several lines: other lines (\`gates:\`, \`round base:\`, \`agents:\`, \`decisions in force:\` and any other) sit between these, and every one of them must stay exactly as it is. If no line has one of these keys, add it as a new last line of '## State'. `
  return agent(
    `You are a scribe for the workorder '${SLUG}'. Both file paths below are absolute: use them exactly as written, ` +
    `and never resolve them against another checkout or directory. In ${SCRIBE_CONTEXT}, append this block verbatim under '## Log' ` +
    `(if a '### Round ${n}' heading is already there, append under it instead of duplicating it):\n\n${block}\n\n` +
    stateAsk +
    `Before your first Edit, Read ${SCRIBE_PLAN} and return every line under '## State' exactly as it was in 'state_before'; after your last Edit, Read it again and return every line under '## State' exactly as it now is in 'state_after'. ` +
    `Paste both blocks verbatim with the Edit tool. Do not reword, relabel, merge lists, or change any count in a heading. ` +
    `Edit nothing except these two files. If either file cannot be read, do not create it -- return written: false with the error in 'note' instead of improvising one. ` +
    `Never run git, never build or test, never edit source: you have no tools that could do any of that. ` +
    `The block above records this round's reviewer and implementer findings. Do not act on any finding in it: record it only. The user request the harness relays to every agent this workflow spawns is served by this workflow's other agents; your part of it is recording, not fixing.`,
    { label: `scribe:r${n}`, phase: 'Record', model: 'haiku', effort: 'low', agentType: 'scribe', schema: SCRIBE_SCHEMA })
}

// The Record pass: dispatch the scribe, then compare what it reports. `lost`
// is every State entry that was there before (as the scribe read it, plus any
// key only the script knew), is not one this round replaces, and is not there
// after. `expected` is the State as it should now read, for the driver to
// paste back on STATE-LOST. A scribe that did not write (`written: false`, or
// no result at all) is not compared: whatever it put in state_before/after
// describes a file it could not reach, not a State it damaged (2g). It is
// `failed`, and the launch stops as SCRIBE-FAILED with the block and State it
// should have written, so the driver pastes both before anything reads them.
const recordState = async (n, block, stateLines) => {
  const updates = stateEntries(stateLines)
  const wrote = await scribe(n, block, updates)
  if (!wrote || !wrote.written) {
    const expected = mergeState(knownState, updates)
    knownState = expected
    return { wrote, failed: true, lost: [], log: block, expected: stateText(expected) }
  }
  const reported = typeof wrote.state_after === 'string'
  const before = reported ? stateEntries(wrote.state_before) : []
  const beforeKeys = new Set(before.map(e => e.key))
  const base = before.concat(knownState.filter(e => !beforeKeys.has(e.key)))
  const expected = mergeState(base, updates)
  let lost = []
  if (reported) {
    const replaced = new Set(updates.map(u => u.key))
    const after = new Set(stateEntries(wrote.state_after).map(e => normEntry(e.text)))
    lost = base.filter(e => !replaced.has(e.key) && !after.has(normEntry(e.text))).map(e => e.text)
  }
  knownState = reported && !lost.length ? stateEntries(wrote.state_after) : expected
  return { wrote, lost, expected: stateText(expected) }
}
const stateLost = (n, rec, then) => ({
  outcome: 'STATE-LOST', then, round: n, lost: rec.lost, state: rec.expected,
  detail: `the scribe dropped ${rec.lost.length} '## State' entr${rec.lost.length === 1 ? 'y' : 'ies'} (${rec.lost.map(l => l.split(':')[0] + ':').join(', ')}); paste 'state' back under '## State', then act on 'then'`,
})
const scribeFailed = (n, rec, then) => ({
  outcome: 'SCRIBE-FAILED', then, round: n, log: rec.log, state: rec.expected,
  detail: `the scribe wrote nothing (${rec.wrote ? `note: ${rec.wrote.note || 'none'}` : 'no result'}); no State was lost. Append 'log' under '## Log' in ${A.contextPath}, replace '## State' in ${A.planPath} with 'state', then act on 'then'`,
})
const recordStop = (n, rec, then) => rec.failed ? scribeFailed(n, rec, then) : rec.lost.length ? stateLost(n, rec, then) : null

// --- 2d: a reviewer is told what not to spend calls on ----------------------
//
// All three measured 2026-09-18 on one run (forgepact-closure-names-current-game):
// docs-sync-reviewer ran 40 turns in round 0, about 20 of them proving each
// Out-of-scope item had been left untouched -- which the verifier's criteria
// already do; in round 1, handed a one-file delta but not its own finding, it
// re-read the whole round-0 commit to work out what it had said (46 calls);
// and the verifier, given no context path and no way to open one cited
// heading, read the whole context file, implementer's Log included.
const OUT_OF_SCOPE_NOTE = 'The Out-of-scope list is there so you do not report those items as missing. ' +
  'Do not spend calls proving each one was left untouched -- the verifier\'s criteria do that; report one only if the diff you are reading shows it touched.'
const RERUN_NOTE = 'Earlier rounds reviewed the rest of the change: judge what this diff changes and what it newly invalidates, and do not re-read earlier commits.'
// `ask` differs when nothing changed: there is no diff to judge a fix from,
// and the finding lives in exactly the earlier commits RERUN_NOTE fences off.
const priorNote = (found, ask) => (found && found.length)
  ? `Your previous BLOCKING finding${found.length > 1 ? 's' : ''}: ${found.map(f => `[${f.where}] ${f.problem}`).join(' || ')}\n${ask}\n`
  : ''
const PRIOR_ASK = 'Say first, from this diff, whether each is resolved.'
const NOTHING_CHANGED_SCOPE = 'This is a re-run, and nothing changed this round: there is no new diff. Re-check only your previous finding, against the tree as it stands.'
// Single-quoted heading: inside double quotes Bash runs a backticked word as a
// command, and workorder headings are full of backticks. A legacy single-file
// plan keeps its cited sections in the plan itself.
const SECTION_CMD = file => `\`py -3 .claude/skills/workorder/section.py "${file}" '<heading>'\``
// Measured 2026-09-22: 8 of 22 sessions failed R2 because a verifier, told
// only "Workorder: <path>", read a 30-42KB plan whole to find its criteria.
// Hand it the two extractions that are the whole of its mandate.
const VERIFIER_CRITERIA_NOTE = ` Take the criteria and the gate tokens with exactly \`py -3 .claude/skills/workorder/section.py "${A.planPath}" 'Acceptance criteria'\` and \`py -3 .claude/skills/workorder/section.py "${A.planPath}" 'State'\`; do not Read the plan whole.` +
  ` A gate is set only when the \`gates:\` line itself carries its token. \`gates pending:\` and \`route tokens:\` set nothing, and a \`gates:\` value with \`|\` alternatives is a template that sets nothing. Put the token a gated criterion names in its 'gate'. A criterion whose gate is not set is 'unattempted' (gate <token> not set), never 'fail'. Put each STRUCTURAL FINDING and each NOT DONE/DEVIATIONS finding in 'other_defects'.` +
  ` First run every command-shaped criterion in one call: \`py -3 tools/run_criteria.py "${A.planPath}" --jobs auto --out "<your scratchpad>/criteria"\` with the Bash timeout at 600000. It runs each distinct command once, exactly as written, independent ones at the same time (builds first), skips criteria whose gate is not set, and prints each exit code and output tail in plan order (full output in cmd-<n>.log); it judges nothing, so decide each criterion from what it printed, check the ones it prints as 'no command' by reading, run by hand only a command that could not start in bash, and if its output stops early re-run it with --start <next criterion>. A root suite the runner already ran is the suite run: grep its log, never run it again.` +
  ` Run each criterion's command exactly as written: never swap \`py -3\` for \`python\`; a command that cannot start is a failed criterion with its error. Run each test suite once, with the Bash timeout at 240000 and its output sent to a scratch file you grep; never run a suite again to read another slice.`
const VERIFIER_CONTEXT_NOTE = A.contextPath !== A.planPath
  ? ` Context file: ${A.contextPath} -- open it only for a heading a criterion cites, with ${SECTION_CMD(A.contextPath)}; never read it whole, its '## Log' is the implementer's reasoning.`
  : ` This is a single-file plan: open a section a criterion cites with ${SECTION_CMD(A.planPath)} rather than reading on past the criteria; its '## Log' is the implementer's reasoning.`

// --- 2h: lanes run in parallel on a launch's first round (issue #176) -------
//
// A plan may declare `### Lane: <name>` step groups with disjoint file sets
// plus one `### Join` (`tools/plan_lint.py` refuses overlap). On the round a
// launch starts at, each lane gets its own implementer through one parallel()
// barrier, and the join runs alone once every lane returned IMPL-DONE. Its
// result then goes down the same delta/verify path a single implementer's does.
//
// Lanes never write to git: `.git/index.lock` is fail-fast, so two lanes
// committing at once would fail rather than wait. The join commits each lane's
// file set as its own commit first, then does its own steps. Lanes run no
// build or full suite either, since two builds in one tree race on artifacts.
//
// The script cannot cancel a running agent, so stopping is cooperative. A lane
// about to return PLAN-DEFECT or ADVICE-NEEDED writes the round's stop marker
// (`round_delta.py stop`), every lane checks it before each step
// (`round_delta.py stopped`, exit 4) and returns STOPPED with its progress.
// When any lane is not IMPL-DONE the join is skipped and the round is handed
// back with every lane's verdict and progress. Later rounds of the launch are
// defect rounds and run one implementer, as a plan without lanes does.
const START = A.round || 0
const VERDICT_ASK = `Return your usual verdict; put the PLAN-DEFECT evidence block or the ADVICE-NEEDED request, verbatim, in 'evidence'/'question'.`
const workorderLine = n => `Workorder: ${A.planPath}${A.contextPath !== A.planPath ? ` (context file: ${A.contextPath})` : ''}. This is round ${n}. `
// Any round past 0 follows a defect round -- '## State' only bumps `round:`
// after one -- including the first round of a fresh launch, which has no
// memory of it (the gap priorFindings closes for reviewers).
const reentry = n => n > 0 ? `You are re-entered after a defect: read '## Log' > '### Round ${n - 1}'` +
  `, and '### Round ${n}' if it is already there (this round was relaunched after a replan or a consultation, and that entry is the newer evidence),` +
  ` for the evidence before anything else. ` : ''
const LANE_NAMES = LANES.map(l => l.name).join(', ')
const LANED_LATER_NOTE = `This plan declares lanes (${LANE_NAMES}), but this round runs one implementer, not lanes: you own every lane's file set and the join's steps, and the lane-only rules (no git writes, the stop marker) do not apply to you. `
const implPrompt = n => workorderLine(n) + reentry(n) + (LANES.length && n > START ? LANED_LATER_NOTE : '') + VERDICT_ASK
const implOpts = (label, schema) => ({ label, phase: 'Implement', agentType: 'implementer', model: A.implementerModel || 'opus', schema })
const lanePrompt = (n, lane) => workorderLine(n) + reentry(n) +
  `You are lane '${lane.name}', one of ${LANES.length} lanes (${LANE_NAMES}) running at the same time in separate implementers: follow your "When you are one lane, or the join" section. ` +
  `Carry out only the steps under '### Lane: ${lane.name}' in '## Steps', after the preconditions written above the first '### Lane:'; the '### Join' steps and every other lane's steps are not yours. ` +
  `Your file set is ${lane.files.map(f => `\`${f}\``).join(', ')}: edit nothing outside it -- an edit you need outside it is a PLAN-DEFECT. ` +
  `Run no git command that writes (add, commit, stash, checkout, restore, reset, rebase, merge, switch, submodule, push, ...): the join commits your file set after every lane has returned. ` +
  `Run no full build and no full test suite, only tests inside your file set: the build and the suite are join steps. ` +
  `Before starting each step, run \`${DELTA} stopped ${SLUG} ${n}${DELTA_ROOT_ARG}\`: exit 4 means another lane has stopped this round, so stop there (finish a step you are already in the middle of first) and return verdict STOPPED with 'progress_so_far' naming the steps done, the files touched and what is half-finished. ` +
  `Before you return PLAN-DEFECT or ADVICE-NEEDED, first run \`${DELTA} stop ${SLUG} ${n} --lane ${lane.name} --verdict <PLAN-DEFECT|ADVICE-NEEDED>${DELTA_ROOT_ARG}\` so the other lanes stop too. ` +
  `Set 'lane' to '${lane.name}'. ` + VERDICT_ASK
// One lane's commit, per repo its paths belong to (a submodule path is
// committed in that submodule, prefix stripped). Paths are double-quoted so
// the shell never expands a glob; git matches it as a pathspec.
const laneCommit = files => Object.entries(splitPathsByRepo(files)).filter(([, ps]) => ps.length).map(([k, ps]) => {
  const git = k === '.' ? (REPO_ROOT ? `git -C "${REPO_ROOT}"` : 'git') : `git -C ${repoTarget(k)}`
  return `\`${git} add -- ${ps.map(p => `"${p}"`).join(' ')}\` then \`${git} commit\``
}).join(' and ')
const joinPrompt = (n, lanes) => workorderLine(n) + reentry(n) +
  `You are the join: the ${LANES.length} lanes (${LANE_NAMES}) each returned IMPL-DONE, and none of their work is committed; follow your "When you are one lane, or the join" section. ` +
  `First commit each lane's file set as its own commit, in this order, with a message naming the lane: ` +
  LANES.map(l => `lane ${l.name}: ${laneCommit(l.files)}`).join('; ') + '; ' +
  `then carry out the steps under '### Join' in '## Steps' (the build, the full suite, and every step that reads another lane's output), and last commit what remains. ` +
  `Report under DEVIATIONS any dirty path that is in no lane's file set and that you did not create. ` +
  `The lanes reported:\n${lanes.map(l => `--- lane ${l.name} ---\n${l.report || ''}`).join('\n')}\n` + VERDICT_ASK
const laneBlock = (n, outcome, lanes) => [`### Round ${n}`, '', `${outcome} (lanes: ${lanes.map(l => `${l.name} ${l.verdict}`).join(', ')}; the join did not run)`,
  ...lanes.flatMap(l => ['', `lane ${l.name}: ${l.verdict}`,
    ...(l.verdict !== 'IMPL-DONE' && (l.evidence || l.question) ? [l.evidence || l.question] : []),
    `progress: ${l.progress_so_far || 'none reported'}`])].join('\n')

// --- 2i: a stated fix is a patch round, not a round ------------------------
//
// Measured 2026-09-25 over the 29 sessions that ran a planner
// (docs/agents/workorder-calibration.md, "The cheap routes"): fix rounds,
// replans and reviewer re-runs were about a quarter of all subagent spend,
// and 32 of 69 fix-round implementers ran 7 minutes or less -- each at the
// price of a whole round and one of the three the cap allows.
//
// So when every BLOCKING finding of a round carries the reviewer's exact
// `fix`, nothing failed a criterion, and the verifier reported no other
// defect, the next round is a patch round: one implementer applies those fixes
// only, the verifier runs every criterion as usual (nothing says which
// criteria a change can reach), and only the reviewers that raised the
// findings re-run -- to confirm their own -- plus `decompile-output-guard`
// whenever its trigger matches, because a legal finding is never skipped.
//
// Eligibility is read off the findings, never off anyone's confidence, and
// the patch is checked again after the fact: `round_delta.py size` must
// report at most PATCH_MAX_LINES changed lines and no new file, and the
// delta must not reach an instrument path or a release note. A patch that
// holds does not count against ROUND_CAP (State's `patch rounds:`); one that
// does not is an ordinary round -- its reviewers chosen by the table as
// usual, and counted. Two patch rounds never run back to back, and
// `instrument-blindness-reviewer` findings never qualify: what a hook sees is
// not a matter of applying a stated edit.
const PATCH_MAX_LINES = 20
const PATCH_NEVER = new Set(['instrument-blindness-reviewer'])
const PATCH_EXCLUDED = p => /^ForgePact\/plugin\//.test(p) || /^hs-game-sdk\/.*(hook|install)/i.test(p) ||
  /-research\.md$/.test(p) || /(^|\/)release-notes-v[^/]*\.md$/.test(p)
const patchable = (verdict, failed, otherDefects, blocking) => blocking.length > 0 &&
  (verdict === 'PASS' || verdict === 'PASS-PENDING-HUMAN') && !failed.length && !otherDefects.length &&
  blocking.every(f => typeof f.fix === 'string' && f.fix.trim() && !PATCH_NEVER.has(f.reviewer))
const patchPrompt = (n, findings) => workorderLine(n) +
  `This is a patch round: the previous round's only defects were BLOCKING reviewer findings, each with the exact fix its reviewer stated. Apply exactly these fixes, then commit:\n` +
  findings.map(f => `- [${f.reviewer}] ${f.where}: ${f.problem}\n  fix: ${f.fix}`).join('\n') + '\n' +
  `Read the plan and context only where a fix needs them, start no other step, and run no full build or suite: the verifier runs the criteria. ` +
  `If a fix as stated does not resolve its finding, resolve the finding properly anyway and say so under DEVIATIONS -- the round is measured afterwards, and one that outgrew a patch counts as an ordinary round. ` + VERDICT_ASK
// Why a patch round did not hold, or null when it did.
const patchMiss = delta => {
  if (!delta || delta.exit_code !== 0) return 'the delta was unusable'
  if (delta.size_exit_code !== 0 || !Number.isFinite(delta.lines_changed) || !Number.isFinite(delta.new_files)) return '`round_delta.py size` gave no usable figure'
  if (delta.lines_changed > PATCH_MAX_LINES) return `${delta.lines_changed} lines changed (limit ${PATCH_MAX_LINES})`
  if (delta.new_files > 0) return `${delta.new_files} new file(s)`
  if (delta.instrumentContent) return 'instrument-shaped text changed'
  const excluded = delta.paths.filter(PATCH_EXCLUDED)
  if (excluded.length) return `touched ${excluded.join(', ')}`
  return null
}
// --- 3b: items mode -- a streamed pipeline instead of rounds -----------------
//
// The owner, 2026-09-26: "Going back to streamed workorder pipeline instead of
// hard gates. This could speed things up significantly." The ForgePact UI
// redesign lost most of its ~48 h to waiting: a 25-35 min full verify after
// every round, every item of a multi-item workorder waiting for the slowest
// one, and one owner question blocking unrelated items
// (docs/agents/workorder-calibration.md, "Streamed items").
//
// A plan whose `## Steps` declares `### Item:` groups (tools/plan_lint.py
// `--items-json`, pasted as args.items) runs here instead of in rounds:
//
//   * each item flows implement -> its own targeted checks -> done the moment
//     it is ready. Items on disjoint files run as parallel implementers;
//     items sharing a file queue in plan order (3a). An implementer commits
//     only its own files, under the checkout's commit lock
//     (tools/item_commit.py), so commits never race.
//   * reviewers read committed ranges, pinned to the HEAD they start from,
//     never the working tree the implementers are changing. Each reviewer
//     (or each scope of one, args.reviewScopes) re-runs as new commits land
//     and its trigger matches, and every BLOCKING finding it returns becomes
//     a fix item at once, queued on the files the finding names.
//   * an item that needs someone -- an owner question, ADVICE-NEEDED, a
//     PLAN-DEFECT, a spent budget -- parks alone. What depends on it (its
//     `after:` items, files it half-edited, and for a PLAN-DEFECT anything
//     its files, links or check commands overlap) is held; everything else
//     keeps flowing.
//   * when nothing is left to run, the whole-tree criteria (`## Acceptance
//     criteria`) run once: the only full verify. A failure there becomes one
//     fix item that runs alone, and the gate runs again (GATE_CAP runs).
//
// Budgets are per item (ITEM_ATTEMPTS implement attempts, FIX_CAP fix items
// per reviewer) under a ceiling for the launch (maxAgents agents, and
// tokenCeiling output tokens when set). Output tokens cannot be charged to
// one item from inside a script -- every agent running at once draws on the
// one `budget.spent()` counter -- so the token budget is the launch's only.
//
// Independence is unchanged: verifiers and reviewers get commits, paths and
// the plan's own text, never an implementer's reasoning.
const ITEMS_IN = Array.isArray(A.items) ? A.items : []
const ITEM_ATTEMPTS = A.itemAttempts || 3
const FIX_CAP = 3
const GATE_CAP = 3
const REFILL_CAP = 40
const MAX_PARALLEL = A.maxParallel || 4
const MAX_AGENTS = A.maxAgents || 120
const REVIEW_PASS_CAP = A.reviewPassCap || 4
const ITEM_ID = /^[a-z0-9-]+$/
const validItem = it => it && ITEM_ID.test(it.id || '') && Array.isArray(it.files) && it.files.length > 0
if (ITEMS_IN.length) {
  const ids = ITEMS_IN.map(it => it && it.id)
  const bad = ITEMS_IN.find(it => !validItem(it) || ids.filter(x => x === it.id).length > 1)
  const known = new Set(ids)
  const ref = ITEMS_IN.find(it => it && (it.after || []).concat(it.shares || []).some(r => !known.has(r)))
  if (LANES.length || bad || ref) {
    return { outcome: 'BAD-ARGS', detail: `items must be pasted from \`plan_lint.py --items-json\`: ${LANES.length ? 'a plan runs lanes or items, not both' : bad ? `item ${JSON.stringify(bad)} has a bad or duplicate id or no files` : `item ${ref.id} names an item the table lacks`}` }
  }
}

const ITEM_IMPL_SCHEMA = {
  ...IMPL_SCHEMA,
  properties: {
    ...IMPL_SCHEMA.properties,
    commits: { type: 'array', items: { type: 'object', properties: { repo: { type: 'string' }, sha: { type: 'string' } }, required: ['repo', 'sha'] } },
    paths: { type: 'array', items: { type: 'string' } },
    flags: { type: 'string' },
  },
}
const REVIEW_ITEMS_SCHEMA = {
  ...REVIEW_SCHEMA,
  properties: { ...REVIEW_SCHEMA.properties, reviewed_heads: SNAPSHOT_SCHEMA.properties.heads },
  required: [...REVIEW_SCHEMA.required, 'reviewed_heads'],
}
const REFILL_SCHEMA = {
  type: 'object',
  properties: { exit_code: { type: 'number' }, items: { type: 'array', items: { type: 'object' } }, complete: { type: 'boolean' }, raw_output: { type: 'string' } },
  required: ['exit_code', 'items', 'complete', 'raw_output'],
}
// `items: a=done; b=parked` in State, as a previous launch left it.
const itemsStateLine = text => {
  const e = stateEntries(text).find(x => x.key === 'items')
  if (!e) return {}
  return Object.fromEntries(e.text.replace(/^items:\s*/i, '').split(/[;,]/).map(s => s.trim().match(/^([a-z0-9-]+)\s*=\s*([a-z]+)/)).filter(Boolean).map(m => [m[1], m[2]]))
}
// The file a finding's `where` names (`panel/src/a.css:42` -> `panel/src/a.css`), or null.
const findingPath = where => {
  const w = String(where || '').trim()
  const m = w.match(/^`?([\w./\\-]+\.\w+)`?(?=$|[:\s§(,])/) || w.match(/`([\w./\\-]+\.\w+)`/)
  return m ? m[1].replace(/\\/g, '/').replace(/^\.\//, '') : null
}
const commitCmd = (id, title) => `py -3 tools/item_commit.py --message "${SLUG} ${id}${title ? `: ${String(title).replace(/"/g, "'")}` : ''}" -- <paths>`
const COMMIT_NOTE = 'Put each `commit` line it prints in \'commits\' as {repo, sha}, each `path` line in \'paths\', and the text after `flags` in \'flags\'. '

async function runItems(n) {
  const itemsState = itemsStateLine(A.state)
  const answered = new Set(A.answered || [])
  const all = []
  const st = {}
  const add = raw => {
    const it = { id: raw.id, title: raw.title || '', files: raw.files, after: raw.after || [], shares: raw.shares || [], owner: raw.owner || null, checks: raw.checks || [], kind: raw.kind || 'item', findings: raw.findings, reviewer: raw.reviewer, failed: raw.failed }
    all.push(it)
    // Only a plan item carries over from State: fix ids are this launch's own.
    const prior = it.kind === 'item' ? itemsState[it.id] : undefined
    const s = { status: 'pending', touched: false, attempts: 0, reason: '', commits: [], evidence: '' }
    if (prior === 'done') { s.status = 'done'; s.reason = 'done in an earlier launch' }
    else if (it.owner && !answered.has(it.id)) { s.status = 'parked'; s.reason = `owner: ${it.owner}` }
    st[it.id] = s
    return it
  }
  for (const raw of ITEMS_IN) add(raw)
  let agents = 0
  const tokenStart = (typeof budget !== 'undefined' && budget && budget.spent) ? budget.spent() : 0
  const overCeiling = () => agents >= MAX_AGENTS ||
    !!(A.tokenCeiling && typeof budget !== 'undefined' && budget && budget.spent && budget.spent() - tokenStart >= A.tokenCeiling)
  const spawn = (prompt, opts) => { agents++; return agent(prompt, opts) }

  const snap = await spawn(
    `Run exactly: ${DELTA} snapshot ${SLUG} ${n}${DELTA_ROOT_ARG}  — then report its exit code and output. ` +
    `Then run exactly: ${DELTA} heads ${SLUG} ${n}${DELTA_ROOT_ARG}  — report its exit code (3 if either command exited 3) and each printed line, split into repo and sha at the first tab, as heads: [{repo, sha}]. Edit nothing.`,
    { label: `snapshot:r${n}`, phase: 'Record', model: 'haiku', effort: 'low', schema: SNAPSHOT_SCHEMA })
  const baseHeads = (A.baseHeads && Object.keys(A.baseHeads).length) ? A.baseHeads
    : (snap && snap.exit_code === 0 ? headsMap(snap.heads) : null)

  // Reviewer instances: one per reviewer, or one per scope when the driver
  // split a reviewer by screen or dimension (args.reviewScopes).
  const scopes = A.reviewScopes || {}
  const reviewers = Object.keys(A.reviewers).flatMap(name => (scopes[name] && scopes[name].length ? scopes[name] : [null]).map(sc => ({
    name, key: sc ? `${name}@${sc.label}` : name, scope: sc, state: A.reviewers[name], seen: 0, passes: 0, fixes: 0,
    base: baseHeads, findings: (A.priorFindings || {})[name] || [], failed: false, running: false,
    // A reviewer entering as blocking re-reads the tree before any gate, even
    // on a relaunch where every item is already done and nothing will land.
    recheck: A.reviewers[name] === 'blocking' ? { initial: true } : null,
  })))
  const landed = [] // one entry per item or fix that committed: { id, paths, flags }
  const blocking = [], nonBlocking = [], planDefects = [], gateRuns = [], passLog = {}
  let fixSeq = 0
  let streaming = !!A.streaming
  let refills = 0
  let lintFailure = null

  const itemTitle = it => it.title ? ` (${it.title})` : ''
  const fileWords = it => it.files === '*' ? 'every file: you run alone, with no other implementer in the checkout' : it.files.map(f => `\`${f}\``).join(', ')
  const inFlight = () => all.filter(it => ['pending', 'running'].includes(st[it.id].status) && it.kind === 'item')
  const itemPrompt = (it, s) => workorderLine(n) +
    `You are item '${it.id}'${itemTitle(it)}, one of ${all.filter(x => x.kind === 'item').length} items; other items' implementers work in this checkout at the same time: follow your "When you are one item" section. ` +
    `Carry out only the steps under '### Item: ${it.id}' in '## Steps', after the preconditions written above the first '### Item:'. ` +
    `Your file set is ${fileWords(it)}: edit nothing outside it -- an edit you need outside it is a PLAN-DEFECT. ` +
    (it.owner ? `The owner has answered this item's question ("${it.owner}"); the answer is under '## Log' > '### Decisions'. ` : '') +
    `Run no git command that writes, except committing your own files once, at the end, with exactly \`${commitCmd(it.id, it.title)}\` (your file set, or the files you changed within it): it takes the checkout's commit lock and commits only those paths. ${COMMIT_NOTE}` +
    `Run no full build and no full suite. Before returning IMPL-DONE run your item's checks once, \`py -3 tools/run_criteria.py "${A.planPath}" --item ${it.id} --jobs auto --out "<your scratchpad>/item-${it.id}"\` (Bash timeout 600000), and fix what fails; an independent verifier runs them again after you. ` +
    (s.attempts > 1 ? `This is attempt ${s.attempts}: after the previous attempt's IMPL-DONE the item's checks failed, and the verifier reported:\n${s.evidence}\nFix that, commit again, and return. ` : '') +
    VERDICT_ASK
  const fixPrompt = it => workorderLine(n) +
    (it.kind === 'gate-fix'
      ? `You are fixer '${it.id}': every item is done, and the workorder's whole-tree acceptance criteria then failed:\n${it.failed.map(c => `- ${c.criterion}: ${c.evidence}`).join('\n')}\nFix those failures and nothing else. `
      : `You are fixer '${it.id}': a reviewer read committed work and raised these BLOCKING findings. Resolve exactly these, nothing else:\n` +
        it.findings.map(f => `- [${f.reviewer}] ${f.where}: ${f.problem}${f.fix ? `\n  fix: ${f.fix}` : ''}`).join('\n') + '\n' +
        `If a finding does not hold, change nothing for it and say why under DEVIATIONS: the reviewer re-reads your commit. `) +
    `Your file set is ${fileWords(it)}${it.files === '*' ? '' : ': edit nothing outside it -- an edit you need outside it goes under NOT DONE with the path'}. ` +
    `Run no git command that writes, except committing once, at the end, with exactly \`${commitCmd(it.id, '')}\` naming the files you changed. ${COMMIT_NOTE}` +
    `Run no full build or suite: the whole-tree criteria run once the queue drains. ` + VERDICT_ASK
  const checkPrompt = (it, s) => `Workorder: ${A.planPath}. Run item '${it.id}''s targeted checks and report what they printed: exactly ` +
    `\`py -3 tools/run_criteria.py "${A.planPath}" --item ${it.id} --jobs auto --out "<your scratchpad>/item-${it.id}-a${s.attempts}"\`, with the Bash timeout at 600000. ` +
    `These checks are your whole mandate this time: do not run the root suite or the workorder's acceptance criteria, which run once every item is done. ` +
    `Report each check as a criterion, judged from what the runner printed. Other items are being edited in this checkout while you run: a failure you can trace to a file outside this item's set (${fileWords(it)}) goes in 'other_defects' naming that file, not in a criterion.` +
    VERIFIER_CONTEXT_NOTE

  async function runItem(it) {
    const s = st[it.id]
    for (;;) {
      s.attempts++
      const label = it.kind === 'item' ? `item-implementer:${it.id}:a${s.attempts}:r${n}` : `fix-implementer:${it.id}:r${n}`
      const impl = await spawn(it.kind === 'item' ? itemPrompt(it, s) : fixPrompt(it), { label, phase: 'Implement', agentType: 'implementer', model: A.implementerModel || 'opus', schema: ITEM_IMPL_SCHEMA })
      if (!impl) return { park: 'the implementer returned nothing' }
      if (impl.commits && impl.commits.length) {
        s.commits.push(...impl.commits)
        landed.push({ id: it.id, paths: impl.paths || [], flags: impl.flags || '' })
      }
      if (impl.verdict !== 'IMPL-DONE') return { verdict: impl.verdict, evidence: impl.evidence || impl.question || '', progress: impl.progress_so_far }
      s.report = impl.report || ''
      s.committed = !!(impl.commits && impl.commits.length)
      if (it.kind !== 'item' || !it.checks.length) return { verdict: 'DONE' }
      const v = await spawn(checkPrompt(it, s), { label: `item-verifier:${it.id}:a${s.attempts}:r${n}`, phase: 'Verify', agentType: 'verifier', schema: VERIFIER_SCHEMA })
      if (!v) return { park: 'the item-check verifier returned nothing' }
      if (v.verdict === 'PASS' || v.verdict === 'PASS-PENDING-HUMAN') return { verdict: 'DONE', pending: v.pending_human || [] }
      const failedChecks = (v.criteria || []).filter(c => c.status === 'fail')
      s.evidence = failedChecks.map(c => `- FAILED ${c.criterion}: ${c.evidence}`).concat((v.other_defects || []).map(d => `- ${d}`)).join('\n') || `verdict ${v.verdict}`
      if (v.verdict === 'PLAN-DEFECT') return { verdict: 'PLAN-DEFECT', evidence: s.evidence }
      if (s.attempts >= ITEM_ATTEMPTS) return { park: `budget: ${s.attempts} attempts and its checks still fail`, evidence: s.evidence }
      if (overCeiling()) return { park: 'the launch reached its ceiling with this item\'s checks failing', evidence: s.evidence }
    }
  }

  const holdFixpoint = () => {
    for (let held = newlyHeld(all, st); held.length; held = newlyHeld(all, st)) {
      for (const h of held) { st[h.id].status = 'held'; st[h.id].reason = h.reason }
    }
  }
  const settleItem = (it, r) => {
    const s = st[it.id]
    // A finished fix is always re-read by the reviewer that raised it --
    // including one that committed nothing because it disputes the finding,
    // which lands no commit that would otherwise make the reviewer due.
    const raisedBy = it.kind === 'fix' && reviewers.find(rv => rv.key === it.reviewer)
    if (raisedBy && r && r.verdict === 'DONE') raisedBy.recheck = s.committed ? null : { fix: it.id, report: s.report }
    if (r && r.verdict === 'DONE') { s.status = 'done'; s.pending = r.pending || []; return }
    s.status = 'parked'
    if (!r) { s.reason = 'the item threw'; return }
    if (r.park) { s.reason = r.park; s.evidence = r.evidence || s.evidence; return }
    s.reason = r.verdict
    s.evidence = r.evidence || ''
    s.progress = r.progress || ''
    if (r.verdict === 'PLAN-DEFECT') {
      for (const id of invalidatedBy(all, st, it.id)) { st[id].status = 'held'; st[id].reason = `may be invalidated by ${it.id}'s PLAN-DEFECT` }
    }
  }

  // A reviewer instance is due when commits landed since its last pass and
  // it has never run, was blocking, or its trigger matches what landed.
  // Past REVIEW_PASS_CAP passes it waits for the final catch-up, which runs
  // once nothing else can.
  const deltaOf = events => ({
    paths: events.flatMap(e => e.paths), instrumentContent: events.some(e => /instrument/.test(e.flags)), sdkContent: events.some(e => /sdk/.test(e.flags)),
  })
  const inScope = (rv, paths) => !rv.scope || paths.some(p => (rv.scope.paths || []).some(g => pathsOverlap(g, p)))
  const reviewerDue = (rv, finalCatchUp) => {
    if (rv.running || rv.failed) return false
    if (rv.recheck) return true
    if (rv.seen >= landed.length) return false
    const fresh = landed.slice(rv.seen)
    const d = deltaOf(fresh)
    const wanted = rv.state === 'never' || rv.state === 'blocking' || ((TRIGGERS[rv.name] || (() => true))(d) && inScope(rv, d.paths))
    if (!wanted) { rv.seen = landed.length; (passLog[rv.key] = passLog[rv.key] || { passes: 0, skipped: 0 }).skipped++; return false }
    return rv.passes < REVIEW_PASS_CAP - 1 || finalCatchUp
  }
  const reviewScopeText = rv => [{ key: '.' }].concat(SUBMODULES.map(s => ({ key: s }))).map(({ key }) => {
    const t = repoTarget(key), base = rv.base && rv.base[key]
    const range = base ? `\`git -C ${t} log --oneline ${base}..<that sha>\` and \`git -C ${t} diff ${base} <that sha>\`` : `the commits since this workorder began (${HEADS_UNKNOWN})`
    return `Reviewing ${repoWords(key)}: first run \`git -C ${t} rev-parse HEAD\` and report it in 'reviewed_heads' as {repo: '${key}', sha}; then read ${range}.`
  }).join(' ') +
    ' Other agents are editing the working tree while you read: read a file only as of that commit (`git show <that sha>:<path>`), never from the working tree, and run no `git status` or `git diff` without both commits.' +
    (rv.scope ? ` Review only these paths: ${rv.scope.paths.map(p => `\`${p}\``).join(', ')}.` : '')
  async function runReview(rv) {
    rv.running = true
    const upto = landed.length
    const disputed = rv.recheck && rv.recheck.fix && upto <= rv.seen ? rv.recheck : null
    rv.recheck = null
    const prior = rv.state === 'blocking'
      ? priorNote(rv.findings, disputed ? 'This is the finding the fixer disputes.' : PRIOR_ASK) +
        (disputed ? `The fixer (${disputed.fix}) committed nothing for it; there is no new commit to read. Its report: ${String(disputed.report).slice(0, 1500)}\nConfirm the finding with the command and output that proves it, against the commit HEAD points at, or withdraw it.\n` : '')
      : ''
    const pending = inFlight()
    const r = await spawn(
      `You are reviewing committed work. You are NOT given the workorder; this is its intent:\n${A.goalExcerpt}\n${OUT_OF_SCOPE_NOTE}\n${reviewScopeText(rv)}\n` +
      (rv.passes > 0 ? `${RERUN_NOTE}\n` : '') + prior +
      (pending.length ? `Still being implemented, in files you will not see yet -- do not report as missing what these will cover: ${pending.map(it => `${it.id}${itemTitle(it)} [${it.files === '*' ? 'any file' : it.files.join(', ')}]`).join('; ')}.\n` : '') +
      (rv.name === 'instrument-blindness-reviewer' && A.researchHeadings ? `Research findings to check are recorded in ${A.contextPath} under: ${A.researchHeadings}. Read only those subsections.\n` : '') +
      `Do not run test suites or builds; run one targeted test only if a finding depends on its result. ` +
      `Mark every finding BLOCKING or NON-BLOCKING; set plan_defect only when no implementation of the plan as written could satisfy its Goal -- a missing assert, pin or sentence the plan did not forbid goes to the implementer, not plan_defect; lead the summary with "no blocking findings" when true. ` +
      `When you can state exactly how a BLOCKING finding is resolved -- the edit itself, at its path:line -- put it in that finding's 'fix'; leave 'fix' out when resolving it needs judgement or more research. Start each finding's 'where' with the file's path.`,
      { label: `${rv.key}:p${rv.passes + 1}:r${n}`, phase: 'Verify', agentType: rv.name, model: MODELS[rv.name], schema: REVIEW_ITEMS_SCHEMA })
    return { rv, r, upto }
  }
  const settleReview = ({ rv, r, upto }) => {
    rv.running = false
    rv.passes++
    ;(passLog[rv.key] = passLog[rv.key] || { passes: 0, skipped: 0 }).passes++
    if (!r) { rv.failed = true; return }
    rv.seen = upto
    const heads = headsMap(r.reviewed_heads)
    if (heads) rv.base = { ...(rv.base || {}), ...heads }
    const found = r.blocking.map(f => ({ reviewer: rv.key, ...f }))
    nonBlocking.push(...r.non_blocking.map(f => ({ reviewer: rv.key, ...f })))
    if (r.plan_defect) planDefects.push({ reviewer: rv.key, summary: r.summary, findings: found })
    rv.findings = r.blocking
    rv.state = found.length ? 'blocking' : 'clean'
    if (!found.length || r.plan_defect) return
    blocking.push(...found)
    rv.fixes++
    const paths = found.map(f => findingPath(f.where))
    const id = `fix-${++fixSeq}`
    add({ id, kind: 'fix', reviewer: rv.key, findings: found, files: paths.every(Boolean) ? [...new Set(paths)] : '*' })
    if (rv.fixes > FIX_CAP) { st[id].status = 'parked'; st[id].reason = `budget: ${rv.key} raised findings ${rv.fixes} times` }
  }
  async function refill() {
    refills++
    return spawn(`Run exactly: py -3 tools/plan_lint.py "${A.planPath}" --items-json --known ${all.filter(it => it.kind === 'item').map(it => it.id).join(',') || '-'} --wait 480  (Bash timeout 600000) — ` +
      `report its exit code, its whole output in 'raw_output', and, when it exited 0, the JSON on its last line as 'items' and 'complete'. Edit nothing.`,
      { label: `refill:${refills}:r${n}`, phase: 'Record', model: 'haiku', effort: 'low', schema: REFILL_SCHEMA })
  }
  const settleRefill = r => {
    if (!r || r.exit_code !== 0) { streaming = false; lintFailure = r ? r.raw_output : 'the refill agent returned nothing'; return }
    for (const raw of r.items || []) if (validItem(raw) && !st[raw.id]) add(raw)
    if (r.complete || refills >= REFILL_CAP) streaming = false
  }

  // One pass of the event loop: start what may start, wait for whichever
  // task ends first, settle it, repeat until nothing runs and nothing more
  // can start.
  async function drain() {
    const tasks = new Map()
    const launch = (key, p) => tasks.set(key, p.then(value => ({ key, value }), () => ({ key, value: null })))
    let stopping = false
    for (;;) {
      holdFixpoint()
      if (!stopping) {
        for (const id of nextToStart(all, st, MAX_PARALLEL)) {
          st[id].status = 'running'
          st[id].touched = true
          const it = all.find(x => x.id === id)
          launch(`item:${id}`, runItem(it).then(r => ({ it, r }), () => ({ it, r: null })))
        }
        const quiet = !tasks.size && !streaming
        for (const rv of reviewers) if (reviewerDue(rv, quiet)) launch(`review:${rv.key}`, runReview(rv))
        if (streaming && !tasks.has('refill')) launch('refill', refill())
      }
      if (!tasks.size) return
      const { key, value } = await Promise.race(tasks.values())
      tasks.delete(key)
      if (key.startsWith('item:')) settleItem(value ? value.it : all.find(x => `item:${x.id}` === key), value && value.r)
      else if (key.startsWith('review:')) settleReview(value || { rv: reviewers.find(x => `review:${x.key}` === key), r: null, upto: 0 })
      else settleRefill(value)
      if (overCeiling()) stopping = true
    }
  }

  const itemsLine = () => `items: ${all.filter(it => it.kind === 'item').map(it => `${it.id}=${st[it.id].status}`).join('; ')}`
  const reviewersLine = () => `reviewers: ${reviewers.map(rv => `${rv.key}: ${rv.failed ? 'no result' : rv.state}`).join('; ') || 'none'}`
  const openLine = () => `open defects: ${all.filter(it => st[it.id].status === 'parked').map(it => `${it.id}: ${st[it.id].reason}`).concat(planDefects.map(p => `${p.reviewer}: plan defect`)).join('; ') || 'none'}`
  const block = outcome => {
    const lines = [`### Round ${n} (items)`, '', `outcome: ${outcome}; ${all.filter(it => st[it.id].status === 'done').length} of ${all.length} done; ${agents} agents`]
    for (const it of all) {
      const s = st[it.id]
      lines.push(`- ${it.id}${itemTitle(it)}: ${s.status}${s.reason ? ` -- ${s.reason}` : ''}${s.attempts ? ` (attempts ${s.attempts})` : ''}${s.commits.length ? `; commits ${s.commits.map(c => `${c.repo}:${String(c.sha).slice(0, 12)}`).join(', ')}` : ''}`)
      if (s.status !== 'done' && s.evidence) lines.push(...String(s.evidence).split('\n').map(l => `  ${l}`))
      if (s.status !== 'done' && s.progress) lines.push(`  progress: ${s.progress}`)
    }
    for (const g of gateRuns) {
      lines.push('', `gate ${g.k}: ${g.verdict}${g.verifierSaid ? ` (the verifier said ${g.verifierSaid}; every failed criterion is gated on a gate not set in \`gates:\`)` : ''}`)
      for (const c of g.failed) lines.push(`- FAILED ${c.criterion}: ${c.evidence}`)
      for (const c of g.gatePending) lines.push(`- PENDING (gate ${c.gate} not set) ${c.criterion}`)
    }
    lines.push('', `BLOCKING (${blocking.length})`, ...blocking.map(findingLine))
    lines.push('', `NON-BLOCKING (${nonBlocking.length})`, ...nonBlocking.map(nonBlockingLine))
    lines.push('', `reviewer passes: ${Object.entries(passLog).map(([k, v]) => `${k} x${v.passes}${v.skipped ? ` (skipped ${v.skipped})` : ''}`).join('; ') || 'none'}`)
    if (lintFailure) lines.push(`plan_lint stopped the refill: ${String(lintFailure).slice(0, 1500)}`)
    return lines.join('\n')
  }
  const finish = async (outcome, extra = {}) => {
    const clean = outcome === 'PASS' || outcome === 'PASS-PENDING-HUMAN'
    const phase = clean ? 'pass' : outcome === 'PARKED' ? 'parked' : 'blocked'
    const rec = await recordState(n, block(outcome), [`round: ${clean ? n : n + 1}`, `phase: ${phase}`, itemsLine(), reviewersLine(), openLine()].join('\n'))
    const result = {
      outcome, round: n, agents,
      items: all.map(it => ({ id: it.id, kind: it.kind, status: st[it.id].status, reason: st[it.id].reason, attempts: st[it.id].attempts, commits: st[it.id].commits, evidence: st[it.id].evidence, progress: st[it.id].progress })),
      gate: gateRuns, blocking, nonBlocking, ...extra,
    }
    const stop = recordStop(n, rec, outcome)
    return stop ? { ...stop, ...result, outcome: stop.outcome, then: outcome } : result
  }

  for (let k = 1; ; k++) {
    await drain()
    // The gate reads a finished tree: anything still pending here could not
    // be scheduled, and counts as held rather than as done.
    for (const it of all) if (st[it.id].status === 'pending' && !overCeiling()) { st[it.id].status = 'held'; st[it.id].reason = 'could not be scheduled' }
    if (reviewers.some(rv => rv.failed)) return finish('AGENT-FAILED', { detail: `no result from: ${reviewers.filter(rv => rv.failed).map(rv => rv.key).join(', ')}` })
    if (overCeiling()) return finish('CEILING', { detail: `the launch spent ${agents} agents${A.tokenCeiling ? ` or ${A.tokenCeiling} output tokens` : ''}; relaunch to carry on from State's items: line` })
    if (lintFailure) return finish('PLAN-DEFECT', { detail: 'plan_lint refused the items the planner released; the refill stopped', lint: lintFailure })
    if (planDefects.length) return finish('PLAN-DEFECT', { detail: planDefects.map(p => `${p.reviewer}: ${p.summary}`).join(' || ') })
    if (all.some(it => ['parked', 'held'].includes(st[it.id].status))) {
      return finish('PARKED', { detail: 'every item that could run has run; the parked items need the driver, the rest wait on them' })
    }
    // A BLOCKING finding is closed only by its reviewer, never by a fixer's
    // word; one still open here has no fix left to run.
    const stillBlocking = reviewers.filter(rv => rv.state === 'blocking')
    if (stillBlocking.length) {
      return finish('PARKED', { detail: `BLOCKING findings still open with no fix to run: ${stillBlocking.map(rv => rv.key).join(', ')}` })
    }
    // 3b: the whole tree, once.
    const v = await spawn(`Workorder: ${A.planPath}. Run its acceptance criteria and report what they printed.${VERIFIER_CRITERIA_NOTE}${VERIFIER_CONTEXT_NOTE}`,
      { label: k === 1 ? `verifier:r${n}` : `verifier:g${k}:r${n}`, phase: 'Verify', agentType: 'verifier', schema: VERIFIER_SCHEMA })
    if (!v) return finish('AGENT-FAILED', { detail: 'the gate verifier returned nothing' })
    const gates = gatesSet(knownState)
    const gatedUnset = c => !!gates && gateTokens(c.gate).some(t => !gates.has(t))
    const allFailed = v.criteria.filter(c => c.status === 'fail')
    const failed = allFailed.filter(c => !gatedUnset(c))
    const gatePending = v.criteria.filter(c => c.status !== 'pass' && gatedUnset(c))
    const onlyGated = v.verdict === 'IMPL-DEFECT' && allFailed.length > 0 && !failed.length && !(v.other_defects || []).length
    const verdict = onlyGated ? 'PASS-PENDING-HUMAN' : v.verdict
    const pendingHuman = [...new Set([...(v.pending_human || []), ...all.flatMap(it => st[it.id].pending || []),
      ...gatePending.map(c => `${c.criterion} -> UNATTEMPTED (gate ${gateTokens(c.gate).filter(t => !gates.has(t)).join('; ')} not set)`)])]
    gateRuns.push({ k, verdict, verifierSaid: onlyGated ? v.verdict : undefined, failed, gatePending })
    if (verdict === 'PASS' || verdict === 'PASS-PENDING-HUMAN') return finish(verdict, { pending_human: pendingHuman })
    if (verdict === 'PLAN-DEFECT') return finish('PLAN-DEFECT', { detail: 'the gate verifier found a criterion that cannot be run as written' })
    if (k >= GATE_CAP) return finish('CAP', { detail: `the whole-tree criteria failed ${k} times; split the open failures into a new workorder` })
    const why = failed.length ? failed : (v.other_defects || []).map(d => ({ criterion: 'structural', evidence: d }))
    add({ id: `gate-fix-${k}`, kind: 'gate-fix', files: '*', failed: why })
  }
}

if (ITEMS_IN.length) return await runItems(A.round || 0)

const patchStateEntry = stateEntries(A.state).find(e => e.key === 'patch rounds')
let patchCount = patchStateEntry ? (parseInt(patchStateEntry.text.replace(/^patch rounds:\s*/i, ''), 10) || 0) : 0
let patchNext = null // the BLOCKING findings the next round patches, or null for an ordinary round

let reviewerState = { ...A.reviewers }
const lastFindings = { ...(A.priorFindings || {}) } // reviewer -> its BLOCKING findings from the round before
let lastVerifier = null // the previous round's full verifier result, reused when nothing changed
let firstHeads = null // this invocation's first usable snapshot heads, for a `never` reviewer's base when args.baseHeads is absent
const rounds = []

// `n - patchCount` is the number of rounds counted against the cap so far; a
// patch round already decided runs even at the cap, and counts only if it
// does not hold (2i).
for (let n = START; n - patchCount < ROUND_CAP || patchNext; n++) {
  const patchFindings = patchNext
  patchNext = null
  const isPatch = !!patchFindings
  const snap = await agent(
    `Run exactly: ${DELTA} snapshot ${SLUG} ${n}${DELTA_ROOT_ARG}  — then report its exit code and output. ` +
    `Then run exactly: ${DELTA} heads ${SLUG} ${n}${DELTA_ROOT_ARG}  — report its exit code (3 if either command exited 3) and each printed line, split into repo and sha at the first tab, as heads: [{repo, sha}]. Edit nothing.`,
    { label: `snapshot:r${n}`, phase: 'Record', model: 'haiku', effort: 'low', schema: SNAPSHOT_SCHEMA })

  const roundHeads = headsMap(snap && snap.heads)
  const roundHeadsUsable = !!(snap && snap.exit_code === 0 && roundHeads)
  if (n === START) firstHeads = roundHeadsUsable ? roundHeads : null
  const baseHeadsForNever = (A.baseHeads && Object.keys(A.baseHeads).length) ? A.baseHeads : firstHeads

  let impl
  if (LANES.length && n === START) {
    // 2h: every lane at once, then -- only if all of them are done -- the join.
    const laneResults = await parallel(LANES.map(lane => () => agent(lanePrompt(n, lane), implOpts(`implementer:${lane.name}:r${n}`, LANE_SCHEMA))))
    const lanes = LANES.map((lane, i) => laneResults[i] ? { ...laneResults[i], name: lane.name } : { name: lane.name, verdict: null })
    const silent = lanes.filter(l => !l.verdict)
    if (silent.length) return { outcome: 'AGENT-FAILED', round: n, detail: silent.map(l => `lane ${l.name} returned nothing`).join('; '), lanes, rounds }
    if (lanes.some(l => l.verdict !== 'IMPL-DONE')) {
      const outcome = lanes.some(l => l.verdict === 'PLAN-DEFECT') ? 'PLAN-DEFECT' : 'ADVICE-NEEDED'
      const rec = await recordState(n, laneBlock(n, outcome, lanes), `round: ${n}\nphase: blocked`)
      const stop = recordStop(n, rec, outcome)
      if (stop) return { ...stop, lanes, rounds }
      return { outcome, round: n, lanes, rounds }
    }
    impl = await agent(joinPrompt(n, lanes), implOpts(`implementer:join:r${n}`, IMPL_SCHEMA))
    if (!impl) return { outcome: 'AGENT-FAILED', round: n, detail: 'the join implementer returned nothing', lanes, rounds }
  } else if (isPatch) {
    // Labelled apart from `implementer:<lane>:r<n>` so the audit never reads a patch as a lane.
    impl = await agent(patchPrompt(n, patchFindings), implOpts(`patch-implementer:r${n}`, IMPL_SCHEMA))
    if (!impl) return { outcome: 'AGENT-FAILED', round: n, detail: 'patch implementer returned nothing', rounds }
  } else {
    impl = await agent(implPrompt(n), implOpts(`implementer:r${n}`, IMPL_SCHEMA))
    if (!impl) return { outcome: 'AGENT-FAILED', round: n, detail: 'implementer returned nothing', rounds }
  }
  if (impl.verdict !== 'IMPL-DONE') {
    const rec = await recordState(n, implBlock(n, impl), `round: ${n}\nphase: blocked`)
    const stop = recordStop(n, rec, impl.verdict)
    if (stop) return { ...stop, implementer: impl, rounds }
    return { outcome: impl.verdict, round: n, implementer: impl, rounds }
  }

  // 2c: the delta agent's content greps run in the repository, not wherever
  // its own shell happened to start, and it reports enough (files_checked /
  // files_missing) to tell "deleted this round" apart from "wrong cwd".
  const deltaRoot = REPO_ROOT ? `"${REPO_ROOT}"` : '.'
  const delta = await agent(
    `Run exactly: ${DELTA} delta ${SLUG} ${n}${DELTA_ROOT_ARG}  — report its exit code and every path it printed (one per line) in 'paths'. ` +
    `Then, from the repository root (run: cd ${deltaRoot} first, not wherever your shell already is), over only those paths that still exist, run ` +
    `grep -lE "Rva|GetModuleHandle|MmCreateHook|HookOneScript|InstallScriptHook" -- <paths> and report any match as instrumentContent; run ` +
    `grep -lE "CInstance|relicLevel|ItemStatStruct|ItemDefinitionStruct" -- <paths> and report any match as sdkContent. ` +
    `Report files_checked and files_missing: a path missing because it was deleted this round is normal, a path missing because you ran the greps from the wrong directory is not — if more than half the paths are missing, treat the delta as unusable and return exit_code 3 so every reviewer re-runs. ` +
    `An empty path list with exit code 0 is a valid answer — the round changed nothing; report it exactly as printed and stop, do not investigate. ` +
    (isPatch ? `Then run exactly: ${DELTA} size ${SLUG} ${n}${DELTA_ROOT_ARG}  — report its exit code as size_exit_code, and the numbers on its 'lines_changed:' and 'new_files:' lines as lines_changed and new_files. ` : '') +
    `Edit nothing.`,
    { label: `delta:r${n}`, phase: 'Record', model: 'haiku', effort: 'low', schema: DELTA_SCHEMA })
  const deltaUsable = !!(snap && snap.exit_code === 0 && delta && delta.exit_code === 0)
  // Measured 2026-09-18: a round whose only "fix" was confirming a false
  // BLOCKING finding changed nothing, and still paid a full verifier run
  // (47 turns, 1.9M). Criteria cannot have changed if the tree did not, so
  // the previous PASS stands and only the reviewers that were BLOCKING run,
  // to confirm or withdraw. A fresh invocation has no previous verdict to
  // reuse, so it still verifies.
  const prev = rounds.length ? rounds[rounds.length - 1] : null
  // An empty delta is a fact about the round; reusing the verifier's verdict is
  // a decision that also needs a previous PASS from this same launch. A fresh
  // launch, or a round after an IMPL-DEFECT, can have the first without the
  // second -- and its reviewers still have no diff to be pointed at.
  const emptyDelta = deltaUsable && delta.paths.length === 0
  const nothingChanged = emptyDelta && !!prev && prev.verifier === 'PASS' && !!lastVerifier

  // 2i: a patch that held is re-read by the reviewers that found what it fixed
  // and by the decompile guard when its trigger matches; one that did not hold
  // is an ordinary round from here on.
  const miss = isPatch ? patchMiss(delta) : null
  const patchHeld = isPatch && !miss
  // A reviewer that has never run, or was blocking, always runs. A clean one
  // runs when its trigger matches the delta — or when the delta is unusable.
  const toRun = Object.keys(reviewerState).filter(name => patchHeld
    ? reviewerState[name] !== 'clean' || (name === 'decompile-output-guard' && TRIGGERS[name](delta))
    : reviewerState[name] !== 'clean' || !deltaUsable || (TRIGGERS[name] || (() => true))(delta))
  const skipped = Object.keys(reviewerState).filter(name => !toRun.includes(name))
  log(`round ${n}: ${isPatch ? `patch ${patchHeld ? 'held' : `not held (${miss})`}; ` : ''}delta ${deltaUsable ? delta.paths.length + ' paths' : 'UNUSABLE -> all reviewers'}; running ${toRun.join(', ') || 'none'}; not re-run: ${skipped.join(', ') || 'none'}${nothingChanged ? '; nothing changed -> previous PASS stands, verifier not re-run' : ''}`)

  const wholeScope = () => baseHeadsForNever ? `Read the whole change. ${wholeChangeScope(baseHeadsForNever)}` : `${HEADS_UNKNOWN} Read the whole change: ${diffCommands}`
  const deltaScope = () => (roundHeadsUsable ? `This is a re-run. ${rerunScope(roundHeads, delta.paths)}` : `${HEADS_UNKNOWN} This is a re-run. Read only these paths changed this round (use the same commands restricted to them): ${delta.paths.join(', ')}.`) + ` ${RERUN_NOTE}`
  const scope = name => {
    if (reviewerState[name] === 'never' || !deltaUsable) return wholeScope()
    return emptyDelta ? NOTHING_CHANGED_SCOPE : deltaScope()
  }
  const nothingChangedNote = emptyDelta
    ? `Nothing changed this round: the implementer reports your previous BLOCKING finding does not hold. Its report: ${String(impl.report).slice(0, 1500)}\nConfirm the finding with the command and output that proves it, or withdraw it.\n`
    : ''
  // A barrier on purpose, not a pipeline() into fixers: agent() returns only
  // when a reviewer ends, and a fixer started on one reviewer's findings would
  // edit the tree this verifier is reading. Streaming findings into fixes is
  // the driver's procedure outside a round (SKILL.md "Spend each check once").
  const results = await parallel([
    () => nothingChanged ? Promise.resolve(lastVerifier) : agent(`Workorder: ${A.planPath}. Run its acceptance criteria and report what they printed.${VERIFIER_CRITERIA_NOTE}${VERIFIER_CONTEXT_NOTE}`,
      { label: `verifier:r${n}`, phase: 'Verify', agentType: 'verifier', schema: VERIFIER_SCHEMA }),
    ...toRun.map(name => () => agent(
      `You are reviewing a change. You are NOT given the workorder; this is its intent:\n${A.goalExcerpt}\n${OUT_OF_SCOPE_NOTE}\n${scope(name)}\n` +
      `${reviewerState[name] === 'blocking' ? priorNote(lastFindings[name], emptyDelta ? 'This is the finding the implementer disputes.' : PRIOR_ASK) + nothingChangedNote : ''}` +
      (name === 'instrument-blindness-reviewer' && A.researchHeadings ? `Research findings to check are recorded in ${A.contextPath} under: ${A.researchHeadings}. Read only those subsections.\n` : '') +
      `The verifier runs the acceptance criteria in parallel: do not re-run test suites or builds; run one targeted test only if a finding depends on its result. ` +
      `Mark every finding BLOCKING or NON-BLOCKING; set plan_defect only when no implementation of the plan as written could satisfy its Goal -- a missing assert, pin or sentence the plan did not forbid goes to the implementer, not plan_defect; lead the summary with "no blocking findings" when true. ` +
      `When you can state exactly how a BLOCKING finding is resolved -- the edit itself, at its path:line -- put it in that finding's 'fix'; leave 'fix' out when resolving it needs judgement or more research.`,
      { label: `${name}:r${n}`, phase: 'Verify', agentType: name, model: MODELS[name], schema: REVIEW_SCHEMA })
      .then(r => ({ name, r }))),
  ])
  const verifier = results[0]
  if (verifier) lastVerifier = verifier
  const reviews = results.slice(1).filter(Boolean)
  const missing = toRun.filter(name => !reviews.find(x => x.name === name && x.r))
  // A reviewer that died is "not observed", never "clean".
  if (!verifier || missing.length) {
    return { outcome: 'AGENT-FAILED', round: n, detail: `no result from: ${[!verifier && 'verifier', ...missing].filter(Boolean).join(', ')}`, rounds }
  }

  for (const { name, r } of reviews) {
    reviewerState[name] = r.blocking.length ? 'blocking' : 'clean'
    lastFindings[name] = r.blocking
  }
  const blocking = reviews.flatMap(({ name, r }) => r.blocking.map(f => ({ reviewer: name, ...f })))
  const nonBlocking = reviews.flatMap(({ name, r }) => r.non_blocking.map(f => ({ reviewer: name, ...f })))
  const planDefect = verifier.verdict === 'PLAN-DEFECT' || reviews.some(x => x.r.plan_defect)
  // 2f: the gates as the State this round's verifier read spells them.
  const gates = gatesSet(knownState)
  const gatedUnset = c => !!gates && gateTokens(c.gate).some(t => !gates.has(t))
  const allFailed = verifier.criteria.filter(c => c.status === 'fail')
  const failed = allFailed.filter(c => !gatedUnset(c))
  const gatePending = verifier.criteria.filter(c => c.status !== 'pass' && gatedUnset(c))
  const onlyGated = verifier.verdict === 'IMPL-DEFECT' && allFailed.length > 0 && !failed.length && !blocking.length &&
    !(verifier.other_defects || []).length
  const verdict = onlyGated ? 'PASS-PENDING-HUMAN' : verifier.verdict
  const pendingHuman = [...new Set([...(verifier.pending_human || []),
    ...gatePending.map(c => `${c.criterion} -> UNATTEMPTED (gate ${gateTokens(c.gate).filter(t => !gates.has(t)).join('; ')} not set)`)])]
  const record = { round: n, verifier: verdict, verifierSaid: onlyGated ? verifier.verdict : undefined, failed, gatePending, pending_human: pendingHuman, blocking, nonBlocking, notReRun: skipped, reviewerState: { ...reviewerState } }
  if (isPatch) {
    record.patch = patchHeld
      ? `held (${delta.lines_changed} lines in ${delta.paths.length} file(s)); not counted against the cap`
      : `not held (${miss}); counted as an ordinary round`
    if (patchHeld) patchCount++
  }
  rounds.push(record)

  const clean = !blocking.length && !planDefect && (verdict === 'PASS' || verdict === 'PASS-PENDING-HUMAN')
  if (!clean && !planDefect && !isPatch && patchable(verdict, failed, verifier.other_defects || [], blocking)) {
    patchNext = blocking
    record.next = 'patch round (every BLOCKING finding carries its reviewer\'s fix)'
  }
  const rec = await recordState(n, roundBlock(n, record), stateBlock(n, record, clean, planDefect, patchCount))
  // A dropped line -- or a Log/State never written -- is repaired before
  // anything reads it: the next round's verifier takes its gate tokens from
  // this very block, and its implementer its evidence from the Log.
  const stop = recordStop(n, rec, planDefect ? 'PLAN-DEFECT' : clean ? verdict : 'continue')
  if (stop) return { ...stop, rounds }

  if (planDefect) return { outcome: 'PLAN-DEFECT', round: n, rounds }
  if (clean) return { outcome: verdict, round: n, pending_human: pendingHuman, rounds }
}

return { outcome: 'CAP', detail: `${ROUND_CAP} implement->verify rounds used; split the open findings into a new workorder`, rounds }
