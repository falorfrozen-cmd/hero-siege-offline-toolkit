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

const DELTA = (paths, extra = {}) => ({ exit_code: 0, paths, instrumentContent: false, sdkContent: false, raw_output: '', ...extra })
const CLEAN = { blocking: [], non_blocking: [], plan_defect: false, summary: 'no blocking findings' }
const DONE = { verdict: 'IMPL-DONE', report: '', evidence: '', progress_so_far: '' }
const PASS = { verdict: 'PASS', criteria: [], pending_human: [] }
const BASE = {
  slug: 'zz', planPath: 'p.md', contextPath: 'c.md', goalExcerpt: 'g', implementerModel: 'sonnet', round: 0,
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
  if (label.startsWith('snapshot')) return DELTA([])
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

test('when the scribe cannot write, the evidence travels in the next dispatch', async () => {
  let verifies = 0
  const prompts = []
  const reply = (label, prompt) => {
    if (label.startsWith('implementer')) prompts.push(prompt)
    return standard({
      scribe: { written: false, note: 'edit failed' },
      verifier: () => (verifies++ === 0 ? { verdict: 'IMPL-DEFECT', criteria: [{ criterion: 'c', status: 'fail', evidence: 'REAL-OUTPUT-42' }], pending_human: [] } : PASS),
    })(label)
  }
  await run(BASE, reply)
  assert.match(prompts[1], /REAL-OUTPUT-42/)
})

test('missing arguments are refused', async () => {
  const { result } = await run({ slug: 'zz' }, standard())
  assert.equal(result.outcome, 'BAD-ARGS')
})
