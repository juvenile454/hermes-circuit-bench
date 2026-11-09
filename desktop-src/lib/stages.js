// Stations 01–06, rail status and HUD key figures. Pure, no SDK.

export const STATIONS = [
  { id: 'plan', n: '01', title: 'Plan', heading: 'PIN MAP', icon: 'circuit-board' },
  { id: 'calc', n: '02', title: 'Calc', heading: 'CALCULATORS', icon: 'symbol-numeric' },
  { id: 'wire', n: '03', title: 'Wire', heading: 'WIRING', icon: 'git-merge' },
  { id: 'solder', n: '04', title: 'Solder', heading: 'SOLDER ORDER', icon: 'flame' },
  { id: 'flash', n: '05', title: 'Flash', heading: 'BUILD & FLASH', icon: 'zap' },
  { id: 'debug', n: '06', title: 'Debug', heading: 'SERIAL & PANIC', icon: 'debug-alt' }
]

export const STATION_IDS = STATIONS.map(s => s.id)
export const VIEW_TO_STATION = { pins: 'plan', calc: 'calc', wire: 'wire', solder: 'solder', flash: 'flash', crash: 'debug' }

export function stationInfo(id) {
  return STATIONS.find(s => s.id === id) || STATIONS[0]
}

export function isStation(id) {
  return STATION_IDS.includes(id)
}

/** Solder progress {done, total} (done counts only ids that are still steps). */
export function solderProgress(project) {
  const steps = project?.solder?.steps || []
  const ids = new Set(steps.map(s => s.id))
  const done = (project?.solder?.done || []).filter(id => ids.has(id)).length
  return { done, total: steps.length }
}

/** Solder plan outdated? parts refs vs step refs → {stale, missing, gone, reopen: done steps a re-plan
 *  unticks (the backend keeps a tick only for an unchanged step id kind + refs, e.g. R5 joins the resistors)}. */
export function solderStale(project) {
  const steps = project?.solder?.steps || []
  const none = { stale: false, missing: [], gone: [], reopen: [] }
  if (!steps.length) return none
  const parts = (project?.parts || []).filter(p => p && p.ref)
  const inPlan = new Set(steps.flatMap(s => s.refs || []))
  const have = new Set(parts.map(p => p.ref))
  const missingParts = parts.filter(p => !inPlan.has(p.ref))
  const gone = [...inPlan].filter(r => !have.has(r))
  if (!missingParts.length && !gone.length) return none
  const done = new Set(project?.solder?.done || [])
  const reopen = steps.filter(s => done.has(s.id) && (missingParts.some(p => p.kind === s.kind) || (s.refs || []).some(r => !have.has(r))))
  return { stale: true, missing: missingParts.map(p => p.ref), gone,
    reopen: reopen.map(s => ({ n: s.n, kind: s.kind, id: s.id, gains: missingParts.filter(p => p.kind === s.kind).map(p => p.ref) })) }
}

/** 05 FLASH, real board only: a hint (never a block) when the solder plan is unfinished or outdated. → text | null */
export function flashSolderHint(project, port) {
  if (!port || /^sim:\/\//.test(String(port))) return null
  const sp = solderProgress(project)
  if (!sp.total) return null
  const st = solderStale(project)
  if (st.stale) return `solder plan outdated (${st.missing.length ? `${st.missing.join(', ')} not in it` : `${st.gone.join(', ')} removed`}) — board not finished?`
  return sp.done < sp.total ? `solder ${sp.done}/${sp.total} — board not finished?` : null
}

/** Panic key: changes when a new panic is stored, so the rail blinks again. */
export function panicKey(project) {
  const p = project?.debug?.last_panic
  return p ? `${p.reason || ''}@${p.at || ''}` : null
}

/** pins.check result.modules.counts → {danger, caution}; dangerCode/cautionCode: the code when one finding. */
export function stageModCounts(env) {
  const c = env?.ok ? env.result?.modules?.counts : null
  const n = k => (Number.isInteger(c?.[k]) && c[k] > 0 ? c[k] : 0)
  const ws = env?.ok && Array.isArray(env.warnings) ? env.warnings.filter(w => /^mod_/.test(w?.code || '')) : []
  const one = k => { const x = ws.filter(w => w.severity === k); return n(k) === 1 && x.length === 1 ? x[0].code : null }
  return { danger: n('danger'), caution: n('caution'), dangerCode: one('danger'), cautionCode: one('caution') }
}

/** Rail status per station → {text, tone, alert}. counts: verdict counts; panicSeen: last panic key seen (06
 *  opened); mods: stageModCounts() — module dangers count as ✕, cautions as ! (never [✓]). */
export function stageStatus(project, counts, panicSeen, mods = null) {
  const out = {}
  const c = counts || { ok: 0, caution: 0, blocked: 0, unchecked: 0 }
  const m = mods || { danger: 0, caution: 0 }
  const bad = c.blocked + m.danger
  const warn = c.caution + m.caution
  const md = [m.danger ? `${m.danger} ${m.dangerWord || 'module danger'}` : '', m.caution ? `${m.caution} ${m.cautionWord || 'module caution'}` : ''].filter(Boolean).join(' · ')
  const total = c.ok + c.caution + c.blocked + c.unchecked
  if (!project) {
    for (const s of STATIONS) out[s.id] = { text: '', tone: 'faint', alert: false }
    return out
  }
  out.plan = bad ? { text: `${bad}✕`, tone: 'bad', alert: false, ...(md && { detail: md }) }
    : warn ? { text: `${warn}!`, tone: 'warn', alert: false, ...(md && { detail: md }) }
      : total ? { text: '[✓]', tone: 'ok', alert: false } : { text: '[ ]', tone: 'faint', alert: false }
  out.calc = (project.calcs || []).length ? { text: '[✓]', tone: 'ok', alert: false } : { text: '[ ]', tone: 'faint', alert: false }
  out.wire = (project.circuits || []).length ? { text: '[✓]', tone: 'ok', alert: false } : { text: '[ ]', tone: 'faint', alert: false }
  const sp = solderProgress(project)
  const st = solderStale(project)
  out.solder = st.stale ? { text: '!', tone: 'warn', alert: false, detail: `plan outdated: ${[st.missing.length ? `${st.missing.join(', ')} not in the plan` : '', st.gone.length ? `${st.gone.join(', ')} removed` : ''].filter(Boolean).join('; ')}` }
    : !sp.total ? { text: '[ ]', tone: 'faint', alert: false }
    : sp.done >= sp.total ? { text: '[✓]', tone: 'ok', alert: false }
      : { text: `${Math.round((sp.done / sp.total) * 100)}%`, tone: sp.done ? 'active' : 'faint', alert: false }
  const fw = project.firmware || {}
  const flashedThis = fw.last_flash?.ok && (!fw.last_build?.elf_sha256 || fw.last_flash.elf_sha256 === fw.last_build.elf_sha256)
  out.flash = fw.last_build && fw.last_build.ok === false ? { text: 'FAIL', tone: 'bad', alert: false }
    : flashedThis ? { text: '[✓]', tone: 'ok', alert: false }
      : fw.last_build?.ok ? { text: 'BUILT', tone: 'active', alert: false } : { text: '[ ]', tone: 'faint', alert: false }
  const pk = panicKey(project)
  out.debug = pk && stagePanicCurrent(project) ? { text: 'PANIC', tone: 'bad', alert: pk !== panicSeen }
    : pk ? { text: '[✓]', tone: 'ok', alert: false } : { text: '[ ]', tone: 'faint', alert: false }
  return out
}

/** Stored panic still current: no successful flash after it (same rule as lib/crash.js projectPanicCurrent). */
export function stagePanicCurrent(project) {
  const p = project?.debug?.last_panic
  if (!p) return false
  const f = project?.firmware?.last_flash
  if (!f?.ok || !f.at || !p.at) return true
  return String(p.at) >= String(f.at)
}

/** First solder step that is not done (null when all are done or there is no plan). */
export function nextSolderStep(project) {
  const done = new Set(project?.solder?.done || [])
  return (project?.solder?.steps || []).find(s => !done.has(s.id)) || null
}

/** HUD figures: pins counts, solder done/total, build state. */
export function hudFigures(project, counts) {
  const fw = project?.firmware || {}
  const b = fw.last_build
  return {
    pins: counts || { ok: 0, caution: 0, blocked: 0, unchecked: 0 },
    solder: solderProgress(project),
    build: !b ? { tone: 'faint', text: '—' } : b.ok ? { tone: 'ok', text: 'OK', ram: b.ram_pct, flash: b.flash_pct }
      : { tone: 'bad', text: 'FAIL' }
  }
}
