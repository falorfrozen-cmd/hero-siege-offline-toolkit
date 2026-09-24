// Dry-runs workorder-rounds.js against stub agents:
//   node --test .claude/workflows/workorder-rounds.test.mjs
// (name the file — `node --test <dir>` does not resolve on Windows here.)
//
// The script only runs for real inside the Workflow tool, where a routing bug
// costs agent spawns to discover. The first dry run found the reviewer trigger
// negated — it skipped the guard whose paths had changed and ran the ones that
// had not — so the routing table is pinned here, with a control on each side.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const src = readFileSync(fileURLToPath(new URL('./workorder-rounds.js', import.meta.url)), 'utf8')
  .replace(/^export const meta/m, 'const meta')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const script = new AsyncFunction('args', 'agent', 'parallel', 'pipeline', 'phase', 'log', 'budget', 'workflow', src)

const DELTA = (paths, extra = {}) => ({ exit_code: 0, paths, instrumentContent: false, sdkContent: false, files_checked: paths.length, files_missing: 0, raw_output: '', ...extra })
const HEADS = (list, extra = {}) => ({ exit_code: 0, heads: list, raw_output: '', ...extra })
const CLEAN = { blocking: [], non_blocking: [], plan_defect: false, summary: 'no blocking findings' }
const DONE = { verdict: 'IMPL-DONE', report: '', evidence: '', progress_so_far: '' }
const PASS = { verdict: 'PASS', criteria: [], pending_human: [] }
const BASE = {
  slug: 'zz', planPath: 'p.md', contextPath: 'c.md', checkoutRoot: 'C:/wt/here', goalExcerpt: 'g', implementerModel: 'sonnet', round: 0,
  reviewers: { 'docs-sync-reviewer': 'never', 'decompile-output-guard': 'never', 'instrument-blindness-reviewer': 'never' },
}

async function run(args, reply) {
  const calls = []
  const agent = async (prompt, opts) => { calls.push(opts.label); return reply(opts.label, prompt, opts) }
  const parallel = thunks => Promise.all(thunks.map(t => t().catch(() => null)))
  const result = await script(args, agent, parallel, null, () => {}, () => {}, {}, null)
  return { result, calls }
}

const standard = (overrides = {}) => label => {
  for (const [prefix, value] of Object.entries(overrides)) if (label.startsWith(prefix)) return typeof value === 'function' ? value(label) : value
  if (label.startsWith('snapshot')) return DELTA([]) // no `heads` field by default -> the heads-unavailable fallback path
  if (label.startsWith('delta')) return DELTA([])
  if (label.startsWith('implementer')) return DONE
  if (label.startsWith('verifier')) return PASS
  if (label.startsWith('scribe')) return { written: true, note: '' }
  return CLEAN
}

test('round 0 runs every applicable reviewer and passes', async () => {
  const { result, calls } = await run(BASE, standard())
  assert.equal(result.outcome, 'PASS')
  for (const name of Object.keys(BASE.reviewers)) assert.ok(calls.includes(`${name}:r0`), name)
})

test('a test-only delta re-runs the decompile guard and nothing else', async () => {
  let verifies = 0
  const { result, calls } = await run(BASE, standard({
    delta: DELTA(['tests/test_x.py']),
    verifier: () => (verifies++ === 0 ? { verdict: 'IMPL-DEFECT', criteria: [{ criterion: 'c', status: 'fail', evidence: 'e' }], pending_human: [] } : PASS),
  }))
  assert.equal(result.outcome, 'PASS')
  assert.equal(result.round, 1)
  assert.ok(calls.includes('decompile-output-guard:r1'), 'a .py file changed: the guard must run')
  assert.ok(!calls.includes('docs-sync-reviewer:r1'), 'tests only: docs-sync must not re-run')
  assert.ok(!calls.includes('instrument-blindness-reviewer:r1'))
  assert.deepEqual(result.rounds[1].notReRun.sort(), ['docs-sync-reviewer', 'instrument-blindness-reviewer'])
})

test('a plugin path or a hook-shaped string re-runs the instrument reviewer', async () => {
  const state = { ...BASE, round: 1, reviewers: { 'instrument-blindness-reviewer': 'clean', 'tauri-command-reviewer': 'clean' } }
  let r = await run(state, standard({ delta: DELTA(['ForgePact/plugin/ModuleMain.cpp']) }))
  assert.ok(r.calls.includes('instrument-blindness-reviewer:r1'))
  assert.ok(!r.calls.includes('tauri-command-reviewer:r1'))
  r = await run(state, standard({ delta: DELTA(['tools/probe.py'], { instrumentContent: true }) }))
  assert.ok(r.calls.includes('instrument-blindness-reviewer:r1'))
  r = await run(state, standard({ delta: DELTA(['docs/submodules/ForgePact/instructions.md']) }))
  assert.ok(r.calls.includes('instrument-blindness-reviewer:r1'))
})

test('a reviewer that was blocking runs again whatever the delta says', async () => {
  const state = { ...BASE, round: 1, reviewers: { 'tauri-command-reviewer': 'blocking' } }
  const { calls } = await run(state, standard({ delta: DELTA(['README.md']) }))
  assert.ok(calls.includes('tauri-command-reviewer:r1'))
})

test('an unusable delta runs every reviewer', async () => {
  const state = { ...BASE, round: 1, reviewers: { 'docs-sync-reviewer': 'clean', 'decompile-output-guard': 'clean' } }
  const { result, calls } = await run(state, standard({ snapshot: { ...DELTA([]), exit_code: 3 }, delta: { ...DELTA([]), exit_code: 3 } }))
  assert.equal(result.outcome, 'PASS')
  assert.ok(calls.includes('docs-sync-reviewer:r1') && calls.includes('decompile-output-guard:r1'))
})

test('a delta that reports most files missing (exit_code 3) runs every reviewer', async () => {
  // 2c: the delta agent itself decides "too many files missing to trust" and
  // reports exit_code 3 -- the same fallback as an unusable snapshot/delta.
  const state = { ...BASE, round: 1, reviewers: { 'docs-sync-reviewer': 'clean', 'decompile-output-guard': 'clean' } }
  const { result, calls } = await run(state, standard({
    delta: { exit_code: 3, paths: ['a.md', 'b.md', 'c.md'], instrumentContent: false, sdkContent: false, files_checked: 1, files_missing: 2, raw_output: '' },
  }))
  assert.equal(result.outcome, 'PASS')
  assert.ok(calls.includes('docs-sync-reviewer:r1') && calls.includes('decompile-output-guard:r1'))
})

test('a reviewer that returns nothing is never counted as clean', async () => {
  const { result } = await run(BASE, standard({ 'instrument-blindness-reviewer': null }))
  assert.equal(result.outcome, 'AGENT-FAILED')
  assert.match(result.detail, /instrument-blindness-reviewer/)
})

test('PLAN-DEFECT and ADVICE-NEEDED hand back to the driver without verifying', async () => {
  for (const verdict of ['PLAN-DEFECT', 'ADVICE-NEEDED']) {
    const { result, calls } = await run(BASE, standard({ implementer: { ...DONE, verdict, evidence: 'ev' } }))
    assert.equal(result.outcome, verdict)
    assert.ok(!calls.some(c => c.startsWith('verifier')))
  }
})

test('an empty delta after a PASS skips the verifier and re-runs only the blocking reviewer', async () => {
  let docsSeen = 0
  const { result, calls } = await run(BASE, standard({
    delta: DELTA([]),
    'docs-sync-reviewer': () => (docsSeen++ === 0 ? { ...CLEAN, blocking: [{ where: 'a', problem: 'claimed', evidence: 'x' }] } : CLEAN),
  }))
  assert.equal(result.outcome, 'PASS')
  assert.equal(result.round, 1)
  assert.ok(!calls.includes('verifier:r1'), 'nothing changed: the round-0 PASS stands')
  assert.ok(calls.includes('docs-sync-reviewer:r1'), 'the blocking reviewer confirms or withdraws')
  assert.ok(!calls.includes('decompile-output-guard:r1') && !calls.includes('instrument-blindness-reviewer:r1'))
})

test('an empty delta on a fresh invocation still runs the verifier', async () => {
  const state = { ...BASE, round: 1, reviewers: { 'docs-sync-reviewer': 'blocking' } }
  const { calls } = await run(state, standard({ delta: DELTA([]) }))
  assert.ok(calls.includes('verifier:r1'), 'no previous verdict to reuse')
})

test('the delta dispatch says an empty result is a valid answer', async () => {
  const prompts = {}
  const reply = (label, prompt) => { prompts[label] = prompt; return standard()(label) }
  await run(BASE, reply)
  assert.match(prompts['delta:r0'], /An empty path list with exit code 0 is a valid answer/)
})

test('a blocking finding spends a round; a non-blocking one does not', async () => {
  let r = await run(BASE, standard({ 'docs-sync-reviewer': { ...CLEAN, non_blocking: [{ where: 'a', problem: 'nit', evidence: '' }] } }))
  assert.equal(r.result.outcome, 'PASS')
  assert.equal(r.result.round, 0)
  let seen = 0
  r = await run(BASE, standard({ 'docs-sync-reviewer': () => (seen++ === 0 ? { ...CLEAN, blocking: [{ where: 'a', problem: 'wrong', evidence: 'x' }] } : CLEAN) }))
  assert.equal(r.result.outcome, 'PASS')
  assert.equal(r.result.round, 1)
})

test('three failing rounds stop at the cap', async () => {
  const fail = { verdict: 'IMPL-DEFECT', criteria: [{ criterion: 'c', status: 'fail', evidence: 'e' }], pending_human: [] }
  const { result, calls } = await run(BASE, standard({ verifier: fail }))
  assert.equal(result.outcome, 'CAP')
  assert.equal(calls.filter(c => c.startsWith('implementer')).length, 3)
})

test('when the scribe cannot write, the launch stops as SCRIBE-FAILED carrying the evidence', async () => {
  for (const scribe of [{ written: false, note: 'edit failed' }, null]) {
    const { result, calls } = await run(BASE, standard({
      scribe,
      verifier: { verdict: 'IMPL-DEFECT', criteria: [{ criterion: 'c', status: 'fail', evidence: 'REAL-OUTPUT-42' }], pending_human: [] },
    }))
    assert.equal(result.outcome, 'SCRIBE-FAILED')
    assert.equal(result.then, 'continue')
    assert.match(result.log, /REAL-OUTPUT-42/)
    assert.match(result.state, /^round: 1$/m)
    assert.ok(!calls.includes('implementer:r1'), 'no round may start from a Log that was never written')
  }
})

test('omitted repoRoot produces the exact commands as before', async () => {
  const prompts = {}
  const reply = (label, prompt) => { prompts[label] = prompt; return standard()(label) }
  await run({ ...BASE, submodules: ['ForgePact'] }, reply)
  assert.equal(prompts['snapshot:r0'],
    'Run exactly: py -3 .claude/skills/workorder/round_delta.py snapshot zz 0  — then report its exit code and output. ' +
    'Then run exactly: py -3 .claude/skills/workorder/round_delta.py heads zz 0  — report its exit code (3 if either command exited 3) and each printed line, split into repo and sha at the first tab, as heads: [{repo, sha}]. Edit nothing.')
  assert.ok(prompts['delta:r0'].startsWith(
    'Run exactly: py -3 .claude/skills/workorder/round_delta.py delta zz 0  — report its exit code'))
  // No usable heads (the stub snapshot omits `heads`) -> the legacy HEAD-relative
  // whole-change commands, unchanged since before baseHeads existed.
  assert.ok(prompts['docs-sync-reviewer:r0'].includes(
    'Read the whole change: git status --porcelain -uall ; git diff HEAD ; git -C ForgePact status --porcelain -uall ; git -C ForgePact diff HEAD'))
})

test('a set repoRoot rewrites the delta command and every diff command', async () => {
  const prompts = {}
  const reply = (label, prompt) => { prompts[label] = prompt; return standard()(label) }
  await run({ ...BASE, repoRoot: '/repo root', submodules: ['ForgePact'] }, reply)
  assert.ok(prompts['snapshot:r0'].includes('snapshot zz 0 --root "/repo root"'))
  assert.ok(prompts['delta:r0'].includes('delta zz 0 --root "/repo root"'))
  assert.ok(prompts['docs-sync-reviewer:r0'].includes(
    'Read the whole change: git -C "/repo root" status --porcelain -uall ; git -C "/repo root" diff HEAD ; ' +
    'git -C "/repo root/ForgePact" status --porcelain -uall ; git -C "/repo root/ForgePact" diff HEAD'))
})

test('submodules combine with repoRoot; an already-absolute entry is left alone', async () => {
  const prompts = {}
  const reply = (label, prompt) => { prompts[label] = prompt; return standard()(label) }
  await run({ ...BASE, repoRoot: 'C:/repo', submodules: ['C:/other/ForgePact', 'HSCraftSim'] }, reply)
  assert.ok(prompts['docs-sync-reviewer:r0'].includes(
    'git -C "C:/other/ForgePact" status --porcelain -uall ; git -C "C:/other/ForgePact" diff HEAD ; ' +
    'git -C "C:/repo/HSCraftSim" status --porcelain -uall ; git -C "C:/repo/HSCraftSim" diff HEAD'))
  assert.ok(!prompts['docs-sync-reviewer:r0'].includes('C:/repo/C:/other'))
})

// The plan_defect clause a reviewer is dispatched with must be the exact
// SKILL.md § "SKILL.md" (a) rule (SPEC.md § 4) -- a plan-shaped defect is one
// no implementation of the plan could have satisfied, not merely a finding
// the plan happened not to spell out. Pinned here so the two cannot drift:
// a reviewer following a looser sentence would route an implementer's own
// missing assert back as a costly replan instead of a normal fix.
test('the reviewer dispatch states the narrow plan_defect rule', async () => {
  const prompts = {}
  const reply = (label, prompt) => { prompts[label] = prompt; return standard()(label) }
  await run(BASE, reply)
  assert.match(prompts['docs-sync-reviewer:r0'],
    /set plan_defect only when no implementation of the plan as written could satisfy its Goal/)
  assert.match(prompts['docs-sync-reviewer:r0'],
    /a missing assert, pin or sentence the plan did not forbid goes to the implementer, not plan_defect/)
})

// Measured on a replayed round: given a correct diff, reviewers still spent
// 5-6 calls each re-running test suites the verifier runs in parallel.
test('the reviewer dispatch tells reviewers not to re-run suites or builds', async () => {
  const prompts = {}
  const reply = (label, prompt) => { prompts[label] = prompt; return standard()(label) }
  await run(BASE, reply)
  assert.match(prompts['instrument-blindness-reviewer:r0'], /do not re-run test suites or builds/)
  assert.doesNotMatch(prompts['verifier:r0'], /do not re-run test suites or builds/, 'the verifier is the one that runs them')
})

test('missing arguments are refused', async () => {
  const { result } = await run({ slug: 'zz' }, standard())
  assert.equal(result.outcome, 'BAD-ARGS')
})

// --- 2a: reviewers diff from the recorded base -----------------------------

test('read commands use the WORKORDER base sha for a never reviewer and this round\'s own sha for a re-run', async () => {
  const prompts = {}
  const reply = (label, prompt) => { prompts[label] = prompt; return standard({ snapshot: HEADS([{ repo: '.', sha: 'BASE-SHA' }]) })(label) }
  await run({ ...BASE, reviewers: { 'docs-sync-reviewer': 'never' } }, reply)
  assert.ok(prompts['docs-sync-reviewer:r0'].includes('git -C . diff BASE-SHA'))
  assert.ok(prompts['docs-sync-reviewer:r0'].includes('log --oneline BASE-SHA..HEAD'))

  const prompts2 = {}
  const reply2 = (label, prompt) => {
    prompts2[label] = prompt
    return standard({ snapshot: HEADS([{ repo: '.', sha: 'ROUND-SHA' }]), delta: DELTA(['README.md']) })(label)
  }
  await run({ ...BASE, round: 1, reviewers: { 'docs-sync-reviewer': 'clean' } }, reply2)
  assert.ok(prompts2['docs-sync-reviewer:r1'].includes('git -C . diff ROUND-SHA -- README.md'))
  assert.ok(!prompts2['docs-sync-reviewer:r1'].includes('log --oneline'), 'a re-run reads only the delta, not the log')
})

test('re-run commands split delta paths per repo from this round\'s own heads, submodule prefix stripped', async () => {
  const prompts = {}
  const reply = (label, prompt) => {
    prompts[label] = prompt
    return standard({
      snapshot: HEADS([{ repo: '.', sha: 'aaa111' }, { repo: 'ForgePact', sha: 'bbb222' }]),
      delta: DELTA(['README.md', 'ForgePact/src/x.py']),
    })(label)
  }
  const state = { ...BASE, round: 1, submodules: ['ForgePact'], reviewers: { 'docs-sync-reviewer': 'clean' } }
  await run(state, reply)
  assert.ok(prompts['docs-sync-reviewer:r1'].includes('git -C . diff aaa111 -- README.md'))
  assert.ok(prompts['docs-sync-reviewer:r1'].includes('git -C ForgePact diff bbb222 -- src/x.py'))
})

test('repoRoot paths are quoted in the head-based commands', async () => {
  const prompts = {}
  const reply = (label, prompt) => {
    prompts[label] = prompt
    return standard({ snapshot: HEADS([{ repo: '.', sha: 'aaa' }, { repo: 'ForgePact', sha: 'bbb' }]) })(label)
  }
  await run({ ...BASE, repoRoot: '/repo root', submodules: ['ForgePact'] }, reply)
  assert.ok(prompts['docs-sync-reviewer:r0'].includes('git -C "/repo root" diff aaa'))
  assert.ok(prompts['docs-sync-reviewer:r0'].includes('git -C "/repo root/ForgePact" diff bbb'))
})

test('args.baseHeads wins over the first snapshot\'s heads for a never reviewer', async () => {
  const prompts = {}
  const reply = (label, prompt) => { prompts[label] = prompt; return standard({ snapshot: HEADS([{ repo: '.', sha: 'FROM-SNAPSHOT' }]) })(label) }
  await run({ ...BASE, baseHeads: { '.': 'FROM-BASEHEADS' } }, reply)
  assert.ok(prompts['docs-sync-reviewer:r0'].includes('git -C . diff FROM-BASEHEADS'))
  assert.ok(!prompts['docs-sync-reviewer:r0'].includes('FROM-SNAPSHOT'))
})

test('missing heads (exit_code 3) produce the loud fallback', async () => {
  const prompts = {}
  const reply = (label, prompt) => { prompts[label] = prompt; return standard({ snapshot: { exit_code: 3, heads: [], raw_output: '' } })(label) }
  await run(BASE, reply)
  assert.match(prompts['docs-sync-reviewer:r0'], /base commit is unknown/)
  assert.ok(prompts['docs-sync-reviewer:r0'].includes('Read the whole change: git status --porcelain -uall ; git diff HEAD'))
})

// --- 2b: the scribe pastes, it does not compose -----------------------------

// Pinned 2026-09-19 after an unrestricted scribe acted on a round's findings
// instead of only recording them (tools/workorder_audit.py R16). Every
// scribe dispatch -- the round-end one, and the one written when the
// implementer returns something other than IMPL-DONE -- must run as the
// restricted `scribe` agent type, never the implementer's.
test('every scribe dispatch runs as the restricted scribe agent type with the required prompt guardrails', async () => {
  const SCRIBE_STRINGS = [
    'Do not act on any finding in it: record it only.',
    'Edit nothing except these two files.',
    'Never run git',
    'If either file cannot be read, do not create it',
    'never resolve them against another checkout or directory',
  ]
  const check = (dispatches, label) => {
    const d = dispatches[label]
    assert.ok(d, `no dispatch captured for ${label}`)
    assert.equal(d.opts.agentType, 'scribe')
    assert.equal(d.opts.model, 'haiku')
    for (const s of SCRIBE_STRINGS) assert.ok(d.prompt.includes(s), `${label} prompt missing: ${JSON.stringify(s)}`)
  }

  // The round-end scribe, dispatched after a normal (non-terminal) round.
  {
    const dispatches = {}
    const reply = (label, prompt, opts) => {
      if (label.startsWith('scribe') || label.startsWith('implementer')) dispatches[label] = { prompt, opts }
      return standard({
        verifier: () => ({ verdict: 'IMPL-DEFECT', criteria: [{ criterion: 'c', status: 'fail', evidence: 'e' }], pending_human: [] }),
      })(label)
    }
    await run(BASE, reply)
    check(dispatches, 'scribe:r0')
    assert.equal(dispatches['implementer:r0'].opts.agentType, 'implementer', 'control: the implementer keeps its own agent type')
  }

  // The scribe dispatched for an implementer's non-IMPL-DONE verdict.
  {
    const dispatches = {}
    const reply = (label, prompt, opts) => {
      if (label.startsWith('scribe') || label.startsWith('implementer')) dispatches[label] = { prompt, opts }
      return standard({ implementer: { verdict: 'PLAN-DEFECT', report: '', evidence: 'ev', progress_so_far: '' } })(label)
    }
    await run(BASE, reply)
    check(dispatches, 'scribe:r0')
  }
})

test('the scribe payload is the verbatim block with separate BLOCKING/NON-BLOCKING headings and counts', async () => {
  const nb = i => ({ where: `w${i}`, problem: `p${i}`, evidence: `e${i}` })
  const prompts = {}
  const reply = (label, prompt) => {
    prompts[label] = prompt
    return standard({
      'docs-sync-reviewer': { blocking: [{ where: 'w', problem: 'wrong', evidence: 'ev' }], non_blocking: [], plan_defect: false, summary: 'x' },
      'decompile-output-guard': { blocking: [], non_blocking: [nb(0), nb(1), nb(2)], plan_defect: false, summary: 'x' },
      'instrument-blindness-reviewer': { blocking: [], non_blocking: [nb(3), nb(4)], plan_defect: false, summary: 'x' },
    })(label)
  }
  await run(BASE, reply)
  assert.match(prompts['scribe:r0'], /BLOCKING \(1\)/)
  assert.match(prompts['scribe:r0'], /NON-BLOCKING \(5\)/)
  assert.ok(!/BLOCKING \(6\)/.test(prompts['scribe:r0']), 'must not merge blocking and non-blocking into one count')
})

// --- 2d: a reviewer is told what not to spend calls on ----------------------

test('a reviewer is told the Out-of-scope list is not a checklist; the verifier is not', async () => {
  const prompts = {}
  const reply = (label, prompt) => { prompts[label] = prompt; return standard()(label) }
  await run(BASE, reply)
  assert.match(prompts['docs-sync-reviewer:r0'], /Do not spend calls proving each one was left untouched/)
  assert.doesNotMatch(prompts['verifier:r0'], /Out-of-scope list/, 'proving scope is exactly the verifier\'s job')
})

test('a blocking reviewer gets its own finding back next round; a clean one that re-runs does not', async () => {
  let docsSeen = 0
  const prompts = {}
  const reply = (label, prompt) => {
    prompts[label] = prompt
    return standard({
      snapshot: HEADS([{ repo: '.', sha: 'SHA' }]),
      delta: DELTA(['README.md']),
      'docs-sync-reviewer': () => (docsSeen++ === 0
        ? { ...CLEAN, blocking: [{ where: 'notes.md:3', problem: 'TAGLINE-CLAIMS-A-FIX', evidence: 'x' }] } : CLEAN),
    })(label)
  }
  const { result } = await run(BASE, reply)
  assert.equal(result.round, 1)
  assert.doesNotMatch(prompts['docs-sync-reviewer:r0'], /previous BLOCKING finding/, 'round 0 has no previous finding')
  assert.doesNotMatch(prompts['docs-sync-reviewer:r0'], /do not re-read earlier commits/, 'a reviewer that has never run reads the whole change')
  assert.match(prompts['docs-sync-reviewer:r1'], /Your previous BLOCKING finding: \[notes\.md:3\] TAGLINE-CLAIMS-A-FIX/)
  assert.match(prompts['docs-sync-reviewer:r1'], /do not re-read earlier commits/)
  // decompile-output-guard re-runs on a .md delta but was clean: nothing to hand back.
  assert.ok(prompts['decompile-output-guard:r1'], 'control: the clean reviewer did re-run')
  assert.doesNotMatch(prompts['decompile-output-guard:r1'], /previous BLOCKING finding/)
  assert.match(prompts['decompile-output-guard:r1'], /do not re-read earlier commits/)
})

test('a fresh launch hands a blocking reviewer the findings the driver copied from the Log', async () => {
  const prompts = {}
  const reply = (label, prompt) => { prompts[label] = prompt; return standard({ delta: DELTA(['README.md']) })(label) }
  const state = {
    ...BASE, round: 1, reviewers: { 'docs-sync-reviewer': 'blocking', 'decompile-output-guard': 'clean' },
    priorFindings: {
      'docs-sync-reviewer': [{ where: 'a.md', problem: 'FIRST' }, { where: 'b.md', problem: 'SECOND' }],
      // A stale entry for a reviewer that has since gone clean: the gate is its state, not the entry.
      'decompile-output-guard': [{ where: 'c.md', problem: 'STALE-CLEARED' }],
    },
  }
  await run(state, reply)
  assert.match(prompts['docs-sync-reviewer:r1'], /Your previous BLOCKING findings: \[a\.md\] FIRST \|\| \[b\.md\] SECOND/)
  assert.ok(prompts['decompile-output-guard:r1'], 'control: the clean reviewer did re-run')
  assert.doesNotMatch(prompts['decompile-output-guard:r1'], /previous BLOCKING finding|STALE-CLEARED|FIRST/)
  // No priorFindings passed: the dispatch degrades to what it was, it does not invent one.
  const bare = {}
  await run({ ...state, priorFindings: undefined }, (label, prompt) => { bare[label] = prompt; return standard({ delta: DELTA(['README.md']) })(label) })
  assert.doesNotMatch(bare['docs-sync-reviewer:r1'], /previous BLOCKING finding/)
})

test('the verifier is given the context path and the one command that opens a cited heading', async () => {
  const prompts = {}
  const reply = (label, prompt) => { prompts[label] = prompt; return standard()(label) }
  await run(BASE, reply)
  assert.ok(prompts['verifier:r0'].includes(`section.py "c.md" '<heading>'`), 'single-quoted: a heading with backticks survives Bash')
  assert.match(prompts['verifier:r0'], /never read it whole/)
  // A legacy single-file plan keeps its cited sections in the plan itself.
  await run({ ...BASE, contextPath: 'p.md' }, reply)
  assert.ok(prompts['verifier:r0'].includes(`section.py "p.md" '<heading>'`))
  assert.doesNotMatch(prompts['verifier:r0'], /Context file:/)
})

test('when nothing changed, the blocking reviewer is not pointed at a diff that does not exist', async () => {
  let docsSeen = 0
  const prompts = {}
  const reply = (label, prompt) => {
    prompts[label] = prompt
    return standard({
      snapshot: HEADS([{ repo: '.', sha: 'SHA' }]),
      delta: DELTA([]),
      'docs-sync-reviewer': () => (docsSeen++ === 0 ? { ...CLEAN, blocking: [{ where: 'a', problem: 'DISPUTED', evidence: 'x' }] } : CLEAN),
    })(label)
  }
  await run(BASE, reply)
  const p = prompts['docs-sync-reviewer:r1']
  assert.match(p, /nothing changed this round: there is no new diff/)
  assert.match(p, /\[a\] DISPUTED\nThis is the finding the implementer disputes\./)
  assert.doesNotMatch(p, /do not re-read earlier commits|from this diff/, 'the finding lives in the earlier commits')
  assert.match(p, /Confirm the finding with the command and output that proves it, or withdraw it/)
})

test('a fresh launch past round 0 tells the implementer it is re-entered; round 0 does not', async () => {
  const prompts = {}
  const reply = (label, prompt) => { prompts[label] = prompt; return standard()(label) }
  await run({ ...BASE, round: 1, reviewers: { 'docs-sync-reviewer': 'blocking' } }, reply)
  assert.match(prompts['implementer:r1'], /re-entered after a defect: read '## Log' > '### Round 0'/)
  // A relaunch after a PLAN-DEFECT raised in round 1 itself keeps `round: 1`,
  // and the newer evidence is under that round's own heading.
  assert.match(prompts['implementer:r1'], /and '### Round 1' if it is already there/)
  assert.match(prompts['implementer:r1'], /newer evidence\), for the evidence before anything else\. Return your usual verdict/)
  await run(BASE, reply)
  assert.doesNotMatch(prompts['implementer:r0'], /re-entered after a defect/)
})

test('an empty delta on a fresh launch gives the blocking reviewer no phantom diff either', async () => {
  // `nothingChanged` (verifier reuse) needs a previous PASS from this launch;
  // the reviewer's wording must not.
  const prompts = {}
  const reply = (label, prompt) => {
    prompts[label] = prompt
    return standard({ snapshot: HEADS([{ repo: '.', sha: 'SHA' }]), delta: DELTA([]) })(label)
  }
  const state = {
    ...BASE, round: 1, reviewers: { 'docs-sync-reviewer': 'blocking', 'decompile-output-guard': 'never' },
    priorFindings: { 'docs-sync-reviewer': [{ where: 'a', problem: 'FIRST' }] },
  }
  const { calls } = await run(state, reply)
  assert.ok(calls.includes('verifier:r1'), 'no previous verdict to reuse: the verifier still runs')
  const p = prompts['docs-sync-reviewer:r1']
  assert.match(p, /nothing changed this round: there is no new diff/)
  assert.match(p, /\[a\] FIRST\nThis is the finding the implementer disputes\./)
  assert.doesNotMatch(p, /from this diff|do not re-read earlier commits|This is a re-run\.  /)
  // A reviewer that has never run made no finding to dispute, and reads the whole change.
  assert.doesNotMatch(prompts['decompile-output-guard:r1'], /previous BLOCKING finding|Nothing changed this round/)
  assert.match(prompts['decompile-output-guard:r1'], /Read the whole change/)
})

test('the path list ends before the re-run note when the round base is unknown', async () => {
  const prompts = {}
  const reply = (label, prompt) => { prompts[label] = prompt; return standard({ delta: DELTA(['a.md', 'b.md']) })(label) }
  await run({ ...BASE, round: 1, reviewers: { 'docs-sync-reviewer': 'clean' } }, reply)
  assert.ok(prompts['docs-sync-reviewer:r1'].includes('restricted to them): a.md, b.md. Earlier rounds reviewed'))
})

// --- 2c: delta greps run in the repository ----------------------------------

test('the delta dispatch runs the content greps from the repo root', async () => {
  const prompts = {}
  const reply = (label, prompt) => { prompts[label] = prompt; return standard()(label) }
  await run(BASE, reply)
  assert.match(prompts['delta:r0'], /cd \./)
  assert.match(prompts['delta:r0'], /grep -lE/)
  await run({ ...BASE, repoRoot: '/repo root' }, reply)
  assert.match(prompts['delta:r0'], /cd "\/repo root"/)
})

test('the verifier is handed the criteria extraction, not left to read the plan whole', async () => {
  // 2026-09-22: 8 of 22 sessions failed R2 on a verifier reading a 30-42KB plan whole.
  const prompts = {}
  await run(BASE, (label, prompt) => { prompts[label] = prompt; return standard()(label) })
  assert.ok(prompts['verifier:r0'].includes(`section.py "p.md" 'Acceptance criteria'`))
  assert.ok(prompts['verifier:r0'].includes(`section.py "p.md" 'State'`))
  assert.match(prompts['verifier:r0'], /do not Read the plan whole/)
})

test('the implementer runs at opus unless triage says otherwise', async () => {
  const models = {}
  await run({ ...BASE, implementerModel: undefined }, (label, prompt, opts) => { models[label] = opts && opts.model; return standard()(label) })
  assert.equal(models['implementer:r0'], 'opus')
})

// --- 2e: State is merged, never replaced ------------------------------------
//
// Pinned 2026-09-23: handed four lines and told to replace them, the haiku
// scribe replaced the whole '## State' block with those four, so the next
// round's verifier read no `gates:` and reported gated criteria pending
// instead of running them. These stubs *apply* the scribe's instructions to an
// in-memory plan, so what survives a Record pass is measured, not assumed.
const PLAN_STATE = [
  'round: 0        phase: plan',
  'gates: `build: complete` (set 2026-09-23); `live1: complete`',
  'round base: round 0 = hub `f76ef98`, ForgePact `cb602e5`',
  'agents: planner-tier=opus',
  'reviewers: <none yet>',
  'open defects: none',
  'decisions in force: D1, D2 (context file, `### Decisions`)',
].join('\n')
const DRIVER_OWNED = /^(gates|round base|agents|decisions in force):/
const planFile = state => `---\nslug: zz\n---\n\n## State\n${state}\n\n## Goal\ng\n`
const stateOf = plan => plan.split('## State\n')[1].split('\n\n')[0]
const between = (s, a, b) => { const i = s.indexOf(a); return i < 0 ? null : s.slice(i + a.length, s.indexOf(b, i + a.length)) }
// A faithful scribe: pastes the whole block when handed one, else edits each
// keyed line in place (adding a key the State lacks at its end).
const faithfulScribe = file => prompt => {
  const before = stateOf(file.plan)
  const whole = between(prompt, 'already in it, verbatim:\n\n', '\n\nBefore your first Edit')
  let after
  if (whole !== null) after = whole
  else {
    const lines = before.split('\n')
    for (const u of between(prompt, 'to exactly these lines:\n\n', '\n\nUse one Edit').split('\n')) {
      const key = u.slice(0, u.indexOf(':') + 1)
      const i = lines.findIndex(l => l.startsWith(key))
      if (i >= 0) lines[i] = u; else lines.push(u)
    }
    after = lines.join('\n')
  }
  file.plan = file.plan.replace(`## State\n${before}\n`, `## State\n${after}\n`)
  return { written: true, note: '', state_before: before, state_after: after }
}
// The measured 2026-09-23 behaviour: the lines this round computed replace the
// whole block, and nothing else is kept.
const incidentScribe = file => prompt => {
  const before = stateOf(file.plan)
  const keys = [...(between(prompt, "this round's ", ' values merged') ?? '').matchAll(/`([^`]+)`/g)].map(m => m[1])
  const handed = between(prompt, 'to exactly these lines:\n\n', '\n\nUse one Edit') ??
    between(prompt, 'already in it, verbatim:\n\n', '\n\nBefore your first Edit').split('\n')
      .filter(l => keys.some(k => l.startsWith(k))).join('\n')
  file.plan = file.plan.replace(`## State\n${before}\n`, `## State\n${handed}\n`)
  return { written: true, note: '', state_before: before, state_after: handed }
}
const withPlan = (file, scribeFn, overrides = {}) => (label, prompt) =>
  label.startsWith('scribe') ? scribeFn(file)(prompt) : standard(overrides)(label)
const defectThenPass = () => {
  let v = 0
  return () => (v++ === 0 ? { verdict: 'IMPL-DEFECT', criteria: [{ criterion: 'c', status: 'fail', evidence: 'e' }], pending_human: [] } : PASS)
}

test('a gates: line survives a Record pass, and the round after it', async () => {
  const file = { plan: planFile(PLAN_STATE) }
  const prompts = {}
  const reply = withPlan(file, faithfulScribe, { verifier: defectThenPass() })
  const { result } = await run({ ...BASE, state: `## State\n${PLAN_STATE}\n` }, (label, prompt, opts) => { prompts[label] = prompt; return reply(label, prompt, opts) })
  assert.equal(result.outcome, 'PASS')
  assert.equal(result.round, 1)
  const lines = stateOf(file.plan).split('\n')
  for (const line of PLAN_STATE.split('\n').filter(l => DRIVER_OWNED.test(l))) assert.ok(lines.includes(line), `lost after two Record passes: ${line}`)
  assert.ok(lines.includes('round: 1') && lines.includes('phase: pass'), lines.join('\n'))
  assert.ok(!lines.some(l => /phase: plan/.test(l)), 'the combined `round: 0  phase: plan` line is replaced, not kept beside the new one')
  assert.equal(lines.filter(l => l.startsWith('round:')).length, 1)
  assert.ok(prompts['scribe:r0'].includes('gates: `build: complete`'), 'the scribe is handed the gates line, not asked to keep it from memory')
})

test('without args.state the scribe is told one Edit per line, and gates: still survives', async () => {
  const file = { plan: planFile(PLAN_STATE.replace('round: 0        phase: plan', 'round: 0\nphase: plan')) }
  const prompts = {}
  const reply = withPlan(file, faithfulScribe)
  const { result } = await run(BASE, (label, prompt, opts) => { prompts[label] = prompt; return reply(label, prompt, opts) })
  assert.equal(result.outcome, 'PASS')
  assert.match(prompts['scribe:r0'], /one Edit per line/)
  assert.match(prompts['scribe:r0'], /Never use an old_string spanning several lines/)
  assert.ok(stateOf(file.plan).split('\n').includes('gates: `build: complete` (set 2026-09-23); `live1: complete`'))
})

test('a scribe that drops gates: stops the launch as STATE-LOST before the next verifier', async () => {
  for (const state of [`## State\n${PLAN_STATE}`, undefined]) {
    const file = { plan: planFile(PLAN_STATE) }
    const { result, calls } = await run({ ...BASE, state }, withPlan(file, incidentScribe, { verifier: defectThenPass() }))
    const tag = `args.state ${state ? 'given' : 'absent'}`
    assert.equal(result.outcome, 'STATE-LOST', tag)
    assert.equal(result.then, 'continue')
    assert.ok(result.lost.some(l => l.startsWith('gates:')), JSON.stringify(result.lost))
    assert.ok(result.lost.some(l => l.startsWith('decisions in force:')), tag)
    assert.ok(result.state.includes('gates: `build: complete`') && /^round: 1$/m.test(result.state), result.state)
    assert.ok(!calls.includes('verifier:r1'), 'no verifier may read the damaged block')
  }
})

test('control: a faithful scribe on a clean pass reports no STATE-LOST', async () => {
  const file = { plan: planFile(PLAN_STATE) }
  const { result } = await run({ ...BASE, state: PLAN_STATE }, withPlan(file, faithfulScribe))
  assert.equal(result.outcome, 'PASS')
  assert.equal(result.lost, undefined)
})

test('the implementer-verdict Record pass keeps reviewers: and open defects:', async () => {
  const withReviewers = PLAN_STATE.replace('reviewers: <none yet>', 'reviewers: docs-sync-reviewer: blocking')
    .replace('open defects: none', 'open defects: docs-sync-reviewer: stale README')
  const blocked = { implementer: { ...DONE, verdict: 'PLAN-DEFECT', evidence: 'ev' } }
  {
    const file = { plan: planFile(withReviewers) }
    const { result } = await run({ ...BASE, state: withReviewers }, withPlan(file, faithfulScribe, blocked))
    assert.equal(result.outcome, 'PLAN-DEFECT')
    const lines = stateOf(file.plan).split('\n')
    assert.ok(lines.includes('phase: blocked'), lines.join('\n'))
    assert.ok(lines.includes('reviewers: docs-sync-reviewer: blocking') && lines.includes('open defects: docs-sync-reviewer: stale README'), lines.join('\n'))
  }
  {
    // Keeping only round/phase is what phase1c's scribe did on 2026-09-23.
    const file = { plan: planFile(withReviewers) }
    const { result } = await run({ ...BASE, state: withReviewers }, withPlan(file, incidentScribe, blocked))
    assert.equal(result.outcome, 'STATE-LOST')
    assert.equal(result.then, 'PLAN-DEFECT')
    assert.ok(result.lost.some(l => l.startsWith('reviewers:')), JSON.stringify(result.lost))
  }
})

test('a scribe that could read nothing is SCRIBE-FAILED, not STATE-LOST', async () => {
  const { result } = await run({ ...BASE, state: PLAN_STATE }, standard({ scribe: { written: false, note: 'no such file', state_before: '', state_after: '' } }))
  assert.equal(result.outcome, 'SCRIBE-FAILED')
  assert.equal(result.then, 'PASS')
})

// --- 2g: the scribe gets absolute paths -------------------------------------
//
// Pinned 2026-09-24 (hs-drive-game-lease, wf_949ed012-a02): run from a
// worktree, the scribe resolved its relative paths against the main checkout,
// found no files, and returned written: false with a non-empty "N/A" State.
// The Record pass compared that against the driver's State and reported
// STATE-LOST, listing every driver-owned line, though nothing had been lost.
test('a scribe that found no files routes as SCRIBE-FAILED with nothing listed lost', async () => {
  const na = { written: false, note: 'files do not exist', state_before: 'N/A - files do not exist', state_after: 'N/A - files do not exist' }
  for (const blocked of [{}, { implementer: { ...DONE, verdict: 'PLAN-DEFECT', evidence: 'ev' } }]) {
    const { result, calls } = await run({ ...BASE, state: PLAN_STATE }, standard({ scribe: na, verifier: defectThenPass(), ...blocked }))
    assert.equal(result.outcome, 'SCRIBE-FAILED', JSON.stringify(result))
    assert.equal(result.lost, undefined)
    assert.equal(result.then, blocked.implementer ? 'PLAN-DEFECT' : 'continue')
    for (const line of PLAN_STATE.split('\n').filter(l => DRIVER_OWNED.test(l))) assert.ok(result.state.includes(line), `state to paste lacks: ${line}`)
    assert.match(result.log, /^### Round 0$/m)
    assert.ok(!calls.includes('verifier:r1'))
  }
})

test('the scribe is handed absolute paths under checkoutRoot, never relative ones', async () => {
  const prompts = {}
  const reply = (label, prompt) => { prompts[label] = prompt; return standard()(label) }
  await run({ ...BASE, planPath: '.claude/workorders/zz-plan.md', contextPath: './.claude/workorders/zz-context.md', checkoutRoot: 'C:\\wt\\here\\' }, reply)
  const p = prompts['scribe:r0']
  assert.ok(p.includes('In C:\\wt\\here/.claude/workorders/zz-context.md, append'), p)
  assert.ok(p.includes('Read C:\\wt\\here/.claude/workorders/zz-plan.md and return'), p)
  assert.doesNotMatch(p, /relative to your current working directory/)
  // An already-absolute path is used as it is.
  await run({ ...BASE, planPath: 'D:/x/p.md', contextPath: 'D:/x/c.md' }, reply)
  assert.ok(prompts['scribe:r0'].includes('In D:/x/c.md, append'))
})

test('control: without checkoutRoot a relative plan path is refused, an absolute one is not', async () => {
  const { checkoutRoot, ...noRoot } = BASE
  let r = await run(noRoot, standard())
  assert.equal(r.result.outcome, 'BAD-ARGS')
  assert.match(r.result.detail, /checkoutRoot/)
  assert.deepEqual(r.calls, [])
  r = await run({ ...noRoot, planPath: 'D:/x/p.md', contextPath: 'D:/x/c.md' }, standard())
  assert.equal(r.result.outcome, 'PASS')
})

// --- 2f: a criterion gated on a gate not set is pending, never a defect -----
//
// Pinned 2026-09-24 (forgepact-issue-14-phase1j): `gates:` was written as a
// template of every gate and value joined by `|`, the verifier read it as all
// set and failed the live-session criteria, and three rounds went to CAP with
// no real defect open after round 0.
const TEMPLATE_GATES = 'gates: build: complete | live1: complete | record: complete | save-route: proven|not-observed'
const gatedState = gatesLine => ['round: 0', 'phase: implement', gatesLine, 'open defects: none'].join('\n')
const LIVE = { criterion: 'phase1j rows= in the live log', status: 'fail', evidence: 'no live log', gate: 'live1: complete' }
const SUITE = { criterion: 'suite passes', status: 'pass', evidence: 'OK', gate: '' }
const failing = (...criteria) => ({ verdict: 'IMPL-DEFECT', criteria: [SUITE, ...criteria], pending_human: [] })

test('failures gated only on a template gates: line route as PASS-PENDING-HUMAN, spending no round', async () => {
  const prompts = {}
  const { result, calls } = await run({ ...BASE, state: gatedState(TEMPLATE_GATES) },
    (label, prompt, opts) => { prompts[label] = prompt; return standard({ verifier: failing(LIVE) })(label, prompt, opts) })
  assert.equal(result.outcome, 'PASS-PENDING-HUMAN')
  assert.equal(result.round, 0)
  assert.equal(calls.filter(c => c.startsWith('implementer')).length, 1)
  assert.deepEqual(result.rounds[0].failed, [])
  assert.ok(result.pending_human.some(p => /gate live1: complete not set/.test(p)), JSON.stringify(result.pending_human))
  assert.match(prompts['scribe:r0'], /verifier: PASS-PENDING-HUMAN \(the verifier said IMPL-DEFECT/)
  assert.match(prompts['scribe:r0'], /- PENDING \(gate live1: complete not set\) phase1j rows=/)
  assert.match(prompts['scribe:r0'], /^phase: pass$/m)
})

test('control: the same failure with its gate literally set on gates: is a defect', async () => {
  for (const line of ['gates: `build: complete`; `live1: complete`', 'gates: build: complete, live1: complete']) {
    const { result } = await run({ ...BASE, state: gatedState(line) }, standard({ verifier: failing(LIVE) }))
    assert.equal(result.outcome, 'CAP', line)
    assert.equal(result.rounds[0].failed.length, 1, line)
  }
})

test('an ungated failure beside a gated one is still a defect, and only it is reported FAILED', async () => {
  const prompts = {}
  const real = { criterion: 'doc structure', status: 'fail', evidence: 'missing heading', gate: '' }
  let v = 0
  const { result } = await run({ ...BASE, state: gatedState(TEMPLATE_GATES) }, (label, prompt, opts) => {
    prompts[label] = prompt
    return standard({ verifier: () => (v++ === 0 ? failing(LIVE, real) : failing(LIVE)) })(label, prompt, opts)
  })
  assert.equal(result.outcome, 'PASS-PENDING-HUMAN')
  assert.equal(result.round, 1, 'round 0 had a real failure')
  assert.match(prompts['scribe:r0'], /- FAILED doc structure/)
  assert.doesNotMatch(prompts['scribe:r0'], /- FAILED phase1j/)
})

test('a BLOCKING finding still spends a round when every failure is gated', async () => {
  let seen = 0
  const { result } = await run({ ...BASE, state: gatedState(TEMPLATE_GATES) }, standard({
    verifier: failing(LIVE),
    'docs-sync-reviewer': () => (seen++ === 0 ? { ...CLEAN, blocking: [{ where: 'a', problem: 'wrong', evidence: 'x' }] } : CLEAN),
  }))
  assert.equal(result.outcome, 'PASS-PENDING-HUMAN')
  assert.equal(result.round, 1)
})

test('with no gates: line in State nothing is reclassified', async () => {
  const { result } = await run({ ...BASE, state: 'round: 0\nphase: implement' }, standard({ verifier: failing(LIVE) }))
  assert.equal(result.outcome, 'CAP')
})

test('a legacy "not yet:" tail and gates pending: set nothing', async () => {
  for (const line of ['gates: `build: complete` (set 2026-09-24); not yet: `live1: complete`', 'gates: none\ngates pending: `live1: complete`']) {
    const { result } = await run({ ...BASE, state: gatedState(line) }, standard({ verifier: failing(LIVE) }))
    assert.equal(result.outcome, 'PASS-PENDING-HUMAN', line)
  }
})

test('the verifier is told a template gates: line sets nothing and a gated criterion is unattempted', async () => {
  const prompts = {}
  await run(BASE, (label, prompt) => { prompts[label] = prompt; return standard()(label) })
  assert.match(prompts['verifier:r0'], /`\|` alternatives is a template that sets nothing/)
  assert.match(prompts['verifier:r0'], /'unattempted' \(gate <token> not set\), never 'fail'/)
})

test('an "or" between backticked tokens on gates: is a template too', async () => {
  const { result } = await run({ ...BASE, state: gatedState('gates: `live1: complete` or `record: complete`') }, standard({ verifier: failing(LIVE) }))
  assert.equal(result.outcome, 'PASS-PENDING-HUMAN')
  // control: "or" inside a token or a parenthetical is not an alternative
  const r = await run({ ...BASE, state: gatedState('gates: `live1: complete` (run or rerun)') }, standard({ verifier: failing(LIVE) }))
  assert.equal(r.result.outcome, 'CAP')
})

test('a dropped State line on an all-gated round reports then: PASS-PENDING-HUMAN', async () => {
  const state = gatedState(TEMPLATE_GATES)
  const file = { plan: planFile(state) }
  const { result } = await run({ ...BASE, state }, withPlan(file, incidentScribe, { verifier: failing(LIVE) }))
  assert.equal(result.outcome, 'STATE-LOST')
  assert.equal(result.then, 'PASS-PENDING-HUMAN')
})

test('a structural finding keeps an all-gated round a defect', async () => {
  const { result } = await run({ ...BASE, state: gatedState(TEMPLATE_GATES) },
    standard({ verifier: { ...failing(LIVE), other_defects: ['ForgePact/plugin/x.cpp:12 *Rva* constant reachable from release'] } }))
  assert.equal(result.outcome, 'CAP')
})

test('NON-BLOCKING Log lines carry no evidence tail; BLOCKING lines keep theirs', async () => {
  const prompts = {}
  const reply = (label, prompt) => {
    prompts[label] = prompt
    return standard({
      'docs-sync-reviewer': { blocking: [{ where: 'w', problem: 'wrong', evidence: 'BLOCK-EV' }], non_blocking: [], plan_defect: false, summary: 'x' },
      'decompile-output-guard': { blocking: [], non_blocking: [{ where: 'nw', problem: 'nit', evidence: 'NB-EV' }], plan_defect: false, summary: 'x' },
    })(label)
  }
  await run(BASE, reply)
  assert.match(prompts['scribe:r0'], /\[docs-sync-reviewer\] w: wrong — evidence: BLOCK-EV/)
  assert.match(prompts['scribe:r0'], /\[decompile-output-guard\] nw: nit/)
  assert.doesNotMatch(prompts['scribe:r0'], /NB-EV/)
})

test('the verifier is told to run criteria as written and each suite once', async () => {
  const prompts = {}
  const reply = (label, prompt) => { prompts[label] = prompt; return standard()(label) }
  await run(BASE, reply)
  assert.match(prompts['verifier:r0'], /never swap `py -3` for `python`/)
  assert.match(prompts['verifier:r0'], /Run each test suite once, with the Bash timeout at 240000/)
})

// --- lanes: independent step groups on parallel implementers (issue #176) ---
//
// `args.lanes` / `args.join` come from `tools/plan_lint.py --lanes-json`. On a
// launch's first round each lane gets its own implementer, all dispatched
// through one parallel() barrier, then the join runs alone. The stub
// parallel() records labels in dispatch order, so "concurrent" is asserted as
// every lane label landing before the join's, and the join being handed every
// lane's report.
const LANES = [
  { name: 'code', files: ['.claude/workflows/x.js', 'tests/test_x.py'] },
  { name: 'docs', files: ['docs/agents/*.md'] },
]
const LANED = { ...BASE, lanes: LANES, join: true }
const laneDone = name => ({ ...DONE, lane: name, report: `REPORT-OF-${name}`, progress_so_far: `PROGRESS-OF-${name}` })
const laneReply = (byLane = {}, overrides = {}) => (label, prompt, opts) => {
  const m = /^implementer:([a-z0-9-]+):r\d+$/.exec(label)
  if (m && m[1] !== 'join') {
    const v = byLane[m[1]]
    if (v === undefined) return laneDone(m[1])
    return typeof v === 'function' ? v(label, prompt, opts) : v
  }
  return standard(overrides)(label, prompt, opts)
}

test('lanes: a plan without lanes dispatches the byte-identical single implementer', async () => {
  const seen = []
  const capture = (label, prompt, opts) => {
    if (label.startsWith('implementer')) seen.push({ label, prompt, opts })
    return standard()(label, prompt, opts)
  }
  const bare = await run(BASE, capture)
  const empty = await run({ ...BASE, lanes: [], join: false }, capture)
  assert.equal(bare.result.outcome, 'PASS')
  assert.equal(empty.result.outcome, 'PASS')
  assert.equal(seen.length, 2, seen.map(s => s.label).join(', '))
  assert.equal(seen[0].label, 'implementer:r0')
  assert.equal(seen[1].label, seen[0].label)
  assert.equal(seen[1].prompt, seen[0].prompt)
  assert.deepEqual(seen[1].opts, seen[0].opts)
  assert.equal(empty.calls.filter(c => c.startsWith('implementer')).length, 1)
  assert.deepEqual(empty.calls.filter(c => c.startsWith('implementer')), ['implementer:r0'])
})

test('lanes: two declared lanes run concurrently and the join runs after both', async () => {
  const opts = {}
  const { result, calls } = await run(LANED, (label, prompt, o) => { opts[label] = o; return laneReply()(label, prompt, o) })
  assert.equal(result.outcome, 'PASS')
  const impl = calls.filter(c => c.startsWith('implementer'))
  assert.deepEqual(impl, ['implementer:code:r0', 'implementer:docs:r0', 'implementer:join:r0'])
  assert.ok(!calls.includes('implementer:r0'), 'a laned round has no single implementer')
  for (const l of ['implementer:code:r0', 'implementer:docs:r0', 'implementer:join:r0']) {
    assert.equal(opts[l].agentType, 'implementer', l)
    assert.equal(opts[l].phase, 'Implement', l)
    assert.equal(opts[l].model, 'sonnet', l)
  }
  assert.ok(opts['implementer:code:r0'].schema.properties.verdict.enum.includes('STOPPED'))
  assert.equal(opts['implementer:code:r0'].schema.properties.lane.type, 'string')
  assert.ok(!opts['implementer:join:r0'].schema.properties.verdict.enum.includes('STOPPED'), 'the join returns the laneless verdicts')
  // the round goes on to the delta and the verifier, once
  assert.ok(calls.indexOf('delta:r0') > calls.indexOf('implementer:join:r0'))
  assert.equal(calls.filter(c => c === 'verifier:r0').length, 1)
})

test('lanes: three declared lanes run concurrently and the join runs after all three', async () => {
  const three = [...LANES, { name: 'audit', files: ['tools/workorder_audit.py'] }]
  const prompts = {}
  const { result, calls } = await run({ ...LANED, lanes: three }, (label, prompt, o) => { prompts[label] = prompt; return laneReply()(label, prompt, o) })
  assert.equal(result.outcome, 'PASS')
  const joinAt = calls.indexOf('implementer:join:r0')
  assert.ok(joinAt > 0)
  for (const name of ['code', 'docs', 'audit']) {
    const at = calls.indexOf(`implementer:${name}:r0`)
    assert.ok(at >= 0 && at < joinAt, `${name} dispatched before the join`)
    assert.ok(prompts['implementer:join:r0'].includes(`REPORT-OF-${name}`), name)
  }
  assert.equal(calls.filter(c => /^implementer:[a-z0-9-]+:r0$/.test(c)).length, 4)
})

test('lanes: the join is handed every lane report and commits per lane by pathspec', async () => {
  const prompts = {}
  await run({ ...LANED, submodules: ['ForgePact'], lanes: [...LANES, { name: 'plugin', files: ['ForgePact/plugin/a.cpp'] }] },
    (label, prompt, o) => { prompts[label] = prompt; return laneReply()(label, prompt, o) })
  const p = prompts['implementer:join:r0']
  assert.ok(p.includes('REPORT-OF-code') && p.includes('REPORT-OF-docs') && p.includes('REPORT-OF-plugin'), p)
  assert.ok(p.includes('git add -- ".claude/workflows/x.js" "tests/test_x.py"'), p)
  assert.ok(p.includes('git add -- "docs/agents/*.md"'), p)
  assert.ok(p.includes('git -C ForgePact add -- "plugin/a.cpp"'), 'a submodule path is committed in its own repo')
  // lane order is the commit order, each lane its own commit, before the join's own steps
  assert.ok(p.indexOf('lane code') < p.indexOf('lane docs') && p.indexOf('lane docs') < p.indexOf('lane plugin'), p)
  assert.match(p, /then carry out the steps under '### Join'/)
  assert.match(p, /DEVIATIONS/)
  assert.match(p, /This is round 0\./)
  assert.match(p, /Return your usual verdict/)
})

test('lanes: a lane PLAN-DEFECT skips the join and hands the round back with the progress of every lane', async () => {
  const prompts = {}
  const defect = { verdict: 'PLAN-DEFECT', report: '', evidence: 'EVIDENCE-CODE', progress_so_far: 'PROGRESS-OF-code', lane: 'code' }
  const stopped = { verdict: 'STOPPED', report: '', evidence: '', progress_so_far: 'PROGRESS-OF-docs', lane: 'docs' }
  const { result, calls } = await run({ ...LANED, state: 'round: 0\nphase: implement\ngates: none' },
    (label, prompt, o) => { prompts[label] = prompt; return laneReply({ code: defect, docs: stopped })(label, prompt, o) })
  assert.equal(result.outcome, 'PLAN-DEFECT')
  assert.equal(result.round, 0)
  assert.ok(!calls.includes('implementer:join:r0'), 'no join after a lane defect')
  assert.ok(!calls.some(c => c.startsWith('verifier') || c.startsWith('delta')))
  assert.deepEqual(result.lanes.map(l => [l.name, l.verdict, l.progress_so_far]),
    [['code', 'PLAN-DEFECT', 'PROGRESS-OF-code'], ['docs', 'STOPPED', 'PROGRESS-OF-docs']])
  const s = prompts['scribe:r0']
  assert.match(s, /^### Round 0$/m)
  assert.match(s, /lane code: PLAN-DEFECT/)
  assert.match(s, /EVIDENCE-CODE/)
  assert.match(s, /lane docs: STOPPED/)
  assert.ok(s.includes('PROGRESS-OF-code') && s.includes('PROGRESS-OF-docs'), s)
  assert.match(s, /^phase: blocked$/m)
})

test('lanes: a lane ADVICE-NEEDED does the same, and PLAN-DEFECT outranks it', async () => {
  const advice = name => ({ verdict: 'ADVICE-NEEDED', report: '', evidence: '', question: `Q-${name}`, progress_so_far: `PROGRESS-OF-${name}`, lane: name })
  let r = await run(LANED, laneReply({ docs: advice('docs') }))
  assert.equal(r.result.outcome, 'ADVICE-NEEDED')
  assert.ok(!r.calls.includes('implementer:join:r0'))
  assert.deepEqual(r.result.lanes.map(l => l.verdict), ['IMPL-DONE', 'ADVICE-NEEDED'])
  const defect = { verdict: 'PLAN-DEFECT', report: '', evidence: 'ev', progress_so_far: 'p', lane: 'docs' }
  r = await run(LANED, laneReply({ code: advice('code'), docs: defect }))
  assert.equal(r.result.outcome, 'PLAN-DEFECT')
  assert.ok(!r.calls.includes('implementer:join:r0'))
})

test('lanes: a lane that returns nothing is AGENT-FAILED naming the lane', async () => {
  const { result, calls } = await run(LANED, laneReply({ docs: null }))
  assert.equal(result.outcome, 'AGENT-FAILED')
  assert.equal(result.detail, 'lane docs returned nothing')
  assert.ok(!calls.includes('implementer:join:r0'))
  // control: the lane that did return is still handed back
  assert.equal(result.lanes.find(l => l.name === 'code').verdict, 'IMPL-DONE')
})

test('lanes: a lane prompt carries its file set, the stop check, the stop write and the no-git-writes rule', async () => {
  const prompts = {}
  await run(LANED, (label, prompt, o) => { prompts[label] = prompt; return laneReply()(label, prompt, o) })
  const p = prompts['implementer:code:r0']
  assert.ok(p.includes('`.claude/workflows/x.js`') && p.includes('`tests/test_x.py`'), p)
  assert.ok(!p.includes('docs/agents/*.md'), 'a lane is not handed another lane\'s file set')
  assert.match(p, /'### Lane: code'/)
  assert.ok(p.includes('py -3 .claude/skills/workorder/round_delta.py stopped zz 0'), p)
  assert.ok(p.includes('py -3 .claude/skills/workorder/round_delta.py stop zz 0 --lane code --verdict <PLAN-DEFECT|ADVICE-NEEDED>'), p)
  assert.match(p, /exit 4/)
  assert.match(p, /STOPPED/)
  assert.match(p, /Run no git command that writes/)
  assert.match(p, /PLAN-DEFECT/)
  assert.match(p, /no full build and no full test suite/)
  assert.match(p, /Workorder: p\.md \(context file: c\.md\)\. This is round 0\./)
  assert.ok(prompts['implementer:docs:r0'].includes('`docs/agents/*.md`'))
  assert.ok(prompts['implementer:docs:r0'].includes('--lane docs'))
  // a repoRoot reaches the stop commands the same way it reaches snapshot/delta
  await run({ ...LANED, repoRoot: '/repo root' }, (label, prompt, o) => { prompts[label] = prompt; return laneReply()(label, prompt, o) })
  assert.ok(prompts['implementer:code:r0'].includes('stopped zz 0 --root "/repo root"'))
})

test('lanes: later rounds of a laned launch run one implementer', async () => {
  const prompts = {}
  const reply = laneReply({}, { verifier: defectThenPass() })
  const { result, calls } = await run(LANED, (label, prompt, o) => { prompts[label] = prompt; return reply(label, prompt, o) })
  assert.equal(result.outcome, 'PASS')
  assert.equal(result.round, 1)
  const impl = calls.filter(c => c.startsWith('implementer'))
  assert.deepEqual(impl, ['implementer:code:r0', 'implementer:docs:r0', 'implementer:join:r0', 'implementer:r1'])
  const p = prompts['implementer:r1']
  assert.match(p, /re-entered after a defect/)
  assert.match(p, /lanes \(code, docs\)/)
  assert.match(p, /you own every lane's file set/)
  // control: a laneless launch's round 1 carries no lane sentence
  const bare = {}
  const bareReply = standard({ verifier: defectThenPass() })
  await run(BASE, (label, prompt, o) => { bare[label] = prompt; return bareReply(label, prompt, o) })
  assert.ok(bare['implementer:r1'], 'control: the laneless launch reached round 1')
  assert.doesNotMatch(bare['implementer:r1'], /lane/)
})

test('lanes: a join verdict routes like the laneless implementer', async () => {
  for (const verdict of ['PLAN-DEFECT', 'ADVICE-NEEDED']) {
    const prompts = {}
    const joinSays = { ...DONE, verdict, evidence: `JOIN-EV-${verdict}` }
    const { result, calls } = await run(LANED, (label, prompt, o) => {
      prompts[label] = prompt
      return laneReply({}, { 'implementer:join': joinSays })(label, prompt, o)
    })
    assert.equal(result.outcome, verdict)
    assert.equal(result.implementer.evidence, `JOIN-EV-${verdict}`)
    assert.ok(!calls.some(c => c.startsWith('verifier')))
    assert.match(prompts['scribe:r0'], new RegExp(`JOIN-EV-${verdict}`))
    assert.match(prompts['scribe:r0'], /^phase: blocked$/m)
  }
  const { result } = await run(LANED, laneReply({}, { 'implementer:join': null }))
  assert.equal(result.outcome, 'AGENT-FAILED')
  assert.match(result.detail, /join/)
})

test('lanes: args that could not have come from plan_lint --lanes-json are refused', async () => {
  for (const bad of [
    { lanes: LANES, join: false },
    { lanes: [{ name: 'code', files: [] }, LANES[1]], join: true },
    { lanes: [{ name: 'join', files: ['a'] }, LANES[1]], join: true },
    { lanes: [{ name: 'Code', files: ['a'] }, LANES[1]], join: true },
    { lanes: [LANES[0], LANES[0]], join: true },
  ]) {
    const { result, calls } = await run({ ...BASE, ...bad }, laneReply())
    assert.equal(result.outcome, 'BAD-ARGS', JSON.stringify(bad))
    assert.deepEqual(calls, [])
  }
})
