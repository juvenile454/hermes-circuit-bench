// Directive `::bench{project="…" view="…"}`. Pure.
// Attributes are strings only (only quoted values survive, keys are lower-cased). Anything else, an unknown
// view or a bad id renders nothing. The card reads the project itself; numbers/bools never come from attributes.

export const DIRECTIVE_ID_RE = /^[a-z0-9-]{1,48}$/
export const DIRECTIVE_VIEWS = ['pins', 'calc', 'wire', 'solder', 'flash', 'crash']
const DIRECTIVE_STATION = { pins: 'plan', calc: 'calc', wire: 'wire', solder: 'solder', flash: 'flash', crash: 'debug' }
const DIRECTIVE_TITLE = { pins: 'PIN MAP', calc: 'CALCULATIONS', wire: 'WIRING', solder: 'SOLDER ORDER', flash: 'BUILD & FLASH', crash: 'PANIC' }

/** → {project, view, station, title} or null. `view` defaults to "pins" only when absent. */
export function parseDirectiveAttrs(attrs) {
  if (!attrs || typeof attrs !== 'object' || Array.isArray(attrs)) return null
  const project = attrs.project
  if (typeof project !== 'string' || !DIRECTIVE_ID_RE.test(project)) return null
  const view = attrs.view === undefined ? 'pins' : attrs.view
  if (typeof view !== 'string' || !DIRECTIVE_VIEWS.includes(view)) return null
  return { project, view, station: DIRECTIVE_STATION[view], title: DIRECTIVE_TITLE[view] }
}

/** Session id from the render props (B has it, v0.22.5 not): `sessionId ?? null`, only a plain short string. */
export function directiveSession(props) {
  const sid = props?.sessionId ?? null
  return typeof sid === 'string' && sid.length <= 128 && /^[A-Za-z0-9_.:-]+$/.test(sid) ? sid : null
}

function dClock(iso) {
  const d = new Date(iso)
  return !iso || Number.isNaN(d.getTime()) ? '—' : [d.getHours(), d.getMinutes(), d.getSeconds()].map(n => String(n).padStart(2, '0')).join(':')
}

/**
 * Compact facts of a project for one view → {headline: {text, tone}, rows: [{k, label, value, tone}]}.
 * `panicCurrent(project)` is injected (lib/crash.js projectPanicCurrent).
 */
export function directiveSummary(view, project, { panicCurrent = () => true } = {}) {
  if (!project) return { headline: { text: 'no project', tone: 'dim' }, rows: [] }
  const rows = []
  if (view === 'pins') {
    const as = project.assignments || []
    const c = { ok: 0, caution: 0, blocked: 0 }
    for (const a of as) if (c[a.verdict] !== undefined) c[a.verdict]++
    for (const a of as.slice(0, 6)) rows.push({ k: a.role, label: a.role, value: `IO${a.pin}`, tone: a.verdict === 'blocked' ? 'bad' : a.verdict === 'caution' ? 'warn' : 'active' })
    const tone = c.blocked ? 'bad' : c.caution ? 'warn' : as.length ? 'ok' : 'dim'
    return { headline: { text: `${c.ok}✓ ${c.caution}! ${c.blocked}✕`, tone }, rows }
  }
  if (view === 'calc') {
    for (const calc of (project.calcs || []).slice(0, 5)) {
      const r = calc.result || {}
      const main = r.r_chosen || r.i_b || r.v_out_max || r.suggested
      rows.push({ k: calc.id, label: `${calc.type} · ${calc.id}`, value: main?.display || '—', tone: 'fg' })
    }
    return { headline: { text: `${(project.calcs || []).length} calculations`, tone: rows.length ? 'ok' : 'dim' }, rows }
  }
  if (view === 'wire') {
    for (const ci of (project.circuits || []).slice(0, 5)) rows.push({ k: ci.id, label: ci.id, value: ci.block, tone: 'fg' })
    const nc = (project.circuits || []).length
    const np = (project.parts || []).length
    return { headline: { text: `${nc} circuit${nc === 1 ? '' : 's'} · ${np} part${np === 1 ? '' : 's'} in the project`, tone: rows.length ? 'ok' : 'dim' }, rows }
  }
  if (view === 'solder') {
    const steps = project.solder?.steps || []
    const done = new Set(project.solder?.done || [])
    const n = steps.filter(s => done.has(s.id)).length
    for (const s of steps.slice(0, 6)) rows.push({ k: s.id, label: `${done.has(s.id) ? '[✓]' : '[ ]'} ${s.n}`, value: s.kind, tone: done.has(s.id) ? 'ok' : 'dim' })
    return { headline: { text: steps.length ? `${n}/${steps.length} done` : 'no plan yet', tone: steps.length && n === steps.length ? 'ok' : steps.length ? 'active' : 'dim' }, rows }
  }
  if (view === 'flash') {
    const fw = project.firmware || {}
    const det = project.board?.detected
    if (det) rows.push({ k: 'det', label: 'board', value: `${det.port}${det.simulated ? ' (sim)' : ''}`, tone: det.simulated ? 'active' : 'ok' })
    if (fw.last_build) rows.push({ k: 'b', label: `build ${dClock(fw.last_build.at)}`, value: fw.last_build.ok ? `ok · ram ${fw.last_build.ram_pct ?? '—'} %` : 'FAILED', tone: fw.last_build.ok ? 'ok' : 'bad' })
    if (fw.last_flash) rows.push({ k: 'f', label: `flash ${dClock(fw.last_flash.at)}`, value: fw.last_flash.ok ? 'ok' : 'FAILED', tone: fw.last_flash.ok ? 'ok' : 'bad' })
    return { headline: { text: fw.last_flash?.ok ? 'flashed' : fw.last_build?.ok ? 'built' : 'not built', tone: fw.last_flash?.ok ? 'ok' : fw.last_build?.ok ? 'active' : 'dim' }, rows }
  }
  if (view === 'crash') {
    const p = project.debug?.last_panic
    if (!p) return { headline: { text: 'no panic recorded', tone: 'ok' }, rows }
    const live = panicCurrent(project)
    rows.push({ k: 'r', label: 'reason', value: `${p.reason || p.kind}${p.core !== undefined ? ` · core ${p.core}` : ''}`, tone: live ? 'bad' : 'dim' })
    if (p.top_frame) rows.push({ k: 't', label: '#0', value: p.top_frame, tone: live ? 'bad' : 'dim' })
    rows.push({ k: 'a', label: 'at', value: dClock(p.at), tone: 'dim' })
    if (!live && project.firmware?.last_flash?.ok) rows.push({ k: 'f', label: 'flashed after it', value: dClock(project.firmware.last_flash.at), tone: 'ok' })
    return { headline: { text: live ? 'PANIC CAUGHT' : 'NO CURRENT PANIC', tone: live ? 'bad' : 'ok' }, rows }
  }
  return { headline: { text: '', tone: 'dim' }, rows }
}
