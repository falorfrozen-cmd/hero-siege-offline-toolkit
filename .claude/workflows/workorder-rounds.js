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
//   implementerModel,                   // 'sonnet' | 'opus', from step 0.5 triage
//   round,                              // the round to start at (State's `round:`)
//   reviewers: { '<name>': 'never' | 'clean' | 'blocking' },   // applicable reviewers and their last verdict
//   submodules: ['ForgePact', ...],     // dirs whose own diff the reviewers must read, relative to repoRoot
//   researchHeadings,                   // '###' heading(s) in the context file recording a research finding, for instrument-blindness-reviewer
//   repoRoot,                           // absolute path to the repo under change, when it isn't this driver's CWD
//   baseHeads,                          // { '.': sha, 'ForgePact': sha, ... }, copied from '## State' > 'round base:'
//                                       // -- the WORKORDER's own starting heads, for a reviewer that has never run
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
    }, required: ['criterion', 'status', 'evidence'] } },
    pending_human: { type: 'array', items: { type: 'string' } },
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
const SCRIBE_SCHEMA = { type: 'object', properties: { written: { type: 'boolean' }, note: { type: 'string' } }, required: ['written', 'note'] }

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
const findingLine = f => `- [${f.reviewer}] ${f.where}: ${f.problem} — evidence: ${f.evidence}`
const roundBlock = (n, record) => {
  const lines = [`### Round ${n}`, '', `verifier: ${record.verifier}`]
  for (const c of record.failed) lines.push(`- FAILED ${c.criterion}: ${c.evidence}`)
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

const scribe = (n, block, state) => agent(
  `You are a scribe for the workorder '${SLUG}'. In ${A.contextPath}, append this block verbatim under '## Log' ` +
  `(if a '### Round ${n}' heading is already there, append under it instead of duplicating it):\n\n${block}\n\n` +
  `In ${A.planPath} under '## State', replace the round/phase/reviewers/open-defects lines with exactly these lines, changing nothing else:\n\n${state}\n\n` +
  `Paste both blocks verbatim with the Edit tool. Do not reword, relabel, merge lists, or change any count in a heading.`,
  { label: `scribe:r${n}`, phase: 'Record', model: 'haiku', effort: 'low', schema: SCRIBE_SCHEMA })

let reviewerState = { ...A.reviewers }
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
    (n > (A.round || 0) || carried ? `You are re-entered after a defect: read '## Log' > '### Round ${n - 1}' for the evidence before anything else. ` : '') +
    (carried ? `The scribe could not write the evidence, so it is here verbatim: ${JSON.stringify(carried)} ` : '') +
    `Return your usual verdict; put the PLAN-DEFECT evidence block or the ADVICE-NEEDED request, verbatim, in 'evidence'/'question'.`,
    { label: `implementer:r${n}`, phase: 'Implement', agentType: 'implementer', model: A.implementerModel || 'sonnet', schema: IMPL_SCHEMA })
  if (!impl) return { outcome: 'AGENT-FAILED', round: n, detail: 'implementer returned nothing', rounds }
  if (impl.verdict !== 'IMPL-DONE') {
    await scribe(n, implBlock(n, impl), `round: ${n}\nphase: blocked`)
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
  const nothingChanged = deltaUsable && delta.paths.length === 0 && !!prev && prev.verifier === 'PASS' && !!lastVerifier

  // A reviewer that has never run, or was blocking, always runs. A clean one
  // runs when its trigger matches the delta — or when the delta is unusable.
  const toRun = Object.keys(reviewerState).filter(name =>
    reviewerState[name] !== 'clean' || !deltaUsable || (TRIGGERS[name] || (() => true))(delta))
  const skipped = Object.keys(reviewerState).filter(name => !toRun.includes(name))
  log(`round ${n}: delta ${deltaUsable ? delta.paths.length + ' paths' : 'UNUSABLE -> all reviewers'}; running ${toRun.join(', ') || 'none'}; not re-run: ${skipped.join(', ') || 'none'}${nothingChanged ? '; nothing changed -> previous PASS stands, verifier not re-run' : ''}`)

  const scope = name => reviewerState[name] === 'never' || !deltaUsable
    ? (baseHeadsForNever ? `Read the whole change. ${wholeChangeScope(baseHeadsForNever)}` : `${HEADS_UNKNOWN} Read the whole change: ${diffCommands}`)
    : (roundHeadsUsable ? `This is a re-run. ${rerunScope(roundHeads, delta.paths)}` : `${HEADS_UNKNOWN} This is a re-run. Read only these paths changed this round (use the same commands restricted to them): ${delta.paths.join(', ')}`)
  const nothingChangedNote = nothingChanged
    ? `Nothing changed this round: the implementer reports your previous BLOCKING finding does not hold. Its report: ${String(impl.report).slice(0, 1500)}\nConfirm the finding with the command and output that proves it, or withdraw it.\n`
    : ''
  const results = await parallel([
    () => nothingChanged ? Promise.resolve(lastVerifier) : agent(`Workorder: ${A.planPath}. Run its acceptance criteria and report what they printed.`,
      { label: `verifier:r${n}`, phase: 'Verify', agentType: 'verifier', schema: VERIFIER_SCHEMA }),
    ...toRun.map(name => () => agent(
      `You are reviewing a change. You are NOT given the workorder; this is its intent:\n${A.goalExcerpt}\n${scope(name)}\n${nothingChangedNote}` +
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

  for (const { name, r } of reviews) reviewerState[name] = r.blocking.length ? 'blocking' : 'clean'
  const blocking = reviews.flatMap(({ name, r }) => r.blocking.map(f => ({ reviewer: name, ...f })))
  const nonBlocking = reviews.flatMap(({ name, r }) => r.non_blocking.map(f => ({ reviewer: name, ...f })))
  const planDefect = verifier.verdict === 'PLAN-DEFECT' || reviews.some(x => x.r.plan_defect)
  const failed = verifier.criteria.filter(c => c.status === 'fail')
  const record = { round: n, verifier: verifier.verdict, failed, pending_human: verifier.pending_human, blocking, nonBlocking, notReRun: skipped, reviewerState: { ...reviewerState } }
  rounds.push(record)

  const clean = !blocking.length && !planDefect && (verifier.verdict === 'PASS' || verifier.verdict === 'PASS-PENDING-HUMAN')
  const wrote = await scribe(n, roundBlock(n, record), stateBlock(n, record, clean, planDefect))

  if (planDefect) return { outcome: 'PLAN-DEFECT', round: n, rounds }
  if (clean) return { outcome: verifier.verdict, round: n, rounds }
  carried = wrote && wrote.written ? null : { failed, blocking }
}

return { outcome: 'CAP', detail: `${ROUND_CAP} implement->verify rounds used; split the open findings into a new workorder`, rounds }
