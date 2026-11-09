// Module findings in rail and HUD, the modules-stress fixture, the schematic routes of the fixture backend and
// calculator choices / one_of from GET /calc.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createFixtureBackend, FIXTURE_BLOCKS } from '../desktop-src/lib/fixtures.js'
import { stageStatus, stageModCounts } from '../desktop-src/lib/stages.js'
import { shellKpis } from '../desktop-src/lib/art-shell.js'
import { calcApplyMeta, calcRawMeta, buildCalcBody, calcNeedText, calcGroups, calcDef } from '../desktop-src/lib/calc.js'
import { calcMetaOf, modCountWords, modCheckExtras, modRails, modFindings } from '../desktop-src/lib/modules.js'
import { wireBlockNames, wireBlockList, wireGroups } from '../desktop-src/lib/wire.js'
import { parseQuantity } from '../desktop-src/lib/units.js'

const DIR = join(dirname(fileURLToPath(import.meta.url)), '..', 'desktop-src', 'fixtures')
const FX = Object.fromEntries(readdirSync(DIR).filter(f => f.endsWith('.json')).map(f => [f.slice(0, -5), JSON.parse(readFileSync(join(DIR, f), 'utf8'))]))
const PROJECT = { id: 'p', assignments: [], calcs: [], circuits: [] }
const C = (ok, caution = 0, blocked = 0) => ({ ok, caution, blocked, unchecked: 0 })
const modEnv = counts => ({ ok: true, result: { modules: { counts } } })

test('module findings make PLAN warn or fail, never [✓]', () => {
  const none = { dangerCode: null, cautionCode: null }
  assert.deepEqual(stageModCounts(modEnv({ danger: 1, caution: 2, info: 3 })), { danger: 1, caution: 2, ...none })
  assert.deepEqual(stageModCounts({ ok: false }), { danger: 0, caution: 0, ...none })
  assert.deepEqual(stageModCounts(null), { danger: 0, caution: 0, ...none })
  assert.equal(stageStatus(PROJECT, C(2)).plan.text, '[✓]')
  const caution = stageStatus(PROJECT, C(2), null, { danger: 0, caution: 1 }).plan
  assert.deepEqual([caution.text, caution.tone, caution.detail], ['1!', 'warn', '1 module caution'])
  const danger = stageStatus(PROJECT, C(2, 1, 1), null, { danger: 2, caution: 1 }).plan
  assert.deepEqual([danger.text, danger.tone, danger.detail], ['3✕', 'bad', '2 module danger · 1 module caution'])
})

test('HUD pins figure names module findings ("PINS 2 ok · 1 module caution")', () => {
  const k = shellKpis(C(2), null, null, { danger: 0, caution: 1 }).pins
  const shown = k.items.filter(i => !i.quiet).map(i => `${i.n} ${i.word}`)
  assert.deepEqual(shown, ['2 ok', '1 module caution'])
  assert.match(k.label, /1 module caution/)
  assert.equal(shellKpis(C(2)).pins.items.length, 3, 'no module items without modules')
  const d = shellKpis(C(0), null, null, { danger: 1, caution: 0 }).pins.items.find(i => i.key === 'mod-danger')
  assert.deepEqual([d.symbol, d.tone, d.word], ['⊗', 'bad', 'module danger'])
  const both = shellKpis(C(1), null, null, { danger: 1, caution: 3 }).pins
  assert.deepEqual(both.items.filter(i => !i.quiet).map(i => `${i.n} ${i.word}`.trim()), ['1 module danger', '3'], 'HUD room: ok hidden, worst word only')
  const pinsOnly = shellKpis(C(2, 1, 1), null, null, { danger: 0, caution: 0 }).pins.items.map(i => i.word)
  assert.deepEqual(pinsOnly, ['ok', 'caution', 'blocked'], 'no module findings: every word stays')
  assert.equal(both.label, 'Pins: 1 ok, 0 caution, 0 blocked, 1 module danger, 3 module caution')
})

test('one module finding of a level names itself in HUD and rail ("1 address conflict")', () => {
  const env = { ok: true, result: { modules: { counts: { danger: 0, caution: 1 } } }, warnings: [{ code: 'mod_address_conflict', severity: 'caution' }, { code: 'pin_x', severity: 'caution' }] }
  const m = modCountWords(stageModCounts(env))
  assert.deepEqual([m.cautionCode, m.cautionWord, m.dangerWord], ['mod_address_conflict', 'address conflict', null])
  assert.equal(stageStatus(PROJECT, C(2), null, m).plan.detail, '1 address conflict')
  const shown = shellKpis(C(2), null, null, m).pins.items.filter(i => !i.quiet).map(i => `${i.n} ${i.word}`)
  assert.deepEqual(shown, ['2 ok', '1 address conflict'])
  const two = { ...env, result: { modules: { counts: { caution: 2 } } }, warnings: [...env.warnings, { code: 'mod_level_5v', severity: 'caution' }] }
  assert.equal(modCountWords(stageModCounts(two)).cautionWord, null, 'two findings keep the generic word')
  assert.equal(modCountWords({ dangerCode: 'mod_env_bme680_sdo_float' }).dangerWord, null, 'long words keep the generic one (HUD room)')
  const crowded = shellKpis(C(1), null, null, { danger: 1, caution: 3, dangerWord: 'shared bus net' }).pins
  assert.deepEqual(crowded.items.filter(i => !i.quiet).map(i => `${i.n} ${i.word}`.trim()), ['1 module danger', '3'], 'crowded HUD: generic word')
})

test('the modules-stress fixture covers danger, hidden findings, a rail limit and a mux segment', async () => {
  const env = FX['pins.check.modules-stress']
  const m = env.result.modules
  assert.ok(m.counts.danger >= 1 && m.counts.findings >= 13 && m.counts.hidden.length > 0)
  assert.ok(env.warnings.some(w => w.code === 'mod_net_shared_signals' && w.severity === 'danger'))
  const rail = modRails(env).find(r => r.net === '3V3')
  assert.ok(rail.frac > 0 && rail.limitSource === 'user', 'filled rail meter')
  assert.ok(m.buses.some(b => b.segments.some(s => s.id.includes('.'))), 'mux segment')
  assert.equal(modFindings(env).warnings[0].severity, 'danger')
  // the fixture backend answers the stress project's own check (desktop body: assignments + parts, no project id)
  const b = createFixtureBackend(FX, { delayMs: 0 })
  const project = (await b.handle('GET', '/projects/modules-stress')).result.project
  const bd = project.board
  const body = { chip: bd.chip, variant: bd.variant, wifi: bd.wifi, devkit: bd.devkit,
    assignments: project.assignments.map(a => ({ role: a.role, mode: a.mode, pin: a.pin, net: a.net })), ...modCheckExtras(project) }
  assert.equal((await b.handle('POST', '/pins/check', body)).result.modules.counts.danger, m.counts.danger)
  assert.equal((await b.handle('POST', '/pins/check', { project: 'modules-stress' })).result.modules.counts.findings, m.counts.findings)
  assert.equal((await b.handle('POST', '/pins/check', { project: 'modules-demo' })).result.modules.counts.danger, 0)
  assert.ok((await b.handle('GET', '/projects')).result.projects.some(p => p.id === 'modules-stress'))
})

test('POST /schematic without a block names every block; led and module have own answers', async () => {
  const b = createFixtureBackend(FX, { delayMs: 0 })
  const none = await b.handle('POST', '/schematic', {})
  assert.equal(none.error.code, 'invalid_args')
  assert.deepEqual(wireBlockNames(none), FIXTURE_BLOCKS)
  assert.ok(FIXTURE_BLOCKS.includes('module') && FIXTURE_BLOCKS.includes('level_shifter'))
  assert.deepEqual(wireGroups(wireBlockList(wireBlockNames(none))).map(g => g.id), ['basic', 'modules'])
  assert.equal((await b.handle('POST', '/schematic', { block: 'led', params: {} })).result.block, 'led')
  assert.equal((await b.handle('POST', '/schematic', { block: 'npn_low_side' })).result.block, 'npn_low_side')
  assert.equal((await b.handle('POST', '/schematic', { block: 'module', params: { part: 'U1' } })).result.block, 'module')
  assert.equal((await b.handle('POST', '/schematic', { block: 'module', params: { part: 'U2' } })).error.code, 'fixture_missing')
  assert.equal((await b.handle('POST', '/schematic', { block: 'divider' })).error.code, 'fixture_missing', 'no npn fallback')
})

test('GET /calc choices become selects, one_of a required combination', () => {
  const meta = FX['calc.meta']
  const groups = calcGroups(calcMetaOf(meta), meta.result.groups)
  const def = kind => calcApplyMeta(groups.flatMap(g => g.defs).find(d => d.type === kind), calcRawMeta(meta, kind))
  const acs = def('current_sense').fields.find(f => f.name === 'variant')
  assert.deepEqual(acs.choice, ['', '05b', '20a', '30a'])
  assert.equal(acs.def, '')
  const ldo = calcApplyMeta(calcDef('ldo'), calcRawMeta(meta, 'ldo')).fields.find(f => f.name === 'part')
  assert.ok(ldo.choice[0] === '' && ldo.choice.includes('AMS1117-3.3') && ldo.def === 'AMS1117-3.3')
  assert.deepEqual(def('ina_shunt').fields.find(f => f.name === 'pga').choice, ['', 'auto', '1', '2', '4', '8'])
  assert.ok(def('current_limit').fields.find(f => f.name === 'driver').choice.includes('a4988'))
  const buck = def('buck')
  assert.deepEqual(buck.oneOf, [['v_out'], ['r_top', 'r_bottom']])
  assert.equal(calcNeedText(buck), 'needs V out, or R top + R bottom')
  const form = Object.fromEntries(buck.fields.map(f => [f.name, f.def]))
  const empty = buildCalcBody(buck, form, parseQuantity)
  assert.equal(empty.ok, false)
  assert.equal(empty.errors._need, 'needs V out, or R top + R bottom')
  assert.equal(empty.errors.r_top, 'one set required')
  assert.equal(buildCalcBody(buck, { ...form, v_out: '3V3' }, parseQuantity).ok, true)
  assert.equal(buildCalcBody(buck, { ...form, r_top: '10k', r_bottom: '1k' }, parseQuantity).ok, true)
  assert.equal(buildCalcBody(buck, { ...form, r_top: '10k' }, parseQuantity).ok, false)
  assert.equal(buildCalcBody(def('current_sense'), { variant: 'x' }, parseQuantity).errors.variant, 'one of 05b, 20a, 30a')
  assert.equal(calcApplyMeta(calcDef('led'), null), calcDef('led'), 'no meta: unchanged')
})
