// Module helpers: pure; top-level names mod*/MOD_* (shared lib scope)

export const MOD_BASIC_CALCS = ['led', 'npn', 'divider', 'i2c_pullup', 'mosfet', 'ldo'] // modspec.BASIC_CALCS, order fixed
export const MOD_FIXED_RAILS = { GND: 0, '3V3': 3.3, '5V': 5 } // modspec.FIXED_RAILS
export const MOD_MAX_CONN = 48 // modspec.MAX_CONN
export const MOD_OPS = ['add_module', 'connect', 'set_rails'] // modspec.MODULE_OPS
const MOD_NET_RE = /^[A-Za-z0-9_+.-]{1,32}$/
const MOD_FAMILIES = ['display', 'pixel', 'level', 'logic', 'switch', 'env', 'ambient', 'motion', 'prox', 'adc', 'powermon',
  'thermo', 'rtc', 'iox', 'motor', 'power', 'wired', 'radio', 'net'] // modspec.FAMILIES
const MOD_FAMILY_WORDS = { env: 'environment', prox: 'proximity', powermon: 'power monitor', thermo: 'temperature', iox: 'IO expander', rtc: 'RTC', adc: 'ADC' }

const modRefKey = ref => {
  const m = /^([A-Z]+)(\d+)$/.exec(String(ref || ''))
  return m ? [m[1], Number(m[2])] : [String(ref || ''), 0]
}
const modByRef = (a, b) => {
  const [pa, na] = modRefKey(a.ref)
  const [pb, nb] = modRefKey(b.ref)
  return pa < pb ? -1 : pa > pb ? 1 : na - nb
}

// parts with `module`, sorted by ref (U1, U2, … U10)
export function moduleInstances(project) {
  const parts = Array.isArray(project?.parts) ? project.parts : []
  return parts.filter(p => p && typeof p.module === 'string' && p.module).map(p => ({
    ref: p.ref, module: p.module, variant: p.variant ?? null, kind: p.kind || 'module', value: p.value || p.module,
    address: p.address ?? null, conn: p.conn && typeof p.conn === 'object' ? { ...p.conn } : {},
    facts: p.facts && typeof p.facts === 'object' ? { ...p.facts } : {}, qty: p.qty ?? 1
  })).sort(modByRef)
}

// modules + plain parts (data order)
export function partGroups(project) {
  const parts = Array.isArray(project?.parts) ? project.parts : []
  return { modules: moduleInstances(project), others: parts.filter(p => p && !(typeof p.module === 'string' && p.module)) }
}

// next free U<n> (upper case, like add_module)
export function modNextRef(parts, prefix = 'U') {
  const used = new Set((parts || []).map(p => String(p?.ref || '').toUpperCase()))
  let n = 1
  while (used.has(`${prefix}${n}`)) n++
  return `${prefix}${n}`
}

// "U1 BME280 · I²C 0x76"
export function modInstanceLabel(inst, info = null) {
  if (!inst) return ''
  const name = info?.short || inst.value || info?.title || inst.module
  const ifs = modInterfaces(info?.interfaces)
  const bus = ifs.length ? ifs[0] : null
  const addr = inst.address ? modAddress(inst.address) : null
  return [`${inst.ref} ${name}`, [bus, addr].filter(Boolean).join(' ')].filter(Boolean).join(' · ')
}

const MOD_SI = [[1e3, 'k'], [1, ''], [1e-3, 'm'], [1e-6, 'µ'], [1e-9, 'n']]

function modSI(value, unit, digits = 3) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  if (value === 0) return `0 ${unit}`
  const abs = Math.abs(value)
  let [scale, prefix] = MOD_SI[MOD_SI.length - 1]
  for (const [s, p] of MOD_SI) if (abs >= s * 0.9995) { scale = s; prefix = p; break }
  return `${Number((value / scale).toPrecision(digits))} ${prefix}${unit}`
}

const modNum = x => (typeof x === 'number' ? x : x && typeof x === 'object' && typeof x.value === 'number' ? x.value : null)

export const modVolts = v => modSI(modNum(v), 'V')
export const modAmps = a => modSI(modNum(a), 'A')

export function modAddress(a) {
  if (typeof a === 'number' && Number.isInteger(a) && a >= 0 && a < 128) return `0x${a.toString(16).padStart(2, '0')}`
  const s = String(a ?? '').trim()
  return /^0x[0-9a-f]{1,2}$/i.test(s) ? `0x${s.slice(2).toLowerCase().padStart(2, '0')}` : s
}

export function modAddresses(list, chosen = null) {
  const raw = Array.isArray(list) ? list : Array.isArray(list?.value) ? list.value : list == null ? [] : [list]
  const want = chosen == null ? null : modAddress(chosen)
  return raw.map(modAddress).filter(Boolean).map(a => (a === want ? `•${a}` : a)).join(' / ')
}

// "1.71–3.6 V" / "VDD 1.71–3.6 V · …"
export function modSupply(s) {
  if (s == null) return '—'
  if (typeof s === 'string') return s || '—'
  if (typeof s === 'number') return modVolts(s)
  if (typeof s !== 'object') return '—'
  const range = r => {
    const [lo, hi, typ] = [r?.min, r?.max, r?.typ].map(modNum)
    if (lo !== null && hi !== null) {
      const [a, b] = [modVolts(lo), modVolts(hi)].map(x => x.split(' '))
      return `${a[1] === b[1] ? a[0] : a.join(' ')}–${b.join(' ')}`
    }
    return typ !== null ? modVolts(typ) : hi !== null ? `≤ ${modVolts(hi)}` : lo !== null ? `≥ ${modVolts(lo)}` : null
  }
  if ('min' in s || 'max' in s || 'typ' in s) return range(s) || '—'
  const parts = Object.entries(s).map(([pin, r]) => { const t = range(r); return t ? `${pin} ${t}` : null }).filter(Boolean)
  return parts.length ? parts.join(' · ') : '—'
}

export const MOD_INTERFACE_LABELS = { i2c: 'I²C', spi: 'SPI', uart: 'UART', onewire: '1-Wire', i2s: 'I²S', analog: 'analog',
  digital: 'digital', pwm: 'PWM', led_serial: 'LED serial', parallel: 'parallel' }

export const modInterfaceLabel = t => MOD_INTERFACE_LABELS[t] || String(t || '')

export function modInterfaces(list) {
  const out = []
  for (const x of Array.isArray(list) ? list : []) {
    const l = modInterfaceLabel(typeof x === 'string' ? x : x?.type)
    if (l && !out.includes(l)) out.push(l)
  }
  return out
}

// findings: words of the generic rules
export const MOD_WARNING_WORDS = {
  mod_address_conflict: 'address conflict', mod_address_reserved: 'reserved address', mod_address_select: 'address select',
  mod_bus_speed: 'bus speed', mod_pin_role: 'pin role', mod_spi_cs: 'shared CS', mod_unconnected: 'not connected',
  mod_supply_range: 'supply range', mod_level_in: 'input level', mod_level_out: 'output level',
  mod_power_budget: 'power budget', mod_required_parts: 'required part', mod_hazard: 'hazard', mod_unknown: 'unknown module',
  mod_net_shared_signals: 'shared bus net', mod_pullup_parallel: 'parallel pull-ups'
}

export const MOD_SEVERITY_LOOK = {
  danger: { symbol: '⊗', tone: 'bad', level: 'danger' },
  caution: { symbol: '◇', tone: 'warn', level: 'caution' },
  info: { symbol: 'i', tone: 'dim', level: 'note' }
}

const MOD_UP = /^([a-z]+\d[a-z0-9]*|bm[ep]|vi[hl]|sdo|sd[ai]|scl|cs|rw|gnd|oled|xshut|int)$/
// modules.env.bmp_vs_bme / mod_env_bmp_vs_bme → "BMP vs BME (environment)"
export function modWarningWord(code) {
  const rest = String(code || '').replace(/^mod(ules)?[._]/, '').replace(/\./g, '_')
  if (MOD_WARNING_WORDS[`mod_${rest}`]) return MOD_WARNING_WORDS[`mod_${rest}`]
  const fam = MOD_FAMILIES.find(f => rest.startsWith(`${f}_`))
  const w = (fam ? rest.slice(fam.length + 1) : rest).split('_').filter(Boolean).map(t => (MOD_UP.test(t) ? t.toUpperCase() : t)).join(' ')
  return w ? (fam ? `${w} (${MOD_FAMILY_WORDS[fam] || fam})` : w) : 'module finding'
}

// one finding of a level → its word in HUD/rail ("1 address conflict" instead of "1 module caution")
const modShortWord = c => { const w = c ? modWarningWord(c) : ''; return w && w.length <= 16 ? w : null } // HUD room
export const modCountWords = m => ({ ...m, dangerWord: modShortWord(m.dangerCode), cautionWord: modShortWord(m.cautionCode) })

export function modWarningMeta(w) {
  const look = MOD_SEVERITY_LOOK[w?.severity] || MOD_SEVERITY_LOOK.info
  return { ...look, severity: MOD_SEVERITY_LOOK[w?.severity] ? w.severity : 'info', word: modWarningWord(w?.code) }
}

export function modStatusMeta(status) {
  switch (status) {
    case 'passed': case 'pass': return { symbol: '✓', word: 'ok', tone: 'ok' }
    case 'failed': case 'fail': return { symbol: '✕', word: 'failed', tone: 'bad' }
    case 'warn': return { symbol: '◇', word: 'caution', tone: 'warn' }
    case 'skipped': return { symbol: '○', word: 'skipped', tone: 'dim' }
    default: return { symbol: '?', word: 'not checked', tone: 'dim' }
  }
}

export function modulesResult(env) {
  const m = env && env.ok ? env.result?.modules : null
  return m && typeof m === 'object' ? m : null
}

// warnings mod_* (danger first), checks modules.* (compact check 'modules' "failed: a, b; …" split per rule)
export function modFindings(env) {
  if (!env || !env.ok) return { warnings: [], checks: [] }
  const rank = { danger: 0, caution: 1, info: 2 }
  const warnings = (Array.isArray(env.warnings) ? env.warnings : [])
    .map((w, i) => ({ w, i })).filter(({ w }) => w && String(w.code || '').startsWith('mod_'))
    .sort((a, b) => (rank[a.w.severity] ?? 3) - (rank[b.w.severity] ?? 3) || a.i - b.i)
    .map(({ w }) => ({ ...w, ...modWarningMeta(w) }))
  const checks = (Array.isArray(env.checks) ? env.checks : []).flatMap(c => (c?.id === 'modules'
    ? String(c.detail || '').split('; ').flatMap(g => { const [st, ids] = g.split(': '); return ids ? ids.split(', ').map(id => ({ id: `modules.${id}`, status: st.replace(' ', '_') })) : [] })
    : String(c?.id || '').startsWith('modules.') ? [c] : [])).map(c => ({ ...c, ...modStatusMeta(c.status) }))
  return { warnings, checks }
}

// rails with texts, load fraction (null without a limit)
export function modRails(env) {
  const m = modulesResult(env)
  return (Array.isArray(m?.rails) ? m.rails : []).map(r => {
    const limit = modNum(r.limit)
    const peak = modNum(r.i_peak) ?? modNum(r.i_max) ?? modNum(r.i_typ)
    return { net: r.net, volts: modVolts(r.volts), typ: modAmps(r.i_typ), max: modAmps(r.i_max), peak: modAmps(r.i_peak),
      limit: limit === null ? null : modAmps(limit), limitSource: r.limit_source ?? null,
      frac: limit && peak !== null ? Math.max(0, peak / limit) : null }
  })
}

// project ops (PATCH /projects/{id})
const modDefined = o => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined))

export function addModuleOp({ module, variant, ref, conn, address, facts, qty } = {}) {
  if (typeof module !== 'string' || !module.trim()) throw new Error('add_module needs a module id')
  return modDefined({ op: 'add_module', module: module.trim(), variant: variant || undefined, ref: ref ? String(ref).trim().toUpperCase() : undefined,
    conn: conn && Object.keys(conn).length ? { ...conn } : undefined, address: address ? modAddress(address) : undefined,
    facts: facts && Object.keys(facts).length ? { ...facts } : undefined, qty: qty === undefined || qty === null ? undefined : Number(qty) })
}

// connect merges; null disconnects
export function connectOp(ref, conn) {
  if (!ref) throw new Error('connect needs a ref')
  if (!conn || typeof conn !== 'object' || !Object.keys(conn).length) throw new Error('connect needs at least one pin')
  return { op: 'connect', ref: String(ref).trim().toUpperCase(), conn: { ...conn } }
}

export function setRailsOp({ rails, rail_limits: limits } = {}) {
  if (!rails && !limits) throw new Error('set_rails needs rails or rail_limits')
  return modDefined({ op: 'set_rails', rails: rails ? { ...rails } : undefined, rail_limits: limits ? { ...limits } : undefined })
}

// conn problems
export function modConnProblems(conn) {
  const out = []
  const entries = Object.entries(conn || {})
  if (entries.length > MOD_MAX_CONN) out.push(`at most ${MOD_MAX_CONN} pins per part`)
  for (const [pin, net] of entries) if (net !== null && !MOD_NET_RE.test(String(net))) out.push(`${pin}: net name ${JSON.stringify(net)} not allowed`)
  return out
}

export function modCheckExtras(project) {
  if (!moduleInstances(project).length) return {}
  return { parts: JSON.parse(JSON.stringify(project.parts)), options: JSON.parse(JSON.stringify(project.options || {})) }
}

export const MOD_CALC_META_FIELDS = ['calculators', 'calcs', 'items']

// GET /calc → [{kind, title, group, summary, params, basic}]
export function calcMetaOf(env) {
  if (!env || !env.ok || !env.result || typeof env.result !== 'object') return []
  const field = MOD_CALC_META_FIELDS.find(f => Array.isArray(env.result[f]))
  const raw = field ? env.result[field] : Array.isArray(env.result) ? env.result : []
  const list = raw.map(c => [c, c?.kind ?? c?.type ?? c?.id]).filter(([, k]) => typeof k === 'string').map(([c, kind]) => ({
    kind, title: c.title || kind, group: c.group || 'basics', summary: c.summary || '',
    params: (Array.isArray(c.params) ? c.params : []).map(p => (typeof p === 'string' ? { name: p, unit: '', required: false, default: null }
      : { name: p.name, unit: p.unit ?? '', required: Boolean(p.required), default: p.default ?? null })),
    basic: MOD_BASIC_CALCS.includes(kind)
  }))
  const basic = MOD_BASIC_CALCS.map(k => list.find(c => c.kind === k)).filter(Boolean)
  return [...basic, ...list.filter(c => !c.basic)]
}

// categories: result.categories or of the loaded items, + extras
export const modCategories = (res, ...extra) => [...new Set([...(Array.isArray(res?.categories) ? res.categories : (res?.items || []).map(m => m.category)), ...extra].filter(Boolean))].sort()

// counts.hidden ("mod_bus_speed U2,U3") → "bus speed U2 U3"
export const modHidden = list => (Array.isArray(list) ? list : []).map(x => { const [c, r] = String(x).split(' '); return [modWarningWord(c), (r || '').replace(/,/g, ' ')].join(' ').trim() })

export const modCategoryLabel = c => String(c || '').replace('.', ' · ').replace(/_/g, ' ')

// modspec.SIGNAL_MODES (first = assign preset)
export const MOD_SIGNAL_MODES = {
  i2c_sda: ['i2c_sda'], i2c_scl: ['i2c_scl'], spi_sck: ['spi_sck'], spi_cs: ['spi_cs', 'out'], spi_sdi: ['spi_mosi'],
  spi_sdo: ['spi_miso'], uart_rx: ['uart_tx'], uart_tx: ['uart_rx'], onewire: ['out', 'in_pullup', 'in'], i2s_bclk: ['out'],
  i2s_ws: ['out'], i2s_din: ['out'], i2s_dout: ['in'], digital_in: ['out', 'pwm', 'spi_mosi', 'spi_sck', 'spi_cs'], pwm_in: ['pwm', 'out'],
  led_data_in: ['out', 'pwm', 'spi_mosi'], reset_in: ['out'], enable_in: ['out'], digital_out: ['in', 'in_pullup', 'in_pulldown', 'spi_miso'],
  open_drain_out: ['in', 'in_pullup', 'in_pulldown'], analog_out: ['adc']
}
// bus lines [role, net]; more devices join the net
const MOD_BUS_LINES = { i2c_sda: ['SDA', 'SDA0'], i2c_scl: ['SCL', 'SCL0'], spi_sck: ['SCK', 'SCK0'], spi_sdi: ['MOSI', 'MOSI0'], spi_sdo: ['MISO', 'MISO0'] }

export const modAssignNet = a => a?.net || (Number.isInteger(a?.pin) ? `GPIO${a.pin}` : null)
const modFixed = n => Object.hasOwn(MOD_FIXED_RAILS, n)
export const modKeep = t => String(t ?? '').replace(/(\d) (?=[GMkmµnp]?(?:Ω|F|A|V|W|Hz)(?![A-Za-z]))/g, '$1\u00a0')

// ESP-facing pins (tied only when wired): linked | bus (connect) | open (assign)
export function modPinLinks(inst, info, assignments = []) {
  const list = Array.isArray(assignments) ? assignments : []
  return (Array.isArray(info?.pins) ? info.pins : []).filter(p => MOD_SIGNAL_MODES[p.signal] && !(p.tie && !inst?.conn?.[p.name])).map(p => {
    const modes = MOD_SIGNAL_MODES[p.signal]
    const net = inst?.conn?.[p.name] ?? null
    const a = net ? list.find(x => modAssignNet(x) === net || net === `GPIO${x.pin}`) || null : null
    const bus = !net && MOD_BUS_LINES[p.signal] ? list.find(x => modes.includes(x.mode)) || null : null
    return { pin: p.name, signal: p.signal, mode: modes[0], net, assignment: a, bus, must: Boolean(p.must_connect), optional: !p.must_connect && !MOD_BUS_LINES[p.signal],
      state: a ? 'linked' : bus ? 'bus' : 'open' }
  })
}

// assign preset for an open module pin
export function modAssignInit(inst, link, assignments = []) {
  const taken = new Set((assignments || []).map(a => a.role))
  const own = `${inst.ref}_${link.pin}`.toUpperCase().replace(/[^A-Z0-9_]/g, '_').slice(0, 24)
  const line = MOD_BUS_LINES[link.signal]
  const role = line && !taken.has(line[0]) ? line[0] : own
  const net = link.net && !modFixed(link.net) && !/^GPIO\d+$/.test(link.net) ? link.net : line && !taken.has(line[0]) ? line[1] : own
  return { role, mode: link.mode, pin: null, net, link: { ref: inst.ref, pin: link.pin } }
}

// proposed conn: bus nets, a fixed rail in the supply range, GND, address select; not tied pins
export function modSuggestConn(info, assignments = [], address = null) {
  const pins = Array.isArray(info?.pins) ? info.pins : []
  const conn = {}
  const inRange = (pin, v) => {
    const s = info?.supplies?.[pin]
    const lo = modNum(s?.min)
    const hi = modNum(s?.max)
    return lo !== null && hi !== null && v >= lo && v <= hi
  }
  for (const p of pins) {
    if (p.tie) continue
    if (MOD_BUS_LINES[p.signal]) {
      const a = (assignments || []).find(x => MOD_SIGNAL_MODES[p.signal].includes(x.mode))
      if (a) conn[p.name] = modAssignNet(a)
    } else if (p.signal === 'gnd') conn[p.name] = 'GND'
    else if (p.signal === 'supply') {
      const rail = ['3V3', '5V'].find(r => inRange(p.name, MOD_FIXED_RAILS[r]))
      if (rail) conn[p.name] = rail
    }
  }
  const netOf = (name, depth = 0) => {
    if (modFixed(name)) return name
    if (conn[name]) return conn[name]
    const t = pins.find(x => x.name === name)?.tie
    return t && depth < 4 ? netOf(t, depth + 1) : null
  }
  for (const i of Array.isArray(info?.interfaces) ? info.interfaces : []) {
    const sel = i?.select
    const want = modAddress(address ?? i.default ?? '')
    if (!sel?.pin || !sel.map || !want) continue
    const key = Object.keys(sel.map).find(k => modAddress(sel.map[k]) === want)
    const net = key ? netOf(key) : null
    if (net) conn[sel.pin] = net
  }
  return conn
}

export function modAddressChoices(info) {
  const i = (Array.isArray(info?.interfaces) ? info.interfaces : []).find(x => x?.addresses)
  if (!i) return { list: [], def: null }
  const raw = Array.isArray(i.addresses) ? i.addresses : Array.isArray(i.addresses?.value) ? i.addresses.value : []
  return { list: raw.map(modAddress), def: i.default ? modAddress(i.default) : null, page: i.addresses?.page ?? null }
}

// worst warning per ref
export function modRefFindings(warnings) {
  const out = {}
  for (const w of warnings || []) for (const r of Array.isArray(w.refs) ? w.refs : []) if (!out[r]) out[r] = w
  return out
}

export function modFText(f) {
  if (f == null) return '—'
  if (typeof f !== 'object') return typeof f === 'boolean' ? (f ? 'yes' : 'no') : String(f)
  if (typeof f.value === 'number') return modSI(f.value, f.unit || '')
  if (typeof f.value === 'boolean') return f.value ? 'yes' : 'no'
  if (typeof f.rel === 'number') return `${f.rel} × ${f.of || '?'}`
  if (typeof f.rel_offset === 'number') return `${f.of || '?'} ${f.rel_offset < 0 ? '−' : '+'} ${Math.abs(f.rel_offset)} ${f.unit || 'V'}`
  return f.value != null ? String(f.value) : '—'
}

export function modEvidence(f) {
  if (!f || typeof f !== 'object') return ''
  const ev = Array.isArray(f.evidence) ? f.evidence.join(' … ') : f.evidence || ''
  return [f.page != null ? `p. ${f.page}` : '', ev ? `“${ev}”` : '', f.conditions || ''].filter(Boolean).join(' · ')
}

// required part → calc kind | null
export function modRequireCalc(req, info) {
  const code = String(req?.code || '')
  const sig = new Set((Array.isArray(req?.pins) ? req.pins : []).map(n => (info?.pins || []).find(p => p.name === n)?.signal))
  if (/pull_?up/.test(code) && (sig.has('i2c_sda') || sig.has('i2c_scl'))) return 'i2c_pullup'
  if (/divider/.test(code)) return 'divider'
  if (/ldo|regulator/.test(code)) return 'ldo'
  return null
}

export function modRequireText(r) {
  return [r?.code, [r?.value, r?.kind].filter(Boolean).join(' '), [(r?.pins || []).join(', '), r?.to].filter(Boolean).join(' → ')]
    .filter(Boolean).join(' · ')
}
