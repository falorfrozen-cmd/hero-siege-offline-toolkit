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
  if (label.startsWith('implementer') || label.startsWith('patch-implementer')) return DONE
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

// Rounds the driver relaunched only to carry the owner's new decisions do not
// count (SKILL.md Step 4, "Owner scope is not a failure"): the ForgePact UI
// redesign's polish and ship workorders each met the cap on owner scope.
test('owner-scope rounds from State extend the cap, at most SCOPE_CAP in all', async () => {
  const fail = { verdict: 'IMPL-DEFECT', criteria: [{ criterion: 'c', status: 'fail', evidence: 'e' }], pending_human: [] }
  for (const [scope, implementers] of [[0, 3], [2, 5], [9, 6]]) {
    const state = `round: 0\nphase: implement${scope ? `\nscope rounds: ${scope}` : ''}`
    const { result, calls } = await run({ ...BASE, state }, standard({ verifier: fail }))
    assert.equal(result.outcome, 'CAP', `scope ${scope}`)
    assert.equal(calls.filter(c => c.startsWith('implementer')).length, implementers, `scope ${scope}`)
    if (scope) assert.match(result.detail, /owner-scope round/)
    else assert.doesNotMatch(result.detail, /owner-scope/)
  }
})

// The Log heading carries the snapshot's start time so round wall time and
// owner waits can be read from the Log alone; a snapshot that printed no time
// (or garbage) leaves the heading exactly as before.
test('a round heading carries the snapshot time when one was printed', async () => {
  for (const [taken, heading] of [['2026-09-27T10:11:12Z', '### Round 0 (started 2026-09-27T10:11:12Z)'], [undefined, '### Round 0\n'], ['soon', '### Round 0\n']]) {
    const prompts = []
    const { calls } = await run(BASE, (label, prompt, opts) => {
      if (label.startsWith('scribe')) prompts.push(prompt)
      return standard({ snapshot: DELTA([], taken ? { taken_utc: taken } : {}) })(label, prompt, opts)
    })
    assert.ok(calls.some(c => c.startsWith('scribe')))
    assert.ok(prompts.some(p => p.includes(heading)), `${taken}: ${prompts[0] && prompts[0].slice(0, 400)}`)
  }
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
    'Then run exactly: py -3 .claude/skills/workorder/round_delta.py heads zz 0  — report its exit code (3 if either command exited 3) and each printed line, split into repo and sha at the first tab, as heads: [{repo, sha}]. ' +
    'The snapshot command\'s `taken_utc: <time>` line, if it printed one, goes in taken_utc verbatim. Edit nothing.')
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
  // 2k: the brief (`--round 1`) prints the round's Log entries, so the prompt
  // points at them there instead of sending the implementer to read the Log.
  assert.match(prompts['implementer:r1'], /re-entered after a defect: your brief prints '## Log' > '### Round 0'/)
  // A relaunch after a PLAN-DEFECT raised in round 1 itself keeps `round: 1`,
  // and the newer evidence is under that round's own heading.
  assert.match(prompts['implementer:r1'], /and '### Round 1' if it is already there/)
  assert.match(prompts['implementer:r1'], /newer evidence\); read that evidence before anything else\. Then read only what that evidence needs beyond the brief/)
  // The owner, 2026-10-02: after a write, read the diff, not the file.
  assert.match(prompts['implementer:r1'], /not the whole plan, and not a file earlier rounds changed: read its diff \(the brief's `git diff` lines, or `git diff <base> -- <path>`/)
  assert.ok(prompts['implementer:r1'].includes('round_delta.py heads zz 0'), prompts['implementer:r1'])
  await run(BASE, reply)
  assert.doesNotMatch(prompts['implementer:r0'], /re-entered after a defect|read its diff/)
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

// ForgePact UI redesign: four STATE-LOST stops on entries nothing removed --
// a multi-line entry re-indented between the scribe's before and after
// reports, and `<none yet>` reported back as `&lt;none yet&gt;`.
test('re-indented continuation lines and escaped brackets are not a lost entry', async () => {
  const multi = PLAN_STATE.replace('decisions in force: D1, D2 (context file, `### Decisions`)',
    'decisions in force: D1 both repositories take `origin/main` by a merge\n  commit (never a rebase)')
  const relayout = file => prompt => {
    const res = faithfulScribe(file)(prompt)
    return { ...res, state_after: res.state_after.replace('\n  commit (never', '\n    commit (never').replace('<none yet>', '&lt;none yet&gt;') }
  }
  const file = { plan: planFile(multi) }
  const { result } = await run({ ...BASE, state: multi }, withPlan(file, relayout, { verifier: defectThenPass() }))
  assert.equal(result.outcome, 'PASS', JSON.stringify(result.lost))
  // control: an entry whose words changed is still lost
  const dropper = file => prompt => {
    const res = faithfulScribe(file)(prompt)
    return { ...res, state_after: res.state_after.replace('never a rebase', 'rebase is fine') }
  }
  const file2 = { plan: planFile(multi) }
  const { result: r2 } = await run({ ...BASE, state: multi }, withPlan(file2, dropper, { verifier: defectThenPass() }))
  assert.equal(r2.outcome, 'STATE-LOST')
  assert.ok(r2.lost.some(l => l.startsWith('decisions in force:')), JSON.stringify(r2.lost))
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
  // The owner, 2026-10-02: after a write, read only what changed. The scribe
  // reads the State range and the Log's tail, never either file whole.
  assert.match(p, /never either file whole/)
  assert.match(p, /reading only that range \(offset at the State heading/)
  assert.match(p, /Read only its last 30 lines \(offset = count - 30\)/)
  assert.ok(p.includes("Grep -n '^### Round 0\\b'"), p)
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

// --- 2i: the patch route ------------------------------------------------------
// A round whose only defects are BLOCKING findings that each carry the
// reviewer's exact fix is followed by a patch round: fix-only implementer,
// verifier as usual, only the finding reviewers (plus the decompile guard on
// its trigger) re-run, and -- when `round_delta.py size` says it stayed small
// -- not counted against the cap. Each property has its control beside it.
const FIXED = { where: 'docs/x.md:3', problem: 'wrong flag', evidence: 'line 3 says --a', fix: 'change `--a` to `--b` on docs/x.md:3' }
const UNFIXED = { where: 'docs/x.md:3', problem: 'wrong flag', evidence: 'line 3 says --a' }
const SMALL = (paths = ['docs/x.md'], extra = {}) => DELTA(paths, { size_exit_code: 0, lines_changed: 2, new_files: 0, ...extra })
const PATCH_BASE = { ...BASE, reviewers: { 'docs-sync-reviewer': 'never', 'decompile-output-guard': 'never', 'tauri-command-reviewer': 'never' } }
const blockingOnce = finding => { let seen = 0; return () => (seen++ === 0 ? { ...CLEAN, blocking: [finding] } : CLEAN) }
const recording = (prompts, reply) => (label, prompt, opts) => { prompts[label] = prompt; return reply(label, prompt, opts) }
const implementers = calls => calls.filter(c => /implementer/.test(c))

test('patch: every BLOCKING finding carrying its fix runs a patch round that is not counted', async () => {
  const prompts = {}
  const { result, calls } = await run(PATCH_BASE, recording(prompts, standard({ delta: SMALL(), 'docs-sync-reviewer': blockingOnce(FIXED) })))
  assert.equal(result.outcome, 'PASS')
  assert.deepEqual(implementers(calls), ['implementer:r0', 'patch-implementer:r1'])
  assert.match(prompts['patch-implementer:r1'], /patch round/)
  assert.ok(prompts['patch-implementer:r1'].includes(FIXED.fix), 'the patch implementer is handed the fix itself')
  assert.ok(prompts['delta:r1'].includes('round_delta.py size zz 1'), 'a patch round is measured')
  assert.ok(!prompts['delta:r0'].includes('round_delta.py size'), 'control: an ordinary round is not')
  assert.ok(calls.includes('verifier:r1'), 'the verifier still runs every criterion')
  assert.ok(calls.includes('docs-sync-reviewer:r1'), 'the reviewer that found it confirms it')
  assert.ok(calls.includes('decompile-output-guard:r1'), 'a .md changed: the legal guard is never skipped')
  assert.ok(!calls.includes('tauri-command-reviewer:r1'))
  assert.match(result.rounds[0].next, /patch round/)
  assert.match(result.rounds[1].patch, /^held \(2 lines in 1 file\(s\)\)/)
  assert.match(prompts['scribe:r1'], /patch rounds: 1/)
  assert.match(prompts['scribe:r0'], /phase: patch/)
})

test('patch: a held patch skips a clean reviewer whose trigger matches; an ordinary round would run it', async () => {
  // docs-sync's trigger matches any non-test path, so an ordinary re-run of a
  // clean docs-sync on docs/x.md runs it -- a held patch does not.
  const reviewers = { 'docs-sync-reviewer': 'never', 'decompile-output-guard': 'never' }
  const tauri = blockingOnce({ ...FIXED, where: 'hub/src-tauri/src/x.rs:1' })
  let r = await run({ ...BASE, reviewers: { ...reviewers, 'tauri-command-reviewer': 'never' } }, standard({ delta: SMALL(), 'tauri-command-reviewer': tauri }))
  assert.ok(r.calls.includes('patch-implementer:r1'))
  assert.ok(!r.calls.includes('docs-sync-reviewer:r1'), 'held patch: a clean docs-sync is not re-run')
  assert.ok(r.calls.includes('tauri-command-reviewer:r1'))
  r = await run({ ...BASE, reviewers: { ...reviewers, 'tauri-command-reviewer': 'never' } },
    standard({ delta: SMALL(), 'tauri-command-reviewer': blockingOnce({ ...UNFIXED, where: 'hub/src-tauri/src/x.rs:1' }) }))
  assert.ok(r.calls.includes('docs-sync-reviewer:r1'), 'control: an ordinary round re-runs it on the same delta')
})

test('patch: control -- a BLOCKING finding without a fix spends an ordinary round', async () => {
  const { calls, result } = await run(PATCH_BASE, standard({ delta: SMALL(), 'docs-sync-reviewer': blockingOnce(UNFIXED) }))
  assert.equal(result.outcome, 'PASS')
  assert.deepEqual(implementers(calls), ['implementer:r0', 'implementer:r1'])
  assert.equal(result.rounds[0].next, undefined)
})

test('patch: one finding without a fix among fixed ones makes the round ordinary', async () => {
  let seen = 0
  const { calls } = await run(PATCH_BASE, standard({
    delta: SMALL(),
    'docs-sync-reviewer': () => (seen++ === 0 ? { ...CLEAN, blocking: [FIXED, UNFIXED] } : CLEAN),
  }))
  assert.deepEqual(implementers(calls), ['implementer:r0', 'implementer:r1'])
})

test('patch: a failed criterion, a structural finding, a plan defect or an instrument finding never patches', async () => {
  const fail = { verdict: 'IMPL-DEFECT', criteria: [{ criterion: 'c', status: 'fail', evidence: 'e' }], pending_human: [] }
  const structural = { verdict: 'IMPL-DEFECT', criteria: [], pending_human: [], other_defects: ['NOT DONE: step 3'] }
  for (const verifierReply of [fail, structural]) {
    let v = 0
    const { calls } = await run(PATCH_BASE, standard({ delta: SMALL(), 'docs-sync-reviewer': blockingOnce(FIXED), verifier: () => (v++ === 0 ? verifierReply : PASS) }))
    assert.deepEqual(implementers(calls), ['implementer:r0', 'implementer:r1'], JSON.stringify(verifierReply))
  }
  let r = await run(PATCH_BASE, standard({ delta: SMALL(), 'docs-sync-reviewer': { ...CLEAN, blocking: [FIXED], plan_defect: true } }))
  assert.equal(r.result.outcome, 'PLAN-DEFECT')
  assert.ok(!r.calls.some(c => c.startsWith('patch-implementer')))
  r = await run({ ...BASE, reviewers: { 'instrument-blindness-reviewer': 'never' } }, standard({ delta: SMALL(), 'instrument-blindness-reviewer': blockingOnce(FIXED) }))
  assert.deepEqual(implementers(r.calls), ['implementer:r0', 'implementer:r1'])
})

test('patch: one that outgrew the limit, added a file or reached an excluded path is counted and reviewed as usual', async () => {
  const cases = [
    [SMALL(['docs/x.md'], { lines_changed: 21 }), /21 lines changed/],
    [SMALL(['docs/x.md', 'docs/new.md'], { new_files: 1 }), /new file/],
    [SMALL(['ForgePact/plugin/ModuleMain.cpp']), /touched ForgePact\/plugin/],
    [SMALL(['ForgePact/release-notes-v1.4.6.md']), /release-notes/],
    [SMALL(['docs/x.md'], { size_exit_code: 3 }), /no usable figure/],
    [SMALL(['tools/x.py'], { instrumentContent: true }), /instrument-shaped/],
  ]
  for (const [delta, why] of cases) {
    const state = { ...PATCH_BASE, reviewers: { ...PATCH_BASE.reviewers, 'instrument-blindness-reviewer': 'never' } }
    const { result, calls } = await run(state, standard({ delta, 'docs-sync-reviewer': blockingOnce(FIXED) }))
    assert.equal(result.outcome, 'PASS')
    assert.match(result.rounds[1].patch, why)
    assert.match(result.rounds[1].patch, /counted as an ordinary round/)
    if (delta.paths.some(p => p.startsWith('ForgePact/plugin/')) || delta.instrumentContent) {
      assert.ok(calls.includes('instrument-blindness-reviewer:r1'), 'an ordinary round runs its triggered reviewers')
    }
  }
  // control: 20 lines is still a patch
  const { result } = await run(PATCH_BASE, standard({ delta: SMALL(['docs/x.md'], { lines_changed: 20 }), 'docs-sync-reviewer': blockingOnce(FIXED) }))
  assert.match(result.rounds[1].patch, /^held/)
})

test('patch: a patch that held does not count, so a third ordinary round still runs after it', async () => {
  // r0 ordinary (blocking, fixed) -> r1 patch held (blocking again, unfixed)
  // -> r2 ordinary -> r3 ordinary. Without the patch route r3 would be past the cap.
  let seen = 0
  const docs = () => { seen++; return seen === 1 ? { ...CLEAN, blocking: [FIXED] } : seen <= 3 ? { ...CLEAN, blocking: [UNFIXED] } : CLEAN }
  const { result, calls } = await run(PATCH_BASE, standard({ delta: SMALL(), 'docs-sync-reviewer': docs }))
  assert.equal(result.outcome, 'PASS', JSON.stringify(result.rounds && result.rounds.map(r => r.patch || '-')))
  assert.equal(result.round, 3)
  assert.deepEqual(implementers(calls), ['implementer:r0', 'patch-implementer:r1', 'implementer:r2', 'implementer:r3'])
})

test('patch: two patch rounds never run back to back', async () => {
  let seen = 0
  const docs = () => (seen++ < 2 ? { ...CLEAN, blocking: [FIXED] } : CLEAN)
  const { calls } = await run(PATCH_BASE, standard({ delta: SMALL(), 'docs-sync-reviewer': docs }))
  assert.deepEqual(implementers(calls), ['implementer:r0', 'patch-implementer:r1', 'implementer:r2'])
})

test('patch: a patch decided on the last counted round still runs, and the cap stands after it', async () => {
  const fail = { verdict: 'IMPL-DEFECT', criteria: [{ criterion: 'c', status: 'fail', evidence: 'e' }], pending_human: [] }
  let v = 0
  const { result, calls } = await run(PATCH_BASE, standard({
    delta: SMALL(),
    verifier: () => (v++ < 2 ? fail : PASS),
    'docs-sync-reviewer': label => (label.endsWith(':r2') || label.endsWith(':r3') ? { ...CLEAN, blocking: [FIXED] } : CLEAN),
  }))
  assert.equal(result.outcome, 'CAP')
  assert.deepEqual(implementers(calls), ['implementer:r0', 'implementer:r1', 'implementer:r2', 'patch-implementer:r3'])
})

test('patch: patch rounds already spent are read from State and keep counting', async () => {
  const prompts = {}
  const state = { ...PATCH_BASE, round: 3, reviewers: { 'docs-sync-reviewer': 'blocking' }, state: '## State\nround: 3\nphase: implement\npatch rounds: 1\n' }
  const { result, calls } = await run(state, recording(prompts, standard({ delta: SMALL() })))
  assert.equal(result.outcome, 'PASS')
  assert.ok(calls.includes('implementer:r3'), 'round 3 with one patch spent is the third counted round, not past the cap')
  assert.match(prompts['scribe:r3'], /patch rounds: 1/)
  const control = await run({ ...state, state: '## State\nround: 3\nphase: implement\n' }, standard({ delta: SMALL() }))
  assert.equal(control.result.outcome, 'CAP', 'control: without patch rounds, round 3 is past the cap')
})

test('patch: the Log line of a BLOCKING finding carries its fix', async () => {
  const prompts = {}
  await run(PATCH_BASE, recording(prompts, standard({ delta: SMALL(), 'docs-sync-reviewer': blockingOnce(FIXED) })))
  assert.ok(prompts['scribe:r0'].includes(`— fix: ${FIXED.fix}`))
  assert.ok(prompts['scribe:r0'].includes('next: patch round'))
  assert.ok(prompts['scribe:r1'].includes('patch: held'))
})

test('patch: reviewers are told what a fix is and when to leave it out', async () => {
  const prompts = {}
  await run(PATCH_BASE, recording(prompts, standard()))
  assert.match(prompts['docs-sync-reviewer:r0'], /'fix'/)
  assert.match(prompts['docs-sync-reviewer:r0'], /leave 'fix' out/)
})

test('the verifier is sent to the criteria runner first, and told it judges nothing', async () => {
  const prompts = {}
  const reply = (label, prompt) => { prompts[label] = prompt; return standard()(label) }
  await run(BASE, reply)
  assert.ok(prompts['verifier:r0'].includes('py -3 tools/run_criteria.py "p.md"'), 'the runner gets the plan path')
  assert.match(prompts['verifier:r0'], /run_in_background: true/)
  assert.match(prompts['verifier:r0'], /it judges nothing/)
  assert.match(prompts['verifier:r0'], /--start/)
  assert.match(prompts['verifier:r0'], /A root suite the runner already ran is the suite run/)
})

// --- items mode (3a, 3b) -----------------------------------------------------
//
// The scheduler is tested as the pure functions it is, cut out of the script
// between its @scheduler markers; the engine around it with stub agents that
// take a few milliseconds each, so "at the same time" is observable.
const schedSrc = src.slice(src.indexOf('// @scheduler-begin'), src.indexOf('// @scheduler-end'))
const sched = new Function(`${schedSrc}\nreturn { nextToStart, newlyHeld, invalidatedBy, drainedItems, pathsOverlap, unblockedItems, buildWaitsFor, staleBuilds, readsPath }`)()
const IT = (id, files, extra = {}) => ({ id, files, after: [], shares: [], checks: [], ...extra })
const ST = (items, statuses = {}) => Object.fromEntries(items.map(it => [it.id, { status: 'pending', touched: false, ...(statuses[it.id] || {}) }]))

test('scheduler: items on disjoint files start together, up to the parallel cap', () => {
  const items = [IT('a', ['panel/a.css']), IT('b', ['panel/b.css']), IT('c', ['docs/c.md'])]
  assert.deepEqual(sched.nextToStart(items, ST(items), 4), ['a', 'b', 'c'])
  assert.deepEqual(sched.nextToStart(items, ST(items), 2), ['a', 'b'])
})

test('scheduler: items sharing a file run one at a time, in plan order', () => {
  const items = [IT('a', ['panel/app.css', 'panel/a.js']), IT('b', ['panel/app.css']), IT('c', ['panel/c.js'])]
  assert.deepEqual(sched.nextToStart(items, ST(items), 4), ['a', 'c'], 'b queues behind a; c is free')
  assert.deepEqual(sched.nextToStart(items, ST(items, { a: { status: 'running' } }), 4), ['c'])
  assert.deepEqual(sched.nextToStart(items, ST(items, { a: { status: 'done' } }), 4), ['b', 'c'])
  // A glob in one and a literal in the other is the same file.
  const globbed = [IT('x', ['panel/src/*.css']), IT('y', ['panel/src/toolbar.css'])]
  assert.deepEqual(sched.nextToStart(globbed, ST(globbed), 4), ['x'])
})

test('scheduler: after: waits for its item; a parked one holds it, and only it', () => {
  const items = [IT('tokens', ['t.css']), IT('toolbar', ['bar.css'], { after: ['tokens'] }), IT('docs', ['d.md'])]
  assert.deepEqual(sched.nextToStart(items, ST(items), 4), ['tokens', 'docs'])
  const st = ST(items, { tokens: { status: 'parked', touched: true } })
  assert.deepEqual(sched.newlyHeld(items, st).map(h => h.id), ['toolbar'])
  assert.deepEqual(sched.nextToStart(items, st, 4), ['docs'], 'the unrelated item keeps flowing')
})

test('scheduler: an item parked before it started does not block its file-sharers; one parked mid-edit does', () => {
  const items = [IT('ask', ['panel/app.css']), IT('other', ['panel/app.css']), IT('free', ['x.md'])]
  const untouched = ST(items, { ask: { status: 'parked', touched: false } })
  assert.deepEqual(sched.nextToStart(items, untouched, 4), ['other', 'free'])
  assert.deepEqual(sched.newlyHeld(items, untouched), [])
  const touched = ST(items, { ask: { status: 'parked', touched: true } })
  assert.deepEqual(sched.nextToStart(items, touched, 4), ['free'])
  assert.deepEqual(sched.newlyHeld(items, touched).map(h => h.id), ['other'])
})

test('scheduler: a fix with unknown files runs alone, after everything before it', () => {
  const items = [IT('a', ['a.css']), IT('b', ['b.css']), IT('fix-1', '*')]
  assert.deepEqual(sched.nextToStart(items, ST(items), 4), ['a', 'b'])
  assert.deepEqual(sched.nextToStart(items, ST(items, { a: { status: 'done' }, b: { status: 'running' } }), 4), [])
  assert.deepEqual(sched.nextToStart(items, ST(items, { a: { status: 'done' }, b: { status: 'done' } }), 4), ['fix-1'])
  const later = [...items, IT('c', ['c.css'])]
  assert.deepEqual(sched.nextToStart(later, ST(later, { a: { status: 'done' }, b: { status: 'done' }, 'fix-1': { status: 'running' } }), 4), [], 'nothing beside it')
})

test('scheduler: a PLAN-DEFECT holds only the items it may invalidate', () => {
  const items = [IT('bad', ['a.css'], { checks: ['`npm test` exits 0'] }), IT('sharer', ['a.css'], { shares: ['bad'] }),
    IT('dependent', ['d.css'], { after: ['bad'] }), IT('same-check', ['e.css'], { checks: ['`npm test` passes'] }), IT('free', ['f.md'])]
  assert.deepEqual(sched.invalidatedBy(items, ST(items), 'bad').sort(), ['dependent', 'same-check', 'sharer'])
})

test('scheduler: overlap matches plan_lint on its lane cases', () => {
  for (const [a, b] of [['docs/**', 'docs/agents/*.md'], ['ForgePact/docs/', 'ForgePact/docs/x.md'], ['docs/', '*.md'], ['docs/agents/', 'docs/*.md']]) {
    assert.ok(sched.pathsOverlap(a, b), `${a} / ${b}`)
  }
  assert.ok(!sched.pathsOverlap('tools/a*.py', 'tools/b*.py'), 'control: diverging prefixes')
})

const ITEMS_BASE = { ...BASE, reviewers: { 'docs-sync-reviewer': 'never' },
  items: [
    { id: 'a', title: 'toolbar', files: ['panel/a.css'], checks: ['`npm test` exits 0'] },
    { id: 'b', title: 'tray', files: ['panel/b.css'], checks: ['`npm test` exits 0'] },
    { id: 'c', title: 'docs', files: ['docs/c.md'], checks: ['`grep x docs/c.md` prints 1'] },
  ] }
const itemOf = label => (label.match(/^(?:item-implementer|item-verifier|fix-implementer):([a-z0-9-]+):/) || [])[1]
const itemsReply = (overrides = {}) => label => {
  for (const [prefix, value] of Object.entries(overrides)) if (label.startsWith(prefix)) return typeof value === 'function' ? value(label) : value
  if (label.startsWith('snapshot')) return HEADS([{ repo: '.', sha: 'base000' }])
  if (label.startsWith('item-implementer') || label.startsWith('fix-implementer')) {
    const id = itemOf(label)
    return { ...DONE, commits: [{ repo: '.', sha: `sha-${id}` }], paths: [`panel/${id}.css`], flags: '' }
  }
  if (label.startsWith('item-verifier') || label.startsWith('verifier')) return PASS
  if (label.startsWith('scribe')) return { written: true, note: '' }
  return { ...CLEAN, reviewed_heads: [{ repo: '.', sha: 'head' }] }
}
// Every stub takes a few ms, and the run records which agents overlapped.
async function runTimed(args, reply) {
  const calls = [], spans = {}, prompts = {}
  let clock = 0
  const agent = async (prompt, opts) => {
    calls.push(opts.label); prompts[opts.label] = prompt
    const start = ++clock
    await new Promise(r => setTimeout(r, 15))
    spans[opts.label] = [start, ++clock]
    return reply(opts.label, prompt, opts)
  }
  const parallel = thunks => Promise.all(thunks.map(t => t().catch(() => null)))
  const result = await script(args, agent, parallel, null, () => {}, () => {}, {}, null)
  return { result, calls, spans, prompts }
}
const overlaps = (s, x, y) => s[x][0] < s[y][1] && s[y][0] < s[x][1]
const impl = (calls, id) => calls.find(c => c.startsWith(`item-implementer:${id}:`))

test('items: disjoint items are implemented at the same time, and the whole-tree gate runs once', async () => {
  const { result, calls, spans } = await runTimed(ITEMS_BASE, itemsReply())
  assert.equal(result.outcome, 'PASS')
  assert.ok(overlaps(spans, impl(calls, 'a'), impl(calls, 'b')) && overlaps(spans, impl(calls, 'b'), impl(calls, 'c')), 'items ran one after another')
  assert.deepEqual(calls.filter(c => /^verifier:/.test(c)), ['verifier:r0'], 'the full verify ran more or less than once')
  assert.equal(calls.filter(c => c.startsWith('item-verifier:')).length, 3, 'each item gets its own targeted check')
  const before = calls.filter(c => c !== 'verifier:r0' && !c.startsWith('scribe'))
  assert.ok(spans['verifier:r0'][0] > Math.max(...before.map(c => spans[c][1])), 'the gate ran before the queue drained')
  assert.deepEqual(result.items.map(i => i.status), ['done', 'done', 'done'])
})

test('items: items sharing a file never overlap, and run in plan order', async () => {
  const args = { ...ITEMS_BASE, items: [
    { id: 'a', files: ['panel/app.css', 'panel/a.js'], checks: ['`npm test` ok'] },
    { id: 'b', files: ['panel/app.css'], shares: ['a'], checks: ['`npm test` ok'] },
    { id: 'c', files: ['docs/c.md'], checks: ['`grep x y` ok'] },
  ] }
  const { result, calls, spans } = await runTimed(args, itemsReply())
  assert.equal(result.outcome, 'PASS')
  assert.ok(!overlaps(spans, impl(calls, 'a'), impl(calls, 'b')), 'a and b edited app.css at the same time')
  assert.ok(spans[impl(calls, 'a')][0] < spans[impl(calls, 'b')][0], 'b went before a')
  assert.ok(overlaps(spans, impl(calls, 'a'), impl(calls, 'c')), 'control: the disjoint item ran beside a')
})

test('items: a parked item does not block the others, and the gate waits for it', async () => {
  const advice = { ...DONE, verdict: 'ADVICE-NEEDED', question: 'which token?', commits: [], paths: [] }
  const { result, calls } = await runTimed(ITEMS_BASE, itemsReply({ 'item-implementer:b:': advice }))
  assert.equal(result.outcome, 'PARKED')
  assert.deepEqual(result.items.map(i => [i.id, i.status]), [['a', 'done'], ['b', 'parked'], ['c', 'done']])
  assert.match(result.items[1].evidence, /which token/)
  assert.ok(!calls.some(c => /^verifier:/.test(c)), 'the whole-tree gate ran with an item parked')
})

test('items: an owner question parks only its item until the driver passes it as answered', async () => {
  const args = { ...ITEMS_BASE, items: [...ITEMS_BASE.items, { id: 'd', files: ['panel/d.css'], owner: 'keep the old tray?', checks: ['`npm test` ok'] }] }
  let r = await runTimed(args, itemsReply())
  assert.equal(r.result.outcome, 'PARKED')
  assert.ok(!r.calls.some(c => c.startsWith('item-implementer:d:')))
  assert.equal(r.result.items.find(i => i.id === 'd').reason, 'owner: keep the old tray?')
  assert.deepEqual(r.result.items.filter(i => i.status === 'done').map(i => i.id), ['a', 'b', 'c'])
  assert.match(r.prompts['scribe:r0'], /items: a=done; b=done; c=done; d=parked\n/)
  // The relaunch: done items stay done, the answered item runs, the gate runs once.
  let docs = 0
  const blockingOnceOnD = () => (docs++ === 0
    ? { ...CLEAN, blocking: [{ where: 'panel/d.css:1', problem: 'p', evidence: 'e' }], reviewed_heads: [{ repo: '.', sha: 'h' }] }
    : { ...CLEAN, reviewed_heads: [{ repo: '.', sha: 'h2' }] })
  const state = '## State\nround: 1\nitems: a=done; b=done; c=done; d=parked; fix-1=done\n'
  r = await runTimed({ ...args, answered: ['d'], state, round: 1 }, itemsReply({ 'docs-sync-reviewer': blockingOnceOnD }))
  assert.equal(r.result.outcome, 'PASS')
  assert.deepEqual(r.calls.filter(c => c.startsWith('item-implementer:')), ['item-implementer:d:a1:r1'])
  assert.match(r.prompts['item-implementer:d:a1:r1'], /### Decisions/)
  assert.ok(r.calls.includes('fix-implementer:fix-1:r1'), 'a stale fix-1=done in State skipped this launch\'s own fix')
})

test('items: a failed targeted check retries the item with the evidence, within its budget', async () => {
  let checks = 0
  const failing = () => (checks++ === 0 ? { verdict: 'IMPL-DEFECT', criteria: [{ criterion: 'npm test', status: 'fail', evidence: 'expected 2 got 3' }], pending_human: [] } : PASS)
  const { result, calls, prompts } = await runTimed(ITEMS_BASE, itemsReply({ 'item-verifier:a:': failing }))
  assert.equal(result.outcome, 'PASS')
  assert.ok(calls.includes('item-implementer:a:a2:r0'))
  assert.match(prompts['item-implementer:a:a2:r0'], /expected 2 got 3/)
  const always = { verdict: 'IMPL-DEFECT', criteria: [{ criterion: 'npm test', status: 'fail', evidence: 'no' }], pending_human: [] }
  const spent = await runTimed(ITEMS_BASE, itemsReply({ 'item-verifier:a:': always }))
  assert.equal(spent.result.outcome, 'PARKED')
  assert.match(spent.result.items[0].reason, /^budget: 3 attempts/)
  assert.ok(!spent.calls.includes('item-implementer:a:a4:r0'))
})

test('items: a BLOCKING review finding becomes a fix on its file, re-reviewed, then the gate once', async () => {
  let passes = 0
  const docs = () => (passes++ === 0
    ? { ...CLEAN, blocking: [{ where: 'panel/a.css:12', problem: 'wrong token', evidence: 'x', fix: 'use --accent' }], reviewed_heads: [{ repo: '.', sha: 'h1' }] }
    : { ...CLEAN, reviewed_heads: [{ repo: '.', sha: 'h2' }] })
  const { result, calls, prompts } = await runTimed(ITEMS_BASE, itemsReply({ 'docs-sync-reviewer': docs }))
  assert.equal(result.outcome, 'PASS')
  assert.ok(calls.includes('fix-implementer:fix-1:r0'))
  assert.match(prompts['fix-implementer:fix-1:r0'], /Your file set is `panel\/a\.css`/)
  assert.match(prompts['fix-implementer:fix-1:r0'], /use --accent/)
  const lastReview = calls.filter(c => c.startsWith('docs-sync-reviewer:')).pop()
  assert.ok(calls.indexOf(lastReview) > calls.indexOf('fix-implementer:fix-1:r0'), 'the reviewer never re-read the fix')
  assert.deepEqual(calls.filter(c => /^verifier:/.test(c)), ['verifier:r0'])
})

test('items: reviewers read pinned commits and are told what is still in flight', async () => {
  const { prompts, calls } = await runTimed(ITEMS_BASE, itemsReply())
  const first = prompts[calls.find(c => c.startsWith('docs-sync-reviewer:'))]
  assert.match(first, /git -C \. rev-parse HEAD/)
  assert.match(first, /git -C \. diff base000 <that sha>/)
  assert.match(first, /never from the working tree/)
  assert.ok(!/Workorder: p\.md/.test(first), 'a reviewer was handed the workorder')
})

test('items: a whole-tree failure becomes one fix that runs alone, then the gate again', async () => {
  let gates = 0
  const gate = () => (gates++ === 0 ? { verdict: 'IMPL-DEFECT', criteria: [{ criterion: 'suite', status: 'fail', evidence: 'FAILED (errors=1)' }], pending_human: [] } : PASS)
  const { result, calls, prompts } = await runTimed(ITEMS_BASE, itemsReply({ 'verifier:': gate }))
  assert.equal(result.outcome, 'PASS')
  assert.deepEqual(calls.filter(c => /^verifier:/.test(c)), ['verifier:r0', 'verifier:g2:r0'])
  assert.match(prompts['fix-implementer:gate-fix-1:r0'], /FAILED \(errors=1\)/)
  assert.match(prompts['fix-implementer:gate-fix-1:r0'], /you run alone/)
})

test('items: a PLAN-DEFECT parks its item and holds only what it may invalidate', async () => {
  const args = { ...ITEMS_BASE, maxParallel: 1, items: [
    { id: 'a', files: ['panel/a.css'], checks: ['`npm test` ok'] },
    { id: 'b', files: ['panel/b.css'], after: ['a'], checks: ['`grep b x` ok'] },
    { id: 'c', files: ['docs/c.md'], checks: ['`grep c x` ok'] },
  ] }
  const defect = { ...DONE, verdict: 'PLAN-DEFECT', evidence: 'STEP 1: no such token', commits: [], paths: [] }
  const { result } = await runTimed(args, itemsReply({ 'item-implementer:a:': defect }))
  assert.equal(result.outcome, 'PARKED')
  assert.deepEqual(result.items.map(i => [i.id, i.status]), [['a', 'parked'], ['b', 'held'], ['c', 'done']])
})

test('items: the scribe records every item and State carries the items line', async () => {
  const { prompts } = await runTimed({ ...ITEMS_BASE, state: '## State\nround: 0\ngates: none\n' }, itemsReply())
  assert.match(prompts['scribe:r0'], /### Round 0 \(items\)/)
  assert.match(prompts['scribe:r0'], /items: a=done; b=done; c=done/)
  assert.match(prompts['scribe:r0'], /gates: none/, 'a driver-owned State line was dropped')
})

test('items: args that could not have come from plan_lint --items-json are refused', async () => {
  for (const items of [[{ id: 'Bad', files: ['a'] }], [{ id: 'a', files: [] }], [{ id: 'a', files: ['x'] }, { id: 'a', files: ['y'] }],
    [{ id: 'a', files: ['x'], after: ['ghost'] }]]) {
    const { result, calls } = await runTimed({ ...ITEMS_BASE, items }, itemsReply())
    assert.equal(result.outcome, 'BAD-ARGS', JSON.stringify(items))
    assert.equal(calls.length, 0)
  }
  const both = await runTimed({ ...ITEMS_BASE, lanes: [{ name: 'x', files: ['x'] }], join: true }, itemsReply())
  assert.equal(both.result.outcome, 'BAD-ARGS')
})

test('items: the implementer commits through item_commit and runs its own checks first', async () => {
  const { prompts } = await runTimed(ITEMS_BASE, itemsReply())
  const p = prompts['item-implementer:a:a1:r0']
  assert.match(p, /py -3 tools\/item_commit\.py --message "zz a: toolbar" -- <paths>/)
  assert.match(p, /run_criteria\.py "p\.md" --item a --jobs auto/)
  assert.match(p, /"When you are one item"/)
  assert.match(prompts['item-verifier:a:a1:r0'], /--item a --jobs auto/)
  assert.match(prompts['item-verifier:a:a1:r0'], /do not run the root suite/)
})

test('items: a streaming plan pulls newly released items while the first ones run', async () => {
  let refills = 0
  const refill = () => (refills++ === 0
    ? { exit_code: 0, items: [{ id: 'late', title: 'late', files: ['late.md'], checks: ['`grep a b` ok'] }], complete: false, raw_output: '' }
    : { exit_code: 0, items: [], complete: true, raw_output: '' })
  const { result, calls, prompts } = await runTimed({ ...ITEMS_BASE, streaming: true }, itemsReply({ refill }))
  assert.equal(result.outcome, 'PASS')
  assert.ok(calls.includes('item-implementer:late:a1:r0'))
  assert.match(prompts['refill:1:r0'], /--items-json --known a,b,c --wait 480/)
  assert.ok(calls.indexOf('verifier:r0') > calls.indexOf('refill:2:r0'), 'the gate ran before planning was complete')
})

test('scheduler: an earlier item waiting (after:) on a later file-sharer does not hold it, so neither deadlocks', () => {
  // PR #239 review: a (declared first, after: b) and b share x.css.
  const items = [IT('a', ['x.css'], { after: ['b'] }), IT('b', ['x.css'])]
  assert.deepEqual(sched.nextToStart(items, ST(items), 4), ['b'])
  assert.deepEqual(sched.nextToStart(items, ST(items, { b: { status: 'done' } }), 4), ['a'])
  // Through a chain, too: a after c, c after b.
  const chain = [IT('a', ['x.css'], { after: ['c'] }), IT('b', ['x.css']), IT('c', ['y.css'], { after: ['b'] })]
  assert.deepEqual(sched.nextToStart(chain, ST(chain), 4), ['b'])
  // Control: an earlier sharer that does not wait on it still goes first.
  const plain = [IT('a', ['x.css']), IT('b', ['x.css'])]
  assert.deepEqual(sched.nextToStart(plain, ST(plain), 4), ['a'])
})

test('items: a fixer that disputes a finding and commits nothing is re-reviewed before any gate', async () => {
  // PR #239 review: with no new commit the blocking reviewer was never due,
  // and the gate still ran and passed.
  let passes = 0
  const finding = { where: 'panel/a.css:12', problem: 'wrong token', evidence: 'x' }
  const docs = () => (passes++ === 0 ? { ...CLEAN, blocking: [finding], reviewed_heads: [{ repo: '.', sha: 'h1' }] }
    : { ...CLEAN, reviewed_heads: [{ repo: '.', sha: 'h1' }] })
  const disputes = { ...DONE, report: 'the token is right: tokens.css:4 defines it', commits: [], paths: [] }
  const { result, calls, prompts } = await runTimed(ITEMS_BASE, itemsReply({ 'docs-sync-reviewer': docs, 'fix-implementer': disputes }))
  assert.equal(result.outcome, 'PASS')
  const recheck = calls.filter(c => c.startsWith('docs-sync-reviewer:')).pop()
  assert.ok(calls.indexOf(recheck) > calls.indexOf('fix-implementer:fix-1:r0'), 'the disputed finding was never re-read')
  assert.match(prompts[recheck], /the fixer disputes/)
  assert.match(prompts[recheck], /tokens\.css:4 defines it/)
  assert.ok(calls.indexOf('verifier:r0') > calls.indexOf(recheck), 'the gate ran before the reviewer confirmed or withdrew')
  // Control: a reviewer that holds its finding after the dispute keeps the
  // run from passing -- it raises another fix, and at its cap the run parks.
  const stubborn = () => ({ ...CLEAN, blocking: [finding], reviewed_heads: [{ repo: '.', sha: 'h1' }] })
  const held = await runTimed(ITEMS_BASE, itemsReply({ 'docs-sync-reviewer': stubborn, 'fix-implementer': disputes }))
  assert.equal(held.result.outcome, 'PARKED')
  assert.ok(!held.calls.includes('verifier:r0'), 'the gate ran over an open BLOCKING finding')
})

// --- a build is re-run after a commit lands on what it reads --------------
//
// forgepact-124-pet-relics, 2026-10-02: `build-dev` passed, a reviewer's fix
// then committed to ForgePact/plugin, and the launch came back PARKED with
// build-dev=done and a DLL older than the fix -- three times in one day.
const BUILD = (extra = {}) => IT('build-dev', ['ForgePact/plugin_build/build.log'], { kind: 'item', buildReads: ['ForgePact/plugin/**'], ...extra })

test('scheduler: readsPath matches plan_lint.reads_path on its cases', () => {
  for (const [g, p] of [['*', 'a/b.c'], ['ForgePact/plugin/**', 'ForgePact/plugin/x/y.cpp'], ['ForgePact/plugin', 'ForgePact/plugin/a.cpp'],
    ['**/x.py', 'x.py'], ['dir/**/*.ts', 'dir/a.ts'], ['tools/x.py', 'tools/x.py']]) assert.ok(sched.readsPath(g, p), `${g} / ${p}`)
  for (const [g, p] of [['ForgePact/plugin/**', 'ForgePact/panel/a.js'], ['ForgePact/plugin', 'ForgePact/plugin2/a.cpp'], ['tools/x.py', 'tools/x.pyc']]) {
    assert.ok(!sched.readsPath(g, p), `control: ${g} / ${p}`)
  }
})

test('scheduler: a build waits for a fix queued on what it reads, and only for that', () => {
  const fix = IT('fix-1', ['ForgePact/plugin/a.cpp'], { kind: 'fix' })
  const items = [BUILD(), IT('docs', ['docs/d.md'], { kind: 'item' }), fix]
  assert.deepEqual(sched.nextToStart(items, ST(items), 4), ['docs', 'fix-1'], 'the build started under a queued fix on its sources')
  assert.deepEqual(sched.nextToStart(items, ST(items, { 'fix-1': { status: 'running' } }), 4), ['docs'])
  assert.deepEqual(sched.nextToStart(items, ST(items, { 'fix-1': { status: 'done' } }), 4), ['build-dev', 'docs'])
  // Control: a fix elsewhere, or an item without build_reads, does not wait.
  const elsewhere = [BUILD(), IT('fix-1', ['docs/d.md'], { kind: 'fix' })]
  assert.deepEqual(sched.nextToStart(elsewhere, ST(elsewhere), 4), ['build-dev', 'fix-1'])
  const plain = [BUILD({ buildReads: [] }), fix]
  assert.deepEqual(sched.nextToStart(plain, ST(plain), 4), ['build-dev', 'fix-1'])
  // A pending plan item on its sources does not hold it: `after:` orders those.
  const planned = [BUILD(), IT('src', ['ForgePact/plugin/a.cpp'], { kind: 'item' })]
  assert.deepEqual(sched.nextToStart(planned, ST(planned), 4), ['build-dev', 'src'])
})

test('scheduler: a fix with unknown files is not queued behind the build that waits for it', () => {
  const items = [BUILD(), IT('fix-1', '*', { kind: 'fix' })]
  assert.deepEqual(sched.nextToStart(items, ST(items), 4), ['fix-1'], 'build and fix each waited on the other')
  assert.ok(sched.buildWaitsFor(items, ST(items), items[0]))
})

test('scheduler: a build, a fix and an item after the build never wait on each other forever (PR #382 review)', () => {
  // X and W feed build B; Y runs after B on src; fix-1 has no path, so '*'.
  const items = [IT('x', ['src/x.cpp'], { kind: 'item' }), IT('w', ['docs/w.md'], { kind: 'item' }),
    IT('b', ['out/b.log'], { kind: 'item', after: ['x', 'w'], buildReads: ['src/**'] }),
    IT('y', ['src/y.cpp'], { kind: 'item', after: ['b'] }), IT('fix-1', '*', { kind: 'fix' })]
  const st = ST(items, { x: { status: 'done' }, w: { status: 'done' } })
  assert.deepEqual(sched.nextToStart(items, st, 4), ['fix-1'], 'y, queued only behind the waiting build, held the fix')
  // The fallback: whatever holds the fix, a pass that would start nothing
  // with nothing running drops the build wait and starts the build.
  const stuck = [IT('b2', ['out/b.log'], { kind: 'item', buildReads: ['src/**'] }), IT('fix-2', ['src/a.cpp'], { kind: 'fix', after: ['gone'] })]
  const st2 = ST(stuck, {}); st2.gone = { status: 'pending' }
  assert.deepEqual(sched.nextToStart(stuck, st2, 4), ['b2'])
  // Control: with something running, the build keeps waiting.
  const busy = [...stuck, IT('r', ['z.md'], { kind: 'item' })]
  const st3 = ST(busy, { r: { status: 'running' } }); st3.gone = { status: 'pending' }
  assert.deepEqual(sched.nextToStart(busy, st3, 4), [])
})

test('scheduler: staleBuilds names the done or running builds a commit reached, never its own author', () => {
  const items = [BUILD(), IT('panel-build', ['x.log'], { kind: 'item', buildReads: ['ForgePact/panel/**'] }), IT('src', ['ForgePact/plugin/a.cpp'], { kind: 'item' })]
  const ids = (st, by, paths) => sched.staleBuilds(items, st, by, paths).map(it => it.id)
  assert.deepEqual(ids(ST(items, { 'build-dev': { status: 'done' }, 'panel-build': { status: 'done' } }), 'fix-1', ['ForgePact/plugin/a.cpp']), ['build-dev'])
  assert.deepEqual(ids(ST(items, { 'build-dev': { status: 'running' } }), 'fix-1', ['ForgePact/plugin/a.cpp']), ['build-dev'])
  assert.deepEqual(ids(ST(items, { 'build-dev': { status: 'pending' } }), 'fix-1', ['ForgePact/plugin/a.cpp']), [], 'a pending build has not built yet')
  assert.deepEqual(ids(ST(items, { 'build-dev': { status: 'done' } }), 'build-dev', ['ForgePact/plugin/a.cpp']), [], 'its own commit')
  assert.deepEqual(ids(ST(items, { 'build-dev': { status: 'done' } }), 'fix-1', ['docs/x.md']), [], 'control: a path it does not read')
})

// The 2026-10-02 sequence: `src` lands, `build-dev` (after src) builds, the
// reviewer reads src and raises a finding on it, and fix-1 commits to it.
const BUILD_ITEMS = { ...ITEMS_BASE, items: [
  { id: 'src', title: 'relic drop', files: ['ForgePact/plugin/a.cpp'], checks: ['`grep -c x ForgePact/plugin/a.cpp` prints 1'] },
  { id: 'build-dev', title: 'dev build', files: ['ForgePact/plugin_build/build.log'], after: ['src'],
    checks: ['`cd ForgePact && cmd //c "plugin_build\\build.bat dev"` exits 0 (reads `ForgePact/plugin/**`)'], build_reads: ['ForgePact/plugin/**'] },
] }
const buildReply = where => {
  let passes = 0
  return itemsReply({
    'item-implementer:src:': { ...DONE, commits: [{ repo: 'ForgePact', sha: 's1' }], paths: ['ForgePact/plugin/a.cpp'], flags: '' },
    'item-implementer:build-dev:': { ...DONE, commits: [], paths: [], flags: '' },
    'fix-implementer:fix-1:': { ...DONE, commits: [{ repo: 'ForgePact', sha: 'f1' }], paths: [where], flags: '' },
    'docs-sync-reviewer': () => (passes++ === 0
      ? { ...CLEAN, blocking: [{ where: `${where}:3`, problem: 'p', evidence: 'e' }], reviewed_heads: [{ repo: '.', sha: 'h1' }] }
      : { ...CLEAN, reviewed_heads: [{ repo: '.', sha: 'h2' }] }),
  })
}
// runTimed with a per-label delay, so which of build and fix ends first is set.
async function runDelayed(args, reply, delays) {
  const calls = [], spans = {}, prompts = {}
  let clock = 0
  const agent = async (prompt, opts) => {
    calls.push(opts.label); prompts[opts.label] = prompt
    const start = ++clock
    const ms = Object.entries(delays).find(([k]) => opts.label.startsWith(k))
    await new Promise(r => setTimeout(r, ms ? ms[1] : 15))
    spans[opts.label] = [start, ++clock]
    return reply(opts.label, prompt, opts)
  }
  const parallel = thunks => Promise.all(thunks.map(t => t().catch(() => null)))
  const result = await script(args, agent, parallel, null, () => {}, () => {}, {}, null)
  return { result, calls, spans, prompts }
}
const builds = calls => calls.filter(c => c.startsWith('item-implementer:build-dev:'))

for (const [when, delays] of [['after the build is done', { 'docs-sync-reviewer': 120 }], ['while the build runs', { 'item-implementer:build-dev:a1': 150 }]]) {
  test(`items: a fix that lands on what a build read ${when} re-runs the build after it`, async () => {
    const { result, calls, spans, prompts } = await runDelayed(BUILD_ITEMS, buildReply('ForgePact/plugin/a.cpp'), delays)
    assert.equal(result.outcome, 'PASS')
    const b = builds(calls)
    assert.equal(b.length, 2, `the build ran ${b.length} time(s): ${calls.join(', ')}`)
    assert.ok(spans[b[1]][0] > spans['fix-implementer:fix-1:r0'][1], 'the second build started before the fix landed')
    assert.match(prompts[b[1]], /fix-1 committed `ForgePact\/plugin\/a\.cpp`/)
    const row = result.items.find(i => i.id === 'build-dev')
    assert.equal(row.rebuilds, 1)
    assert.equal(row.status, 'done')
    assert.ok(spans['verifier:r0'][0] > spans[b[1]][1], 'the gate ran on the old build')
  })
}

test('items: a fix that lands during an attempt whose checks then fail is in the retry, so no extra rebuild (PR #382 review)', async () => {
  let checks = 0
  const failsOnce = () => (checks++ === 0 ? { verdict: 'IMPL-DEFECT', criteria: [{ criterion: 'build', status: 'fail', evidence: 'link error' }], pending_human: [] } : PASS)
  const reply = buildReply('ForgePact/plugin/a.cpp')
  const { result, calls } = await runDelayed(BUILD_ITEMS, (label, ...rest) => label.startsWith('item-verifier:build-dev:') ? failsOnce() : reply(label, ...rest),
    { 'item-implementer:build-dev:a1': 150 })
  assert.equal(result.outcome, 'PASS')
  assert.deepEqual(builds(calls), ['item-implementer:build-dev:a1:r0', 'item-implementer:build-dev:a2:r0'], 'the retry already built the fixed tree')
  assert.equal(result.items.find(i => i.id === 'build-dev').rebuilds, undefined)
})

test('items: control -- a fix outside what the build reads, or a build with no build_reads, is not re-run', async () => {
  let r = await runDelayed(BUILD_ITEMS, buildReply('docs/c.md'), { 'docs-sync-reviewer': 120 })
  assert.equal(r.result.outcome, 'PASS')
  assert.equal(builds(r.calls).length, 1)
  const plain = { ...BUILD_ITEMS, items: BUILD_ITEMS.items.map(it => ({ ...it, build_reads: undefined })) }
  r = await runDelayed(plain, buildReply('ForgePact/plugin/a.cpp'), { 'docs-sync-reviewer': 120 })
  assert.equal(r.result.outcome, 'PASS')
  assert.equal(builds(r.calls).length, 1, 'without build_reads the engine has nothing to compare a commit with')
})

test('items: a relaunch re-runs a build State left done once this launch\'s fix lands on it', async () => {
  const args = { ...BUILD_ITEMS, round: 1, reviewers: { 'docs-sync-reviewer': 'blocking' },
    priorFindings: { 'docs-sync-reviewer': [{ where: 'ForgePact/plugin/a.cpp:3', problem: 'p' }] },
    state: '## State\nround: 1\nitems: src=done; build-dev=done\n' }
  const { result, calls } = await runDelayed(args, buildReply('ForgePact/plugin/a.cpp'), {})
  assert.equal(result.outcome, 'PASS')
  assert.deepEqual(builds(calls), ['item-implementer:build-dev:a1:r1'], calls.join(', '))
  assert.ok(calls.indexOf('fix-implementer:fix-1:r1') < calls.indexOf('item-implementer:build-dev:a1:r1'), calls.join(', '))
  assert.match(result.items.find(i => i.id === 'build-dev').reason, /^$/)
})

test('items: two builds that commit into what the other reads park at the rebuild cap instead of looping', async () => {
  const args = { ...ITEMS_BASE, reviewers: {}, items: [
    { id: 'panel', files: ['ForgePact/panel/dist/x.js'], checks: ['`npm --prefix ForgePact/panel run build` exits 0 (reads `ForgePact/plugin/**`)'], build_reads: ['ForgePact/plugin/**'] },
    { id: 'plugin', files: ['ForgePact/plugin/gen.h'], checks: ['`cd ForgePact && cmd //c "plugin_build\build.bat dev"` exits 0 (reads `ForgePact/panel/dist/**`)'], build_reads: ['ForgePact/panel/dist/**'] },
  ] }
  const commits = path => ({ ...DONE, commits: [{ repo: 'ForgePact', sha: 'x' }], paths: [path], flags: '' })
  const { result, calls } = await runDelayed(args, itemsReply({
    'item-implementer:panel:': commits('ForgePact/panel/dist/x.js'), 'item-implementer:plugin:': commits('ForgePact/plugin/gen.h') }), {})
  assert.equal(result.outcome, 'PARKED')
  assert.ok(result.items.some(i => /^budget: re-run 5 times/.test(i.reason)), JSON.stringify(result.items.map(i => i.reason)))
  assert.ok(calls.filter(c => c.startsWith('item-implementer:')).length <= 12, `${calls.length} calls`)
})

test('items: a relaunch with every item done still re-reads a reviewer that entered blocking', async () => {
  const args = { ...ITEMS_BASE, round: 1, reviewers: { 'docs-sync-reviewer': 'blocking' },
    priorFindings: { 'docs-sync-reviewer': [{ where: 'docs/c.md', problem: 'stale command' }] },
    state: '## State\nround: 1\nitems: a=done; b=done; c=done\n' }
  const { result, calls, prompts } = await runTimed(args, itemsReply())
  assert.equal(result.outcome, 'PASS')
  assert.ok(calls.includes('docs-sync-reviewer:p1:r1'), 'the blocking reviewer never ran')
  assert.match(prompts['docs-sync-reviewer:p1:r1'], /stale command/)
  assert.ok(calls.indexOf('verifier:r1') > calls.indexOf('docs-sync-reviewer:p1:r1'))
  assert.ok(!calls.some(c => c.startsWith('item-implementer:')), 'a done item ran again')
  // Control: if it still finds the problem, the gate does not run over it.
  const still = { ...CLEAN, blocking: [{ where: 'docs/c.md', problem: 'stale command', evidence: 'x' }], reviewed_heads: [{ repo: '.', sha: 'h' }] }
  const r = await runTimed(args, itemsReply({ 'docs-sync-reviewer': still }))
  assert.ok(r.calls.includes('fix-implementer:fix-1:r1'))
  assert.notEqual(r.result.outcome, 'PASS')
})

// --- 2j: after a small fix, re-run only the checks it can reach -------------
const CRIT = (k, status, extra = {}) => ({ criterion: `c${k}`, status, evidence: 'e', k, ...extra })
const reachRun = async (verifies, overrides = {}, args = BASE) => {
  const prompts = {}
  let v = 0
  const reply = (label, prompt) => {
    prompts[label] = prompt
    return standard({
      snapshot: HEADS([{ repo: '.', sha: 'HUB-SHA' }, { repo: 'ForgePact', sha: 'FP-SHA' }]),
      delta: DELTA(['ForgePact/panel/src/lib/undo.js']),
      verifier: () => verifies[Math.min(v++, verifies.length - 1)],
      ...overrides,
    })(label)
  }
  const { result, calls } = await run(args, reply)
  return { result, calls, prompts }
}
const FAILED_2 = { verdict: 'IMPL-DEFECT', criteria: [CRIT(1, 'pass'), CRIT(2, 'fail'), CRIT(3, 'pass')], pending_human: [] }

test('a fix round after a verify that passed every other criterion re-verifies only what it reaches, plus the failed one', async () => {
  const scopedPass = { verdict: 'PASS', criteria: [CRIT(1, 'not-selected'), CRIT(2, 'pass'), CRIT(3, 'pass')], pending_human: [] }
  const { result, prompts } = await reachRun([FAILED_2, scopedPass])
  assert.ok(!prompts['verifier:r0'].includes('--changed-since'), 'round 0 of a launch has no delta to select by')
  assert.ok(prompts['verifier:r0'].includes("in 'k'"), 'every verifier is asked for the plan numbers')
  assert.ok(prompts['verifier:r1'].includes('--jobs auto --changed-since HUB-SHA --changed-since ForgePact=FP-SHA --failed 2 --out'), prompts['verifier:r1'])
  assert.match(prompts['verifier:r1'], /status 'not-selected'.*never as 'pass'/)
  assert.equal(result.outcome, 'PASS')
  assert.equal(result.verifyScope, 'reach')
  assert.match(result.note, /full set once at the final gate before push/)
})

test('a criterion a reach verify did not select keeps its standing for the next round', async () => {
  const stillFailing = { verdict: 'IMPL-DEFECT', criteria: [CRIT(1, 'not-selected'), CRIT(2, 'fail'), CRIT(3, 'pass')], pending_human: [] }
  const { prompts } = await reachRun([FAILED_2, stillFailing, PASS])
  assert.ok(prompts['verifier:r2'].includes('--changed-since HUB-SHA'), 'criterion 1 still stands at pass')
  assert.ok(prompts['verifier:r2'].includes('--failed 2 --out'))
})

test('the full set runs when a standing is unknown, a number is missing, or the delta or heads are unusable', async () => {
  // Controls for the route above: each takes away one thing it needs.
  const unattempted = { verdict: 'IMPL-DEFECT', criteria: [CRIT(1, 'unattempted'), CRIT(2, 'fail'), CRIT(3, 'pass')], pending_human: [] }
  const unnumbered = { verdict: 'IMPL-DEFECT', criteria: [CRIT(1, 'pass'), { criterion: 'c2', status: 'fail', evidence: 'e' }], pending_human: [] }
  const cases = [
    ['a criterion that could not run', [unattempted, PASS], {}],
    ['a criterion with no number', [unnumbered, PASS], {}],
    ['round_delta exit 3', [FAILED_2, PASS], { delta: DELTA(['x'], { exit_code: 3 }) }],
    ['no heads', [FAILED_2, PASS], { snapshot: DELTA([]) }],
  ]
  for (const [why, verifies, overrides] of cases) {
    const { prompts } = await reachRun(verifies, overrides)
    assert.ok(prompts['verifier:r1'], why)
    assert.ok(!prompts['verifier:r1'].includes('--changed-since'), `${why}: expected the full set`)
  }
})

test('a gate not set is a standing, not an unknown', async () => {
  const gated = { verdict: 'IMPL-DEFECT', criteria: [CRIT(1, 'unattempted', { gate: 'live1: complete' }), CRIT(2, 'fail'), CRIT(3, 'pass')], pending_human: [] }
  const { prompts } = await reachRun([gated, PASS], {}, { ...BASE, state: '## State\ngates: none\n' })
  assert.ok(prompts['verifier:r1'].includes('--changed-since HUB-SHA'))
  assert.ok(prompts['verifier:r1'].includes('--failed 2 --out'), 'the gated criterion is not re-run as failed')
})

// The owner, 2026-10-02: "full suite runs ... should be reserved to the last
// step before the pr. during development only relevant subset should be run."
test('development verifies defer the whole suites; only fullVerify runs the full set', async () => {
  // Round 0 runs --dev: every criterion but the final-gate ones.
  const deferred = { verdict: 'IMPL-DEFECT', criteria: [CRIT(1, 'not-selected'), CRIT(2, 'fail'), CRIT(3, 'pass')], pending_human: [] }
  const dev = await reachRun([deferred, PASS])
  assert.ok(dev.prompts['verifier:r0'].includes('--jobs auto --dev --out'), dev.prompts['verifier:r0'])
  assert.match(dev.prompts['verifier:r0'], /development verify.*never as 'pass'.*skip your procedure's step 3 root suite/)
  // A deferred criterion is a known standing, so the fix round goes by reach.
  assert.ok(dev.prompts['verifier:r1'].includes('--changed-since HUB-SHA --changed-since ForgePact=FP-SHA --failed 2 --out'), dev.prompts['verifier:r1'])
  assert.equal(dev.result.verifyScope, 'reach')
  const once = await reachRun([PASS])
  assert.equal(once.result.outcome, 'PASS')
  assert.equal(once.result.verifyScope, 'dev')
  assert.match(once.result.note, /full set once at the final gate before push/)
  // Control: the final gate before the PR runs every criterion, suites included.
  const full = await reachRun([deferred, PASS], {}, { ...BASE, fullVerify: true })
  assert.ok(!full.prompts['verifier:r0'].includes('--dev'), full.prompts['verifier:r0'])
  assert.ok(!full.prompts['verifier:r1'].includes('--changed-since'), 'under fullVerify an unselected criterion is unknown')
  assert.ok(!('verifyScope' in full.result))
  // The items gate is a development verify too.
  const items = await runTimed(ITEMS_BASE, itemsReply())
  assert.ok(items.prompts['verifier:r0'].includes('--jobs auto --dev --out'), items.prompts['verifier:r0'])
  const itemsFull = await runTimed({ ...ITEMS_BASE, fullVerify: true }, itemsReply())
  assert.ok(!itemsFull.prompts['verifier:r0'].includes('--dev'))
})

// --- goal 4: maxParallel is validated, its default named ---------------------
//
// Measured 2026-09-27: no item in the ForgePact bug batch waited on the cap
// of 4, so the default stays and only the argument is checked. The speed
// report's scope criterion reads DEFAULT_MAX_PARALLEL out of the source.
test('maxParallel: 0, 17 and "x" are refused before a spawn; 1 and 16 run', async () => {
  assert.match(src, /const DEFAULT_MAX_PARALLEL = 4\n/)
  for (const maxParallel of [0, 17, 'x', 2.5, '4']) {
    const { result, calls } = await runTimed({ ...ITEMS_BASE, maxParallel }, itemsReply())
    assert.equal(result.outcome, 'BAD-ARGS', JSON.stringify(maxParallel))
    assert.match(result.detail, /whole number from 1 to 16/)
    assert.equal(calls.length, 0, `${JSON.stringify(maxParallel)}: an agent spawned before the refusal`)
  }
  // Rounds mode takes no items, and a bad value is still a typo worth refusing.
  assert.equal((await run({ ...BASE, maxParallel: 0 }, standard())).result.outcome, 'BAD-ARGS')
  // Controls: the ends of the range run, and 1 really is one at a time.
  const one = await runTimed({ ...ITEMS_BASE, maxParallel: 1 }, itemsReply())
  assert.equal(one.result.outcome, 'PASS')
  assert.ok(!overlaps(one.spans, impl(one.calls, 'a'), impl(one.calls, 'b')), 'maxParallel 1 ran two implementers at once')
  const sixteen = await runTimed({ ...ITEMS_BASE, maxParallel: 16 }, itemsReply())
  assert.equal(sixteen.result.outcome, 'PASS')
  assert.ok(overlaps(sixteen.spans, impl(sixteen.calls, 'a'), impl(sixteen.calls, 'b')))
  const unset = await runTimed(ITEMS_BASE, itemsReply())
  assert.equal(unset.result.outcome, 'PASS', 'no maxParallel is the default, not a refusal')
})

// --- goal 3: a reversible owner question runs on its default ----------------
const OWNED = (id, extra) => ({ id, title: id, files: [`panel/${id}.css`], checks: [`\`grep ${id} x\` ok`], owner: `question ${id}?`, ...extra })

test('owner: a reversible default runs and is listed under defaulted; an irreversible or unmarked item parks', async () => {
  const args = { ...ITEMS_BASE, items: [...ITEMS_BASE.items,
    OWNED('d', { default: 'keep the old tray', reversible: true }),
    OWNED('e', { default: 'drop it', reversible: false }),
    OWNED('f', { default: 'drop it' }),
    OWNED('g', { default: 'none', reversible: true }),
  ] }
  const { result, calls, prompts } = await runTimed(args, itemsReply())
  assert.equal(result.outcome, 'PARKED')
  assert.deepEqual(result.items.map(i => [i.id, i.status]),
    [['a', 'done'], ['b', 'done'], ['c', 'done'], ['d', 'done'], ['e', 'parked'], ['f', 'parked'], ['g', 'parked']])
  assert.match(prompts['item-implementer:d:a1:r0'], /has not answered this item's question \("question d\?"\)/)
  assert.match(prompts['item-implementer:d:a1:r0'], /default "keep the old tray": proceed on that default/)
  assert.ok(!/has answered/.test(prompts['item-implementer:d:a1:r0']))
  // Controls: `reversible: false`, no `reversible` field, and a `none` default all park, unspawned.
  for (const id of ['e', 'f', 'g']) {
    assert.ok(!calls.some(c => c.startsWith(`item-implementer:${id}:`)), `${id} ran`)
    assert.equal(result.items.find(i => i.id === id).reason, `owner: question ${id}?`)
  }
  assert.deepEqual(result.defaulted.map(d => [d.id, d.question, d.default, d.status]), [['d', 'question d?', 'keep the old tray', 'done']])
  assert.deepEqual(result.defaulted[0].commits, [{ repo: '.', sha: 'sha-d' }])
  assert.match(result.defaulted[0].undo, /revert \.:sha-d, record the owner's answer under '### Decisions', and relaunch with 'd' in answered/)
  assert.match(prompts['scribe:r0'], /defaulted \(1\):\n- d: "question d\?" -> default "keep the old tray" \(done\); undo: revert \.:sha-d/)
  assert.match(prompts['scribe:r0'], /items: a=done; b=done; c=done; d=defaulted; e=parked; f=parked; g=parked\n/)
})

test('owner: a defaulted item stays done on a relaunch, and runs again once the owner answers', async () => {
  const args = { ...ITEMS_BASE, round: 1, items: [...ITEMS_BASE.items, OWNED('d', { default: 'keep', reversible: true })],
    state: '## State\nround: 1\nitems: a=done; b=done; c=done; d=defaulted\n' }
  const again = await runTimed(args, itemsReply())
  assert.equal(again.result.outcome, 'PASS')
  assert.ok(!again.calls.some(c => c.startsWith('item-implementer:')), 'a defaulted item ran again with no answer')
  assert.equal(again.result.defaulted[0].id, 'd', 'the defaulted item dropped off the list')
  assert.match(again.prompts['scribe:r1'], /d=defaulted\n/)
  const answered = await runTimed({ ...args, answered: ['d'] }, itemsReply())
  assert.deepEqual(answered.calls.filter(c => c.startsWith('item-implementer:')), ['item-implementer:d:a1:r1'])
  assert.match(answered.prompts['item-implementer:d:a1:r1'], /has answered this item's question/)
  assert.deepEqual(answered.result.defaulted, [])
  assert.match(answered.prompts['scribe:r1'], /d=done\n/)
})

// --- goal 3: a wait on a person names the work that does not wait on it -----
test('unblocked: a PLAN-DEFECT independent of an owner-parked item is listed; the item after the owner one is not', async () => {
  const args = { ...ITEMS_BASE, items: [
    OWNED('o', { default: 'x', reversible: false }),
    { id: 'w', title: 'w', files: ['panel/w.css'], after: ['o'], checks: ['`grep w x` ok'] },
    { id: 'p', title: 'p', files: ['panel/p.css'], checks: ['`grep p x` ok'] },
    { id: 'q', title: 'q', files: ['docs/q.md'], checks: ['`grep q x` ok'] },
  ] }
  const defect = { ...DONE, verdict: 'PLAN-DEFECT', evidence: 'STEP 1: no such token', commits: [], paths: [] }
  const { result, prompts } = await runTimed(args, itemsReply({ 'item-implementer:p:': defect }))
  assert.equal(result.outcome, 'PARKED')
  assert.deepEqual(result.items.map(i => [i.id, i.status]), [['o', 'parked'], ['w', 'held'], ['p', 'parked'], ['q', 'done']])
  assert.deepEqual(result.unblocked, [{ id: 'p', reason: 'PLAN-DEFECT', route: 'amend-or-replan' }])
  assert.match(prompts['scribe:r0'], /\nunblocked: p \(PLAN-DEFECT -> amend-or-replan\)\n/)
  // Control: the same PLAN-DEFECT with no owner question waits on no person, so no list.
  const noOwner = { ...args, items: args.items.filter(it => it.id !== 'o').map(it => ({ ...it, after: [] })) }
  const r = await runTimed(noOwner, itemsReply({ 'item-implementer:p:': defect }))
  assert.equal(r.result.outcome, 'PARKED')
  assert.ok(!('unblocked' in r.result), 'a result that waits on no person carried unblocked')
  assert.ok(!/\nunblocked:/.test(r.prompts['scribe:r0']))
})

test('unblocked: every hold is traced to its root, and each route is named', () => {
  const items = [IT('o', ['o.css']), IT('w', ['w.css'], { after: ['o'] }), IT('y', ['y.css'], { after: ['w'] }),
    IT('p', ['p.css']), IT('h', ['h.css']), IT('a', ['a.css']), IT('b', ['b.css']), IT('z', ['z.css']), IT('k', ['k.css'])]
  const st = ST(items, {
    o: { status: 'parked', reason: 'owner: o?', ownerWait: true },
    w: { status: 'held', reason: 'after o, which is parked', heldBy: 'o' },
    y: { status: 'held', reason: 'after w, which is held', heldBy: 'w' },
    p: { status: 'parked', reason: 'PLAN-DEFECT' },
    h: { status: 'held', reason: "may be invalidated by p's PLAN-DEFECT", heldBy: 'p' },
    a: { status: 'parked', reason: 'ADVICE-NEEDED' },
    b: { status: 'parked', reason: 'budget: 3 attempts and its checks still fail' },
    z: { status: 'held', reason: 'could not be scheduled' },
    k: { status: 'done' },
  })
  assert.deepEqual(sched.unblockedItems(items, st).map(u => [u.id, u.route]),
    [['p', 'amend-or-replan'], ['h', 'amend-or-replan'], ['a', 'consult'], ['b', 'split'], ['z', 'relaunch']])
})

test('unblocked: a pass pending a human carries an empty list, in items mode and in rounds', async () => {
  const pending = { verdict: 'PASS-PENDING-HUMAN', criteria: [], pending_human: ['look at the panel'] }
  const items = await runTimed(ITEMS_BASE, itemsReply({ 'verifier:': pending }))
  assert.equal(items.result.outcome, 'PASS-PENDING-HUMAN')
  assert.deepEqual(items.result.unblocked, [])
  assert.match(items.prompts['scribe:r0'], /\nunblocked: none\n/)
  const prompts = {}
  const rounds = await run(BASE, (label, prompt) => { prompts[label] = prompt; return standard({ verifier: pending })(label) })
  assert.equal(rounds.result.outcome, 'PASS-PENDING-HUMAN')
  assert.deepEqual(rounds.result.unblocked, [])
  assert.match(prompts['scribe:r0'], /\nunblocked: none\n/)
  // Control: a plain PASS waits on no one.
  const pass = await run(BASE, standard())
  assert.ok(!('unblocked' in pass.result))
})

// --- goal 2: whole-tree runs go to the background, item checks do not -------
test('background: the rounds verifier, a reach re-verify and the items gate poll --status; item checks stay in the foreground', async () => {
  const background = p => {
    assert.match(p, /run_in_background: true/)
    assert.match(p, /py -3 tools\/run_criteria\.py --status "<your scratchpad>\/criteria" --wait 220/)
    assert.match(p, /Bash timeout of 300000, re-issued while it exits 3/)
    assert.match(p, /run_criteria\.py --digest "<your scratchpad>\/criteria"/)
  }
  const rounds = {}
  await run(BASE, (label, prompt) => { rounds[label] = prompt; return standard()(label) })
  background(rounds['verifier:r0'])
  const scopedPass = { verdict: 'PASS', criteria: [CRIT(1, 'pass'), CRIT(2, 'pass'), CRIT(3, 'pass')], pending_human: [] }
  const reach = await reachRun([FAILED_2, scopedPass])
  assert.ok(reach.prompts['verifier:r1'].includes('--changed-since HUB-SHA'), 'control: this is the reach re-verify')
  background(reach.prompts['verifier:r1'])
  const items = await runTimed(ITEMS_BASE, itemsReply())
  background(items.prompts['verifier:r0'])
  // Controls: the item check and the item implementer keep their foreground run.
  for (const label of ['item-verifier:a:a1:r0', 'item-implementer:a:a1:r0']) {
    const p = items.prompts[label]
    assert.ok(p.includes('--item a --jobs auto'), label)
    assert.ok(!p.includes('--status'), `${label} was sent to the background`)
    assert.ok(!p.includes('run_in_background'), `${label} was sent to the background`)
    assert.match(p, /Bash timeout (at )?600000/)
  }
})

// --- goal 5: a stated correction is amended inside the launch ---------------
//
// Measured 2026-09-27: the bug batch's one round-borne amendment waited 41
// minutes for a driver turn. Only `amend_check.py check`'s `AMENDMENT` may put
// the work back in the queue; every other outcome is the driver's replan.
const defectBlock = correction => `VERDICT: PLAN-DEFECT\nSTEP: 1\nEVIDENCE: \`grep -c x docs/c.md\` printed 0\n` +
  `WHAT THE PLAN ASSUMED: x\nWHAT IS ACTUALLY TRUE: y\nCORRECTION: ${correction}\nPROGRESS SO FAR: nothing edited`
const FIX_TEXT = 'criterion 3: grep `--item`, not `--items`'
const CORRECTED = (correction = FIX_TEXT) => ({ ...DONE, verdict: 'PLAN-DEFECT', evidence: defectBlock(correction), commits: [], paths: [] })
const AMEND_OK = {
  'amend-save:': { exit_code: 0, raw_output: 'saved p.md -> .rounds/zz/amend-base-plan.md' },
  'amendment: ': { verdict: 'PLAN-READY', report: 'criterion 3 now greps --item' },
  'amend-check:': { exit_code: 0, verdict_line: 'AMENDMENT', raw_output: 'p.md: ## acceptance criteria: +1 -1\nlines_changed: 2\nAMENDMENT' },
  'amend-restore:': { exit_code: 0, raw_output: 'restored .rounds/zz/amend-base-plan.md -> p.md' },
}
const tableOf = items => ({ exit_code: 0, items, complete: true, raw_output: '' })
const AMEND_AGENT = /^(amend-save|amendment: |amend-check|amend-items|amend-restore)/
const amendCalls = calls => calls.filter(c => AMEND_AGENT.test(c))
// runTimed, also keeping each agent's options.
async function runAmend(args, reply) {
  const opts = {}
  const r = await runTimed(args, (label, prompt, o) => { opts[label] = o; return reply(label, prompt, o) })
  return { ...r, opts }
}

test('amend: items mode -- a stated CORRECTION is saved, amended, checked, the table re-read, and the item re-run to done', async () => {
  // maxParallel 1, so b (after a) and d (same check command as a) are still
  // pending when a parks: both are held for the amendment, c is not.
  const args = { ...ITEMS_BASE, maxParallel: 1, items: [
    { id: 'a', title: 'toolbar', files: ['panel/a.css'], checks: ['`npm test` exits 0'] },
    { id: 'b', title: 'tray', files: ['panel/b.css'], after: ['a'], checks: ['`grep b x` ok'] },
    { id: 'c', title: 'docs', files: ['docs/c.md'], checks: ['`grep c x` ok'] },
    { id: 'd', title: 'badge', files: ['panel/d.css'], checks: ['`npm test` exits 0'] },
  ] }
  const amended = tableOf([{ ...args.items[0], files: ['panel/a2.css'] }, ...args.items.slice(1)])
  const { result, calls, prompts, opts } = await runAmend(args, itemsReply({ 'item-implementer:a:a1:': CORRECTED(), ...AMEND_OK, 'amend-items:': amended }))
  assert.equal(result.outcome, 'PASS')
  assert.deepEqual(result.items.map(i => [i.id, i.status]), [['a', 'done'], ['b', 'done'], ['c', 'done'], ['d', 'done']])
  const order = ['item-implementer:a:a1:r0', 'amend-save:a:r0', 'amendment: zz a:r0', 'amend-check:a:r0', 'amend-items:a:r0', 'item-implementer:a:a2:r0', 'item-implementer:b:a1:r0']
  for (const [x, y] of order.slice(1).map((l, i) => [order[i], l])) assert.ok(calls.indexOf(x) >= 0 && calls.indexOf(x) < calls.indexOf(y), `${x} before ${y}: ${calls.join(', ')}`)
  assert.ok(calls.indexOf('item-implementer:d:a1:r0') > calls.indexOf('amend-items:a:r0'), 'd ran before the amendment released it')
  // Work the PLAN-DEFECT does not reach waits too, since it would read the plan
  // mid-rewrite, and runs once the amendment is confirmed; nothing is restored.
  assert.ok(calls.indexOf('item-implementer:c:a1:r0') > calls.indexOf('amend-items:a:r0'), 'c started while the plan was being amended')
  assert.ok(!calls.some(c => c.startsWith('amend-restore:')), 'a confirmed amendment was restored')
  assert.match(prompts['amend-save:a:r0'], /Run exactly: py -3 tools\/amend_check\.py save "p\.md" "c\.md"/)
  assert.match(prompts['amend-check:a:r0'], /Run exactly: py -3 tools\/amend_check\.py check "p\.md" "c\.md"/)
  assert.equal(opts['amendment: zz a:r0'].agentType, 'planner')
  assert.equal(opts['amendment: zz a:r0'].model, 'opus', 'the amendment planner always runs on opus, never fable')
  assert.deepEqual(opts['amendment: zz a:r0'].schema.properties.verdict.enum, ['PLAN-READY', 'NOT AN AMENDMENT'])
  // The correction verbatim, and only its own field; the whole evidence block follows it.
  assert.equal(between(prompts['amendment: zz a:r0'], 'Apply this correction and nothing else:\n\n', '\n\nThe PLAN-DEFECT evidence'), FIX_TEXT)
  assert.ok(prompts['amendment: zz a:r0'].includes(defectBlock(FIX_TEXT)), 'the evidence was not passed verbatim')
  assert.match(prompts['amendment: zz a:r0'], /"When you are spawned as an amendment"/)
  // The re-run reads the amended table and knows why it runs again.
  assert.match(prompts['item-implementer:a:a2:r0'], /Your file set is `panel\/a2\.css`/)
  assert.match(prompts['item-implementer:a:a2:r0'], /plan was amended in this launch/)
  assert.ok(!/checks failed/.test(prompts['item-implementer:a:a2:r0']))
  assert.deepEqual(result.amendments, [{ id: 'a', amended: true, why: '', verdict: 'AMENDMENT' }])
  assert.match(prompts['scribe:r0'], /\namendments \(1\):\n- a: AMENDMENT; re-run\n/)
})

test('amend: items mode -- REPLAN, NOT AN AMENDMENT, SCOPE, a failed check or lint, and CORRECTION: none each park the item unrun', async () => {
  const cases = [
    ['REPLAN', { 'amend-check:': { exit_code: 1, verdict_line: 'REPLAN: p.md: ## goal changed', raw_output: 'lines_changed: 3\nREPLAN: p.md: ## goal changed' } }, /^REPLAN: p\.md: ## goal changed$/],
    ['NOT AN AMENDMENT', { 'amendment: ': { verdict: 'NOT AN AMENDMENT', reason: 'the stated fix is wrong' } }, /^NOT AN AMENDMENT: the stated fix is wrong$/],
    ['SCOPE', { 'amend-check:': { exit_code: 0, verdict_line: 'SCOPE: 1 new owner decision(s); not a replan (was: x)', raw_output: 'SCOPE: 1 new owner decision(s); not a replan (was: x)' } }, /^SCOPE: .*the driver's to route$/],
    ['exit 2', { 'amend-check:': { exit_code: 2, raw_output: 'amend_check: missing p.md (run `save` before the amendment)' } }, /^amend_check\.py check exited 2: amend_check: missing/],
    ['save failed', { 'amend-save:': { exit_code: 2, raw_output: 'amend_check: no such file: c.md' } }, /^amend_check\.py save exited 2/],
    ['lint', { 'amend-items:': { exit_code: 1, items: [], complete: false, raw_output: 'p.md: item a: overlap: x' } }, /^plan_lint refused the amended plan: p\.md: item a: overlap/],
  ]
  for (const [why, stubs, reason] of cases) {
    const { result, calls, prompts } = await runAmend(ITEMS_BASE, itemsReply({ 'item-implementer:a:a1:': CORRECTED(), ...AMEND_OK, 'amend-items:': tableOf(ITEMS_BASE.items), ...stubs }))
    const a = result.items.find(i => i.id === 'a')
    assert.equal(result.outcome, 'PARKED', why)
    assert.deepEqual([a.status, a.reason], ['parked', 'PLAN-DEFECT'], why)
    assert.match(a.replan, reason, why)
    assert.ok(!calls.includes('item-implementer:a:a2:r0'), `${why}: the item was re-run`)
    if (why !== 'save failed') {
      assert.ok(calls.includes('amend-check:a:r0'), `${why}: a spawned planner had no check after it (R24)`)
      // The rejected edit is put back before anything else can read it.
      const last = why === 'lint' ? 'amend-items:a:r0' : 'amend-check:a:r0'
      assert.ok(calls.indexOf('amend-restore:a:r0') > calls.indexOf(last), `${why}: no restore after ${last}: ${calls.join(', ')}`)
      assert.match(prompts['amend-restore:a:r0'], /Run exactly: py -3 tools\/amend_check\.py restore "p\.md" "c\.md"/)
    } else {
      assert.ok(!calls.includes('amendment: zz a:r0'), 'a planner ran without a saved copy')
      assert.ok(!calls.includes('amend-restore:a:r0'), 'control: nothing was saved, so nothing is restored')
    }
    assert.deepEqual(result.amendments.map(x => [x.id, x.amended]), [['a', false]], why)
    assert.match(prompts['scribe:r0'], /\n- a: not amended -- /, why)
    assert.match(prompts['scribe:r0'], /\n- a \(toolbar\): parked -- PLAN-DEFECT; replan: /, why)
  }
  // `CORRECTION: none` is the implementer's own "needs a replan": no amendment runs at all.
  const none = await runAmend(ITEMS_BASE, itemsReply({ 'item-implementer:a:a1:': CORRECTED('none'), ...AMEND_OK }))
  assert.deepEqual(amendCalls(none.calls), [])
  assert.equal(none.result.items[0].replan, 'its CORRECTION is none')
  assert.ok(!none.calls.includes('item-implementer:a:a2:r0'))
  // Control: no CORRECTION line at all leaves the route to the driver, as before.
  const bare = await runAmend(ITEMS_BASE, itemsReply({ 'item-implementer:a:a1:': { ...CORRECTED(), evidence: 'STEP 1: no such token' } }))
  assert.deepEqual(amendCalls(bare.calls), [])
  assert.equal(bare.result.items[0].replan, undefined)
  // The driver is told which of the two routes a parked PLAN-DEFECT needs.
  const items = [IT('p', ['p.css']), IT('r', ['r.css'])]
  const st = ST(items, { p: { status: 'parked', reason: 'PLAN-DEFECT' }, r: { status: 'parked', reason: 'PLAN-DEFECT', replan: 'REPLAN: x' } })
  assert.deepEqual(sched.unblockedItems(items, st).map(u => [u.id, u.route]), [['p', 'amend-or-replan'], ['r', 'replan']])
})

test('amend: items mode -- a second PLAN-DEFECT after its amendment parks; one after an IMPL-DONE is amended again', async () => {
  const again = await runAmend(ITEMS_BASE, itemsReply({ 'item-implementer:a:': CORRECTED(), ...AMEND_OK, 'amend-items:': tableOf(ITEMS_BASE.items) }))
  assert.equal(again.result.outcome, 'PARKED')
  assert.equal(again.calls.filter(c => c.startsWith('amendment: ')).length, 1, 'a second amendment ran back to back')
  assert.match(again.result.items[0].replan, /^PLAN-DEFECT again after its amendment in this launch, with no IMPL-DONE between$/)
  assert.ok(!again.calls.includes('item-implementer:a:a3:r0'))
  // Control: an IMPL-DONE between the two resets the limit, and neither
  // amendment is charged to the item's check budget (4 attempts, 2 charged).
  const failOnce = { verdict: 'IMPL-DEFECT', criteria: [{ criterion: 'npm test', status: 'fail', evidence: 'expected 2 got 3' }], pending_human: [] }
  const later = await runAmend(ITEMS_BASE, itemsReply({ 'item-implementer:a:a1:': CORRECTED(), 'item-implementer:a:a3:': CORRECTED(),
    'item-verifier:a:a2:': failOnce, ...AMEND_OK, 'amend-items:': tableOf(ITEMS_BASE.items) }))
  assert.equal(later.result.outcome, 'PASS')
  assert.equal(later.calls.filter(c => c.startsWith('amendment: ')).length, 2)
  assert.equal(later.result.items[0].attempts, 4)
  assert.match(later.prompts['item-implementer:a:a3:r0'], /checks failed.*\n- FAILED npm test: expected 2 got 3/s)
  assert.match(later.prompts['item-implementer:a:a4:r0'], /This is attempt 4\. The plan was amended in this launch/)
})

test('amend: items mode -- two items amended in one launch never overlap', async () => {
  const { result, calls, spans } = await runAmend(ITEMS_BASE, itemsReply({ 'item-implementer:a:a1:': CORRECTED(), 'item-implementer:c:a1:': CORRECTED(),
    ...AMEND_OK, 'amend-items:': tableOf(ITEMS_BASE.items) }))
  assert.equal(result.outcome, 'PASS')
  assert.deepEqual(result.amendments.map(x => x.id).sort(), ['a', 'c'])
  const span = id => [spans[`amend-save:${id}:r0`][0], spans[`amend-items:${id}:r0`][1]]
  const s = { a: span('a'), c: span('c') }
  assert.ok(!overlaps(s, 'a', 'c'), `two amendments ran at once: ${JSON.stringify(s)}`)
  // Control: the two implementers that raised them did run at the same time.
  assert.ok(overlaps(spans, 'item-implementer:a:a1:r0', 'item-implementer:c:a1:r0'))
  assert.ok(calls.includes('item-implementer:a:a2:r0') && calls.includes('item-implementer:c:a2:r0'))
})

test('amend: items mode -- no item starts while an amendment runs; unrelated work starts once it is confirmed, or rejected and restored', async () => {
  // maxParallel 1, so c (unrelated to a's PLAN-DEFECT) is still pending when a parks.
  const args = { ...ITEMS_BASE, maxParallel: 1, items: [
    { id: 'a', title: 'toolbar', files: ['panel/a.css'], checks: ['`grep a x` ok'] },
    { id: 'c', title: 'docs', files: ['docs/c.md'], checks: ['`grep c x` ok'] },
  ] }
  const startOf = (spans, label) => spans[label][0]
  const confirmed = await runAmend(args, itemsReply({ 'item-implementer:a:a1:': CORRECTED(), ...AMEND_OK, 'amend-items:': tableOf(args.items) }))
  assert.equal(confirmed.result.outcome, 'PASS')
  assert.ok(startOf(confirmed.spans, 'item-implementer:c:a1:r0') > confirmed.spans['amend-items:a:r0'][1],
    `c started while a's amendment ran: ${confirmed.calls.join(', ')}`)
  assert.ok(!confirmed.calls.includes('amend-restore:a:r0'), 'control: a confirmed amendment is not restored')
  const rejected = await runAmend(args, itemsReply({ 'item-implementer:a:a1:': CORRECTED(), ...AMEND_OK,
    'amend-check:': { exit_code: 1, verdict_line: 'REPLAN: p.md: ## goal changed', raw_output: 'REPLAN: p.md: ## goal changed' } }))
  assert.equal(rejected.result.outcome, 'PARKED')
  assert.deepEqual(rejected.result.items.map(i => [i.id, i.status]), [['a', 'parked'], ['c', 'done']])
  assert.ok(startOf(rejected.spans, 'item-implementer:c:a1:r0') > rejected.spans['amend-restore:a:r0'][1],
    `c started before the rejected amendment was restored: ${rejected.calls.join(', ')}`)
  assert.match(rejected.result.items[0].replan, /^REPLAN: p\.md: ## goal changed$/)
})

test('amend: items mode -- a restore that fails starts nothing more, and says why', async () => {
  const args = { ...ITEMS_BASE, maxParallel: 1, items: [
    { id: 'a', title: 'toolbar', files: ['panel/a.css'], checks: ['`grep a x` ok'] },
    { id: 'c', title: 'docs', files: ['docs/c.md'], checks: ['`grep c x` ok'] },
  ] }
  const { result, calls } = await runAmend(args, itemsReply({ 'item-implementer:a:a1:': CORRECTED(), ...AMEND_OK,
    'amend-check:': { exit_code: 1, verdict_line: 'REPLAN: p.md: ## goal changed', raw_output: '' },
    'amend-restore:': { exit_code: 2, raw_output: 'amend_check: no saved copy' } }))
  assert.equal(result.outcome, 'PARKED')
  assert.ok(!calls.includes('item-implementer:c:a1:r0'), 'c read a plan that may still carry the rejected edit')
  const [a, c] = result.items
  assert.match(a.replan, /^REPLAN: p\.md: ## goal changed; restoring the saved plan failed \(amend_check\.py restore exited 2: amend_check: no saved copy\)/)
  assert.equal(c.status, 'held')
  assert.match(c.reason, /^not started: REPLAN: .*restoring the saved plan failed/)
})

test('amend: items mode -- after a failed restore a queued amendment is not attempted, so its save cannot overwrite the good copy', async () => {
  // a and c run at once and both return a CORRECTION; whichever settles first
  // is amended, rejected, and its restore fails while the other waits queued.
  const args = { ...ITEMS_BASE, items: [
    { id: 'a', title: 'toolbar', files: ['panel/a.css'], checks: ['`grep a x` ok'] },
    { id: 'c', title: 'docs', files: ['docs/c.md'], checks: ['`grep c x` ok'] },
  ] }
  const stubs = { 'item-implementer:a:a1:': CORRECTED(), 'item-implementer:c:a1:': CORRECTED(), ...AMEND_OK,
    'amend-check:': { exit_code: 1, verdict_line: 'REPLAN: p.md: ## goal changed', raw_output: '' } }
  const { result, calls, prompts } = await runAmend(args, itemsReply({ ...stubs, 'amend-restore:': { exit_code: 2, raw_output: 'amend_check: no saved copy' } }))
  const saves = calls.filter(c => c.startsWith('amend-save:'))
  assert.equal(saves.length, 1, `a second save overwrote the only saved copy: ${calls.join(', ')}`)
  const first = saves[0].split(':')[1], second = first === 'a' ? 'c' : 'a'
  assert.equal(result.outcome, 'PARKED')
  const q = result.items.find(i => i.id === second)
  assert.deepEqual([q.status, q.reason], ['parked', 'PLAN-DEFECT'])
  assert.match(q.replan, /^its amendment was not attempted: REPLAN: p\.md: ## goal changed; restoring the saved plan failed/)
  assert.deepEqual(result.amendments.map(x => [x.id, x.amended]), [[first, false], [second, false]])
  assert.match(prompts['scribe:r0'], new RegExp(`\\n- ${second}: not amended -- its amendment was not attempted: `))
  assert.ok(!calls.some(c => /^item-implementer:[ac]:a2:/.test(c)), 'an item re-ran on a plan that may carry the rejected edit')
  // Control: with the restore succeeding, the second amendment does run.
  const ok = await runAmend(args, itemsReply(stubs))
  assert.equal(ok.calls.filter(c => c.startsWith('amend-save:')).length, 2, `control: ${ok.calls.join(', ')}`)
  assert.deepEqual(ok.result.amendments.map(x => x.amended), [false, false])
  assert.equal(ok.result.outcome, 'PARKED')
})

test('amend: rounds mode -- an amendment re-runs the same round, uncounted; a second PLAN-DEFECT returns PLAN-DEFECT', async () => {
  let impls = 0
  const prompts = {}
  const once = await run(BASE, (label, prompt) => { prompts[label] = prompt; return standard({ implementer: () => (impls++ === 0 ? CORRECTED() : DONE), ...AMEND_OK })(label) })
  assert.equal(once.result.outcome, 'PASS')
  assert.equal(once.result.round, 0)
  assert.deepEqual(once.calls.filter(c => c.startsWith('implementer')), ['implementer:r0', 'implementer:r0'])
  assert.deepEqual(amendCalls(once.calls), ['amend-save:implementer:r0', 'amendment: zz implementer:r0', 'amend-check:implementer:r0'])
  assert.deepEqual(once.calls.filter(c => c.startsWith('verifier')), ['verifier:r0'])
  assert.match(prompts['implementer:r0'], /plan was amended in this launch/, 'the re-run was not told why it runs again')
  assert.match(once.result.rounds[0].amendment, /^AMENDMENT; this round re-ran, not counted$/)
  assert.match(prompts['scribe:r0'], /\namendment: AMENDMENT; this round re-ran, not counted\n/)
  // The amendment spends no round: three failing verifies still make three rounds.
  const fail = { verdict: 'IMPL-DEFECT', criteria: [{ criterion: 'c', status: 'fail', evidence: 'e' }], pending_human: [] }
  impls = 0
  const capped = await run(BASE, standard({ implementer: () => (impls++ === 0 ? CORRECTED() : DONE), ...AMEND_OK, verifier: fail }))
  assert.equal(capped.result.outcome, 'CAP')
  assert.deepEqual(capped.calls.filter(c => c.startsWith('verifier')), ['verifier:r0', 'verifier:r1', 'verifier:r2'])
  // A second PLAN-DEFECT from the re-run is the driver's.
  const twice = await run(BASE, standard({ implementer: CORRECTED(), ...AMEND_OK }))
  assert.equal(twice.result.outcome, 'PLAN-DEFECT')
  assert.equal(twice.calls.filter(c => c.startsWith('amendment: ')).length, 1)
  assert.ok(!twice.calls.some(c => c.startsWith('verifier')))
  assert.match(twice.result.amendment.why, /again after its amendment/)
  // Control: an unconfirmed amendment returns PLAN-DEFECT without a re-run.
  const replan = await run(BASE, standard({ implementer: CORRECTED(), ...AMEND_OK, 'amend-check:': { exit_code: 1, verdict_line: 'REPLAN: 30 lines changed (limit 20)', raw_output: '' } }))
  assert.equal(replan.result.outcome, 'PLAN-DEFECT')
  assert.deepEqual(replan.calls.filter(c => c.startsWith('implementer')), ['implementer:r0'])
  assert.deepEqual(replan.result.amendment, { amended: false, why: 'REPLAN: 30 lines changed (limit 20)', verdict: 'REPLAN: 30 lines changed (limit 20)' })
  // The driver's replan starts from the plan as it was, not the rejected edit;
  // the confirmed amendment above was not restored (amendCalls lists restores).
  assert.deepEqual(amendCalls(replan.calls), ['amend-save:implementer:r0', 'amendment: zz implementer:r0', 'amend-check:implementer:r0', 'amend-restore:implementer:r0'])
})

test('amend: rounds mode -- a lane\'s PLAN-DEFECT is unchanged; the join\'s is amended and re-run as one implementer', async () => {
  const lane = { ...CORRECTED(), lane: 'code' }
  const r = await run(LANED, laneReply({ code: lane }, AMEND_OK))
  assert.equal(r.result.outcome, 'PLAN-DEFECT')
  assert.deepEqual(amendCalls(r.calls), [], 'a lane PLAN-DEFECT was amended in the launch')
  assert.ok(!r.calls.includes('implementer:join:r0'))
  const prompts = {}
  const joined = await run(LANED, (label, prompt, o) => { prompts[label] = prompt; return laneReply({}, { 'implementer:join': CORRECTED(), ...AMEND_OK })(label, prompt, o) })
  assert.equal(joined.result.outcome, 'PASS')
  assert.deepEqual(joined.calls.filter(c => c.startsWith('implementer')), ['implementer:code:r0', 'implementer:docs:r0', 'implementer:join:r0', 'implementer:r0'])
  assert.match(prompts['implementer:r0'], /you own every lane's file set and the join's steps/)
})

// --- 2k: every implementer starts from its brief -----------------------------
//
// Measured 2026-10-03 (workorder-calibration.md, "Plan slices, the amendment
// tier and symbol lookup"): implementers spent 5-20 Read/sed calls slicing the
// plan and the context file for themselves. The script cannot read a file, so
// each prompt names the one command that prints that implementer's slice
// (`tools/workorder_brief.py`) with its own selector, and keeps the plan and
// context paths as the fallback.
const BRIEF = 'py -3 tools/workorder_brief.py "p.md" --context "c.md"'
const briefOf = p => { const m = /`py -3 tools\/workorder_brief\.py [^`]*`/.exec(p || ''); return m ? m[0].slice(1, -1) : null }
const hasPlanPaths = p => /Workorder: p\.md \(context file: c\.md\)\./.test(p)

test('brief: rounds mode names --round, --since-round past round 0, and --amended only on the amended re-run', async () => {
  const prompts = {}
  await run(BASE, recording(prompts, standard()))
  assert.equal(briefOf(prompts['implementer:r0']), `${BRIEF} --round 0`)
  assert.ok(hasPlanPaths(prompts['implementer:r0']), 'the plan and context paths stay as the fallback')
  // The brief is the first thing the implementer runs: only the workorder line comes before it.
  assert.match(prompts['implementer:r0'], /^Workorder: p\.md \(context file: c\.md\)\. This is round 0\. Run `py -3 tools\/workorder_brief\.py/)
  await run({ ...BASE, round: 1, reviewers: { 'docs-sync-reviewer': 'blocking' } }, recording(prompts, standard()))
  assert.equal(briefOf(prompts['implementer:r1']), `${BRIEF} --round 1 --since-round 0`)
  assert.ok(hasPlanPaths(prompts['implementer:r1']))
  // The brief carries the round's Log entries and the criteria now; the prompt stops sending the implementer for them.
  assert.ok(!prompts['implementer:r1'].includes(`section.py "p.md" 'Acceptance criteria'`), prompts['implementer:r1'])
  assert.doesNotMatch(prompts['implementer:r1'], /re-entered after a defect: read '## Log'/)
  // Amended re-run: the first attempt has no --amended, the re-run does.
  const seen = []
  let impls = 0
  await run(BASE, (label, prompt) => {
    if (label === 'implementer:r0') seen.push(prompt)
    return standard({ implementer: () => (impls++ === 0 ? CORRECTED() : DONE), ...AMEND_OK })(label)
  })
  assert.equal(seen.length, 2)
  assert.equal(briefOf(seen[0]), `${BRIEF} --round 0`)
  assert.equal(briefOf(seen[1]), `${BRIEF} --round 0 --amended`)
})

test('brief: a single-file plan gets no --context, and the brief keeps the plan path double-quoted', async () => {
  const prompts = {}
  await run({ ...BASE, contextPath: 'p.md' }, recording(prompts, standard()))
  assert.equal(briefOf(prompts['implementer:r0']), 'py -3 tools/workorder_brief.py "p.md" --round 0')
  assert.match(prompts['implementer:r0'], /^Workorder: p\.md\. This is round 0\./)
})

test('brief: each lane gets --lane with its own name, the join gets --join', async () => {
  const prompts = {}
  await run(LANED, (label, prompt, o) => { prompts[label] = prompt; return laneReply()(label, prompt, o) })
  assert.equal(briefOf(prompts['implementer:code:r0']), `${BRIEF} --lane code`)
  assert.equal(briefOf(prompts['implementer:docs:r0']), `${BRIEF} --lane docs`)
  assert.ok(!prompts['implementer:code:r0'].includes('--lane docs'), 'control: a lane is not handed another lane\'s brief')
  assert.equal(briefOf(prompts['implementer:join:r0']), `${BRIEF} --join`)
  for (const l of ['implementer:code:r0', 'implementer:docs:r0', 'implementer:join:r0']) assert.ok(hasPlanPaths(prompts[l]), l)
  // A lane's brief carries no Log, so a laned relaunch past round 0 still sends it to the Log; the join's carries the criteria.
  await run({ ...LANED, round: 1, reviewers: { 'docs-sync-reviewer': 'blocking' } }, (label, prompt, o) => { prompts[label] = prompt; return laneReply()(label, prompt, o) })
  assert.match(prompts['implementer:code:r1'], /re-entered after a defect: read '## Log' > '### Round 0'/)
  assert.ok(prompts['implementer:code:r1'].includes(`section.py "p.md" 'Acceptance criteria'`))
  assert.match(prompts['implementer:join:r1'], /re-entered after a defect: read '## Log' > '### Round 0'/)
  assert.ok(!prompts['implementer:join:r1'].includes(`section.py "p.md" 'Acceptance criteria'`), 'the join\'s brief prints every criterion')
})

test('brief: a patch round gets --paths from the findings\' where; with no path there is no brief line', async () => {
  const prompts = {}
  await run(PATCH_BASE, recording(prompts, standard({ delta: SMALL(), 'docs-sync-reviewer': blockingOnce(FIXED) })))
  assert.equal(briefOf(prompts['patch-implementer:r1']), `${BRIEF} --paths "docs/x.md"`)
  assert.ok(hasPlanPaths(prompts['patch-implementer:r1']))
  const three = [FIXED, { ...FIXED, where: 'tools/a.py:9' }, { ...FIXED, where: 'docs/x.md:7' }]
  let seen = 0
  await run(PATCH_BASE, recording(prompts, standard({ delta: SMALL(), 'docs-sync-reviewer': () => (seen++ === 0 ? { ...CLEAN, blocking: three } : CLEAN) })))
  assert.equal(briefOf(prompts['patch-implementer:r1']), `${BRIEF} --paths "docs/x.md,tools/a.py"`, 'each path once, in finding order')
  // Control: a where that names no file (no `/` and no `.`) gives no brief line at all.
  await run(PATCH_BASE, recording(prompts, standard({ delta: SMALL(), 'docs-sync-reviewer': blockingOnce({ ...FIXED, where: 'general' }) })))
  assert.ok(prompts['patch-implementer:r1'], 'control: the patch round ran')
  assert.equal(briefOf(prompts['patch-implementer:r1']), null)
  assert.ok(hasPlanPaths(prompts['patch-implementer:r1']))
})

test('brief: an item gets --item, --base from the launch heads after its first attempt, and --amended on the amended retry', async () => {
  let checks = 0
  const failing = () => (checks++ === 0 ? { verdict: 'IMPL-DEFECT', criteria: [{ criterion: 'npm test', status: 'fail', evidence: 'expected 2 got 3' }], pending_human: [] } : PASS)
  const { prompts } = await runTimed(ITEMS_BASE, itemsReply({ 'item-verifier:a:': failing }))
  assert.equal(briefOf(prompts['item-implementer:a:a1:r0']), `${BRIEF} --item a`)
  assert.equal(briefOf(prompts['item-implementer:b:a1:r0']), `${BRIEF} --item b`)
  assert.equal(briefOf(prompts['item-implementer:a:a2:r0']), `${BRIEF} --item a --base .=base000`)
  assert.ok(hasPlanPaths(prompts['item-implementer:a:a1:r0']))
  // Control: the item-check verifier runs no brief.
  assert.equal(briefOf(prompts['item-verifier:a:a1:r0']), null)
  const am = await runAmend(ITEMS_BASE, itemsReply({ 'item-implementer:a:a1:': CORRECTED(), ...AMEND_OK, 'amend-items:': tableOf(ITEMS_BASE.items) }))
  assert.equal(briefOf(am.prompts['item-implementer:a:a2:r0']), `${BRIEF} --item a --amended --base .=base000`)
})

test('brief: a review fixer gets --paths, a gate-fix gets --criteria from its numbered failures, and an unnumbered one none', async () => {
  let passes = 0
  const docs = () => (passes++ === 0
    ? { ...CLEAN, blocking: [{ where: 'panel/a.css:12', problem: 'wrong token', evidence: 'x', fix: 'use --accent' }], reviewed_heads: [{ repo: '.', sha: 'h1' }] }
    : { ...CLEAN, reviewed_heads: [{ repo: '.', sha: 'h2' }] })
  const fixed = await runTimed(ITEMS_BASE, itemsReply({ 'docs-sync-reviewer': docs }))
  assert.equal(briefOf(fixed.prompts['fix-implementer:fix-1:r0']), `${BRIEF} --paths "panel/a.css"`)
  assert.ok(hasPlanPaths(fixed.prompts['fix-implementer:fix-1:r0']))
  let gates = 0
  const numbered = () => (gates++ === 0 ? { verdict: 'IMPL-DEFECT', criteria: [CRIT(2, 'fail'), CRIT(3, 'pass'), CRIT(5, 'fail')], pending_human: [] } : PASS)
  const g = await runTimed(ITEMS_BASE, itemsReply({ 'verifier:': numbered }))
  assert.equal(briefOf(g.prompts['fix-implementer:gate-fix-1:r0']), `${BRIEF} --criteria 2,5`)
  // Control: a failure with no number (here a structural finding) gives a gate-fix no brief line.
  gates = 0
  const unnumbered = () => (gates++ === 0 ? { verdict: 'IMPL-DEFECT', criteria: [], other_defects: ['a stray file'], pending_human: [] } : PASS)
  const u = await runTimed(ITEMS_BASE, itemsReply({ 'verifier:': unnumbered }))
  assert.ok(u.prompts['fix-implementer:gate-fix-1:r0'], 'control: the gate-fix ran')
  assert.equal(briefOf(u.prompts['fix-implementer:gate-fix-1:r0']), null)
  assert.ok(hasPlanPaths(u.prompts['fix-implementer:gate-fix-1:r0']))
})

test('digest: every whole-tree verifier judges from run_criteria.py --digest and never reads report.txt whole; item checks do not', async () => {
  const digest = p => {
    assert.ok(p.includes('py -3 tools/run_criteria.py --digest "<your scratchpad>/criteria"'), p)
    assert.match(p, /never read `?report\.txt`? whole/i)
    assert.match(p, /cmd-<n>\.log/)
  }
  const rounds = {}
  await run(BASE, recording(rounds, standard()))
  digest(rounds['verifier:r0'])
  await run({ ...BASE, fullVerify: true }, recording(rounds, standard()))
  digest(rounds['verifier:r0'])
  const scopedPass = { verdict: 'PASS', criteria: [CRIT(1, 'pass'), CRIT(2, 'pass'), CRIT(3, 'pass')], pending_human: [] }
  const reach = await reachRun([FAILED_2, scopedPass])
  digest(reach.prompts['verifier:r1'])
  const items = await runTimed(ITEMS_BASE, itemsReply())
  digest(items.prompts['verifier:r0'])
  // Control: the item check reads its own foreground output, and its --out naming is unchanged.
  assert.ok(!items.prompts['item-verifier:a:a1:r0'].includes('--digest'))
  assert.ok(items.prompts['item-verifier:a:a1:r0'].includes('--out "<your scratchpad>/item-a-a1"'))
})
