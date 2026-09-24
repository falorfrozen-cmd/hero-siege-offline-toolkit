export const meta = {
  name: 'workorder-rounds',
  description: 'Run one workorder\'s implement -> verify -> route rounds as code; hands back to the driver on anything that needs judgement',
  whenToUse: 'Opt-in from /workorder (workflow mode). Replaces the driver\'s own turns for steps 2-4; replans, consultations, human questions and the final report stay with the driver.',
  phases: [
    { title: 'Implement', detail: 'fresh implementer per round at the triaged tier' },
    { title: 'Verify', detail: 'verifier + delta-scoped reviewers, in parallel' },
    { title: 'Record', detail: 'haiku scribe: round snapshot/delta, Log entry, State' },
  ],
}

// Contract: .claude/skills/workorder/SKILL.md, "Workflow mode". The reviewer
// trigger table below is that skill's round >= 1 table as code; change both
// together.
//
// args: {
//   slug, planPath, contextPath,        // contextPath === planPath for a legacy single-file plan
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
// }

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
const FINDING = { type: 'object', properties: { where: { type: 'string' }, problem: { type: 'string' }, evidence: { type: 'string' } }, required: ['where', 'problem', 'evidence'] }
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
const SCRIBE_SCHEMA = {
  type: 'object',
  properties: { written: { type: 'boolean' }, note: { type: 'string' }, state_before: { type: 'string' }, state_after: { type: 'string' } },
  required: ['written', 'note', 'state_before', 'state_after'],
}

if (!SLUG || !A.planPath || !A.contextPath || !A.goalExcerpt || !A.reviewers) {
  return { outcome: 'BAD-ARGS', detail: 'need slug, planPath, contextPath, goalExcerpt, reviewers' }
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
const findingLine = f => `- [${f.reviewer}] ${f.where}: ${f.problem} — evidence: ${f.evidence}`
const roundBlock = (n, record) => {
  const lines = [`### Round ${n}`, '', `verifier: ${record.verifier}` +
    (record.verifierSaid ? ` (the verifier said ${record.verifierSaid}; every failed criterion is gated on a gate not set in \`gates:\`)` : '')]
  for (const c of record.failed) lines.push(`- FAILED ${c.criterion}: ${c.evidence}`)
  for (const c of record.gatePending || []) lines.push(`- PENDING (gate ${c.gate} not set) ${c.criterion}`)
  lines.push('', `BLOCKING (${record.blocking.length})`)
  for (const f of record.blocking) lines.push(findingLine(f))
  lines.push('', `NON-BLOCKING (${record.nonBlocking.length})`)
  for (const f of record.nonBlocking) lines.push(findingLine(f))
  lines.push('', `not re-run: ${record.notReRun.join(', ') || 'none'}`)
  return lines.join('\n')
}
const stateBlock = (n, record, clean, planDefect) => [
  `round: ${clean || planDefect ? n : n + 1}`,
  `phase: ${clean ? 'pass' : planDefect ? 'blocked' : 'implement'}`,
  `reviewers: ${Object.entries(record.reviewerState).map(([k, v]) => `${k}: ${v}${record.notReRun.includes(k) ? ', not re-run' : ''}`).join('; ')}`,
  `open defects: ${record.blocking.map(f => `${f.reviewer}: ${f.problem}`).join('; ') || 'none'}`,
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
// as set. A value holding `|` alternatives or a `<placeholder>` is a template
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
  if (/\||<[^>]*>/.test(value)) return new Set()
  return new Set(gateTokens(value.split(/\bnot yet\b/i)[0]))
}

const scribe = (n, block, updates) => {
  const keys = updates.map(u => `\`${u.key}:\``).join(', ')
  const stateAsk = knownState.length
    ? `In ${A.planPath}, replace the lines under '## State' with exactly these lines. They are the whole State: this round's ${keys} values merged into the lines already there, so every other line (\`gates:\`, \`round base:\`, \`agents:\`, \`decisions in force:\` and any other) is already in it, verbatim:\n\n${stateText(mergeState(knownState, updates))}\n\n`
    : `In ${A.planPath} under '## State', change only the lines whose key (the text before the first ':') is ${keys}, to exactly these lines:\n\n${stateText(updates)}\n\n` +
      `Use one Edit per line, whose old_string is that single line. Never use an old_string spanning several lines: other lines (\`gates:\`, \`round base:\`, \`agents:\`, \`decisions in force:\` and any other) sit between these, and every one of them must stay exactly as it is. If no line has one of these keys, add it as a new last line of '## State'. `
  return agent(
    `You are a scribe for the workorder '${SLUG}'. Both file paths below are relative to your current working directory ` +
    `(the repository root). In ${A.contextPath}, append this block verbatim under '## Log' ` +
    `(if a '### Round ${n}' heading is already there, append under it instead of duplicating it):\n\n${block}\n\n` +
    stateAsk +
    `Before your first Edit, Read ${A.planPath} and return every line under '## State' exactly as it was in 'state_before'; after your last Edit, Read it again and return every line under '## State' exactly as it now is in 'state_after'. ` +
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
// paste back on STATE-LOST. A scribe that reports nothing (it read no file)
// is not checked; its `written: false` already carries the evidence forward.
const recordState = async (n, block, stateLines) => {
  const updates = stateEntries(stateLines)
  const wrote = await scribe(n, block, updates)
  const reported = !!wrote && typeof wrote.state_after === 'string' && (!!wrote.written || wrote.state_after.trim() !== '')
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
  ` A gate is set only when the \`gates:\` line itself carries its token. \`gates pending:\` and \`route tokens:\` set nothing, and a \`gates:\` value with \`|\` alternatives is a template that sets nothing. Put the token a gated criterion names in its 'gate'. A criterion whose gate is not set is 'unattempted' (gate <token> not set), never 'fail'. Put each STRUCTURAL FINDING and each NOT DONE/DEVIATIONS finding in 'other_defects'.`
const VERIFIER_CONTEXT_NOTE = A.contextPath !== A.planPath
  ? ` Context file: ${A.contextPath} -- open it only for a heading a criterion cites, with ${SECTION_CMD(A.contextPath)}; never read it whole, its '## Log' is the implementer's reasoning.`
  : ` This is a single-file plan: open a section a criterion cites with ${SECTION_CMD(A.planPath)} rather than reading on past the criteria; its '## Log' is the implementer's reasoning.`

let reviewerState = { ...A.reviewers }
const lastFindings = { ...(A.priorFindings || {}) } // reviewer -> its BLOCKING findings from the round before
let carried = null // evidence for the next implementer when the scribe could not write it
let lastVerifier = null // the previous round's full verifier result, reused when nothing changed
let firstHeads = null // this invocation's first usable snapshot heads, for a `never` reviewer's base when args.baseHeads is absent
const rounds = []

for (let n = A.round || 0; n < ROUND_CAP; n++) {
  const snap = await agent(
    `Run exactly: ${DELTA} snapshot ${SLUG} ${n}${DELTA_ROOT_ARG}  — then report its exit code and output. ` +
    `Then run exactly: ${DELTA} heads ${SLUG} ${n}${DELTA_ROOT_ARG}  — report its exit code (3 if either command exited 3) and each printed line, split into repo and sha at the first tab, as heads: [{repo, sha}]. Edit nothing.`,
    { label: `snapshot:r${n}`, phase: 'Record', model: 'haiku', effort: 'low', schema: SNAPSHOT_SCHEMA })

  const roundHeads = headsMap(snap && snap.heads)
  const roundHeadsUsable = !!(snap && snap.exit_code === 0 && roundHeads)
  if (n === (A.round || 0)) firstHeads = roundHeadsUsable ? roundHeads : null
  const baseHeadsForNever = (A.baseHeads && Object.keys(A.baseHeads).length) ? A.baseHeads : firstHeads

  const impl = await agent(
    `Workorder: ${A.planPath}${A.contextPath !== A.planPath ? ` (context file: ${A.contextPath})` : ''}. This is round ${n}. ` +
    // Any round past 0 follows a defect round -- '## State' only bumps `round:`
    // after one -- including the first round of a fresh launch, which has no
    // memory of it (the gap priorFindings closes for reviewers).
    (n > 0 || carried ? `You are re-entered after a defect: read '## Log' > '### Round ${n - 1}'` +
      (n > 0 ? `, and '### Round ${n}' if it is already there (this round was relaunched after a replan or a consultation, and that entry is the newer evidence),` : '') +
      ` for the evidence before anything else. ` : '') +
    (carried ? `The scribe could not write the evidence, so it is here verbatim: ${JSON.stringify(carried)} ` : '') +
    `Return your usual verdict; put the PLAN-DEFECT evidence block or the ADVICE-NEEDED request, verbatim, in 'evidence'/'question'.`,
    { label: `implementer:r${n}`, phase: 'Implement', agentType: 'implementer', model: A.implementerModel || 'opus', schema: IMPL_SCHEMA })
  if (!impl) return { outcome: 'AGENT-FAILED', round: n, detail: 'implementer returned nothing', rounds }
  if (impl.verdict !== 'IMPL-DONE') {
    const rec = await recordState(n, implBlock(n, impl), `round: ${n}\nphase: blocked`)
    if (rec.lost.length) return { ...stateLost(n, rec, impl.verdict), implementer: impl, rounds }
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
    `An empty path list with exit code 0 is a valid answer — the round changed nothing; report it exactly as printed and stop, do not investigate. Edit nothing.`,
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

  // A reviewer that has never run, or was blocking, always runs. A clean one
  // runs when its trigger matches the delta — or when the delta is unusable.
  const toRun = Object.keys(reviewerState).filter(name =>
    reviewerState[name] !== 'clean' || !deltaUsable || (TRIGGERS[name] || (() => true))(delta))
  const skipped = Object.keys(reviewerState).filter(name => !toRun.includes(name))
  log(`round ${n}: delta ${deltaUsable ? delta.paths.length + ' paths' : 'UNUSABLE -> all reviewers'}; running ${toRun.join(', ') || 'none'}; not re-run: ${skipped.join(', ') || 'none'}${nothingChanged ? '; nothing changed -> previous PASS stands, verifier not re-run' : ''}`)

  const wholeScope = () => baseHeadsForNever ? `Read the whole change. ${wholeChangeScope(baseHeadsForNever)}` : `${HEADS_UNKNOWN} Read the whole change: ${diffCommands}`
  const deltaScope = () => (roundHeadsUsable ? `This is a re-run. ${rerunScope(roundHeads, delta.paths)}` : `${HEADS_UNKNOWN} This is a re-run. Read only these paths changed this round (use the same commands restricted to them): ${delta.paths.join(', ')}.`) + ` ${RERUN_NOTE}`
  const scope = name => {
    if (reviewerState[name] === 'never' || !deltaUsable) return wholeScope()
    return emptyDelta ? NOTHING_CHANGED_SCOPE : deltaScope()
  }
  const nothingChangedNote = emptyDelta
    ? `Nothing changed this round: the implementer reports your previous BLOCKING finding does not hold. Its report: ${String(impl.report).slice(0, 1500)}\nConfirm the finding with the command and output that proves it, or withdraw it.\n`
    : ''
  const results = await parallel([
    () => nothingChanged ? Promise.resolve(lastVerifier) : agent(`Workorder: ${A.planPath}. Run its acceptance criteria and report what they printed.${VERIFIER_CRITERIA_NOTE}${VERIFIER_CONTEXT_NOTE}`,
      { label: `verifier:r${n}`, phase: 'Verify', agentType: 'verifier', schema: VERIFIER_SCHEMA }),
    ...toRun.map(name => () => agent(
      `You are reviewing a change. You are NOT given the workorder; this is its intent:\n${A.goalExcerpt}\n${OUT_OF_SCOPE_NOTE}\n${scope(name)}\n` +
      `${reviewerState[name] === 'blocking' ? priorNote(lastFindings[name], emptyDelta ? 'This is the finding the implementer disputes.' : PRIOR_ASK) + nothingChangedNote : ''}` +
      (name === 'instrument-blindness-reviewer' && A.researchHeadings ? `Research findings to check are recorded in ${A.contextPath} under: ${A.researchHeadings}. Read only those subsections.\n` : '') +
      `The verifier runs the acceptance criteria in parallel: do not re-run test suites or builds; run one targeted test only if a finding depends on its result. ` +
      `Mark every finding BLOCKING or NON-BLOCKING; set plan_defect only when no implementation of the plan as written could satisfy its Goal -- a missing assert, pin or sentence the plan did not forbid goes to the implementer, not plan_defect; lead the summary with "no blocking findings" when true.`,
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
  rounds.push(record)

  const clean = !blocking.length && !planDefect && (verdict === 'PASS' || verdict === 'PASS-PENDING-HUMAN')
  const rec = await recordState(n, roundBlock(n, record), stateBlock(n, record, clean, planDefect))
  const wrote = rec.wrote
  // A dropped line is repaired before anything reads it: the next round's
  // verifier takes its gate tokens from this very block.
  if (rec.lost.length) return { ...stateLost(n, rec, planDefect ? 'PLAN-DEFECT' : clean ? verifier.verdict : 'continue'), rounds }

  if (planDefect) return { outcome: 'PLAN-DEFECT', round: n, rounds }
  if (clean) return { outcome: verdict, round: n, pending_human: pendingHuman, rounds }
  carried = wrote && wrote.written ? null : { failed, blocking }
}

return { outcome: 'CAP', detail: `${ROUND_CAP} implement->verify rounds used; split the open findings into a new workorder`, rounds }
