// Graphic primitives lib/art.js: escaping, determinism, instance prefixes,
// no forbidden SVG parts (the sanitizeSvg list of lib/wire.js), one distinct symbol per state, textWidth.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import * as art from '../desktop-src/lib/art.js'
import { sanitizeSvg } from '../desktop-src/lib/wire.js'

const {
  artEsc, artNum, artTextWidth, artDefs, artId, artGlyph, artGlyphShapes, artPad, artPill, artPort, artButton, artIc, artCan, artAntenna,
  ART_STATE_WORDS, ART_STATES, ART_PORT_KINDS, ART_PORT_SIZE
} = art
const SRC = join(dirname(fileURLToPath(import.meta.url)), '..', 'desktop-src')

/** The regexes of sanitizeSvg, read from lib/wire.js (mirrors the list instead of copying it). */
function forbiddenList() {
  const src = readFileSync(join(SRC, 'lib', 'wire.js'), 'utf8')
  const body = src.slice(src.indexOf('export function sanitizeSvg'))
  const list = /const bad = \[([^\n]+)\]\n/.exec(body)[1]
  const res = [...list.matchAll(/\/((?:\\.|[^/\\])+)\/([a-z]*)/g)].map(m => new RegExp(m[1], m[2]))
  assert.ok(res.length >= 9, `parsed ${res.length} rules`)
  return res
}

/** One sample of every primitive (with and without prefix). */
function samples(prefix = 's3') {
  return [
    artDefs(prefix),
    ...ART_STATES.map((s, i) => artGlyph(s, 10 + i * 14, 10)),
    ...ART_STATES.map((s, i) => artPad(10 + i * 16, 30, { state: s, prefix, square: i % 2 === 0 })),
    ...ART_STATES.map((s, i) => artPad(10 + i * 16, 50, { state: s })),
    ...ART_STATES.map((s, i) => artPill(`tag${i}`, s, 100, 70 + i * 18, i % 2 ? 'l' : 'r')),
    ...ART_PORT_KINDS.map((k, i) => artPort(k, i * 70, 200, { prefix })),
    ...ART_PORT_KINDS.map((k, i) => artPort(k, i * 70, 280)),
    artButton(10, 400, 'BOOT', { prefix }), artButton(60, 400, 'RST'),
    artIc(120, 400, 44, 44, { pins: 5, label: 'UART', prefix }), artIc(200, 400, 40, 24),
    artCan(10, 480, 196, 150, ['ESP32-S3', 'WROOM-1 · N16R8', '16 MB flash'], { prefix }), artCan(220, 480, 60, 40, []),
    artAntenna(10, 650, 208, 58)
  ]
}

test('artEsc escapes & < > " \' and stringifies', () => {
  assert.equal(artEsc(`<a href="x">Tom & 'Jerry'</a>`), '&lt;a href=&quot;x&quot;&gt;Tom &amp; &#39;Jerry&#39;&lt;/a&gt;')
  assert.equal(artEsc(null), '')
  assert.equal(artEsc(35), '35')
})

test('every data input is escaped: labels, pill text, can lines, prefixes, states and kinds', () => {
  const evil = `"><script>alert(1)</script><g onload='x' a="`
  const out = [artPill(evil, 'assigned', 0, 0), artButton(0, 0, evil), artIc(0, 0, 10, 10, { label: evil }), artCan(0, 0, 100, 60, [evil, evil]),
    artDefs(evil), artPad(0, 0, { state: evil, prefix: evil }), artGlyph(evil, 0, 0), artPort(evil, 0, 0)].join('')
  assert.ok(!out.includes('<script'), 'raw <script')
  assert.ok(!/<g onload/.test(out))
  assert.ok(!/<[^>]*\sonload=/.test(out), 'onload attribute')
  assert.ok(!out.includes("'x'"))
  // text nodes and attributes hold only escaped quotes / brackets
  for (const m of out.matchAll(/="([^"]*)"/g)) assert.ok(!/[<>]/.test(m[1]), m[0])
  for (const m of out.matchAll(/>([^<]*)</g)) assert.ok(!/["'&](?![a-z#0-9]+;)/.test(m[1]), m[1])
  assert.ok(out.includes('&lt;SCRIPT&gt;') && out.includes('&lt;script&gt;'))
  // coordinates from data never reach an attribute raw
  assert.equal(artNum('1" onload="x'), 0)
  assert.equal(artNum(NaN), 0)
  assert.equal(artNum('12.3456'), 12.35)
  assert.ok(!artPad('0" onload="x', 1).includes('onload'))
})

test('deterministic: the same input gives the same string', () => {
  assert.deepEqual(samples(), samples())
  assert.equal(artDefs('a'), artDefs('a'))
})

test('two instances with different prefixes have no id collision; references stay inside their instance', () => {
  const ids = s => [...s.matchAll(/\sid="([^"]+)"/g)].map(m => m[1])
  const refs = s => [...s.matchAll(/url\(#([^)]+)\)/g)].map(m => m[1])
  const a = samples('board-a').join('')
  const b = samples('chat-b').join('')
  const ia = ids(a)
  const ib = ids(b)
  assert.ok(ia.length >= 6)
  assert.equal(new Set(ia).size, ia.length, 'duplicate id inside one instance')
  assert.deepEqual(ia.filter(x => ib.includes(x)), [])
  for (const id of ia) assert.match(id, /^cb-board-a-[a-z]+$/)
  for (const r of refs(a)) assert.ok(ia.includes(r), `dangling ${r}`)
  for (const r of refs(b)) assert.ok(ib.includes(r), `dangling ${r}`)
  for (const name of ['pcb', 'metal', 'tin', 'hatch', 'shadow', 'glow']) assert.ok(ia.includes(artId('board-a', name)), name)
  assert.equal(artId('x y/z', 'tin'), 'cb-x-y-z-tin')
})

test('no forbidden SVG parts (the sanitizeSvg list), colours only as tokens, no fixed hex values', () => {
  const rules = forbiddenList()
  const all = samples().join('')
  for (const re of rules) assert.ok(!re.test(all), `forbidden ${re}`)
  assert.equal(sanitizeSvg(`<svg xmlns="http://www.w3.org/2000/svg">${all}</svg>`).ok, true)
  assert.ok(!/<style|<image|<foreignObject|xlink|href=/i.test(all))
  assert.ok(!/#[0-9a-f]{3,6}\b(?![^"(]*\))/i.test(all.replace(/url\(#[^)]+\)/g, '')), 'fixed colour value')
  for (const m of all.matchAll(/(?:fill|stroke|stop-color|flood-color)="([^"]+)"/g)) {
    assert.match(m[1], /^(none|url\(#cb-[a-z0-9-]+\)|var\(--cb-[a-z-]+\)|color-mix\(in oklab, var\(--cb-[a-z-]+\) \d+%, var\(--cb-[a-z-]+\)\))$/, m[0])
  }
})

test('every state has its word and a distinct symbol form (not only colour)', () => {
  assert.deepEqual(ART_STATES, ['free', 'assigned', 'caution', 'blocked', 'assigned_blocked', 'power', 'ground', 'nc', 'signal'])
  assert.deepEqual(ART_STATE_WORDS, { free: 'free', assigned: 'assigned', caution: 'caution', blocked: 'blocked', assigned_blocked: 'assigned · blocked',
    power: 'power', ground: 'ground / reset', nc: 'not connected', signal: 'board signal' })
  // the form: the shapes with the same ink, so colour plays no part
  const forms = ART_STATES.map(s => JSON.stringify(artGlyphShapes(s, 6, 6, 'C', 'K')))
  assert.equal(new Set(forms).size, ART_STATES.length, 'two states share a symbol form')
  for (const s of ART_STATES) {
    const g = artGlyph(s, 6, 6)
    assert.ok(g.startsWith(`<g class="cb-art-glyph" data-cb-state="${s}">`), s)
    assert.ok(!/<text/.test(g), `${s}: symbols are shapes, not font text`)
  }
  assert.equal(artGlyph('nope', 0, 0), '')
  // symbols fill a box of at least 12 px (free/blocked: r 5 + stroke 2 → 12; assigned: r 6 → 12; caution: diagonal 11 + 2)
  const extent = s => {
    let lo = Infinity
    let hi = -Infinity
    for (const [t, a] of artGlyphShapes(s, 0, 0)) {
      const sw = a['stroke-width'] || 0
      if (t === 'circle') { lo = Math.min(lo, -a.r - sw / 2); hi = Math.max(hi, a.r + sw / 2) }
      if (t === 'rect') { lo = Math.min(lo, a.x - sw / 2); hi = Math.max(hi, a.x + a.width + sw / 2) }
      if (t === 'path') for (const n of a.d.match(/-?\d+(\.\d+)?/g).map(Number)) { lo = Math.min(lo, n - sw / 2); hi = Math.max(hi, n + sw / 2) }
    }
    return hi - lo
  }
  for (const s of ART_STATES.filter(s => s !== 'signal')) assert.ok(extent(s) >= 11.9, `${s} ${extent(s)}`)
  // the signal dot is small by design (·) but its pad/label slot is the same 12 px box; the shape stays visible
  assert.ok(extent('signal') >= 4)
})

test('pads: ring in the state tone, blocked hatched, assigned glows, unknown state falls back to free', () => {
  assert.match(artPad(0, 0, { state: 'blocked', prefix: 'p' }), /url\(#cb-p-hatch\)/)
  assert.match(artPad(0, 0, { state: 'assigned', prefix: 'p' }), /url\(#cb-p-glow\)/)
  // an assigned pad is filled (active), never tin
  assert.match(artPad(0, 0, { state: 'assigned', prefix: 'p' }), /<circle[^>]+fill="var\(--cb-active\)"[^>]+stroke="var\(--cb-active\)"/)
  assert.match(artPad(0, 0, { state: 'free' }), /stroke="var\(--cb-ok\)"/)
  assert.match(artPad(0, 0, { state: 'power', square: true }), /<rect[^>]+stroke="var\(--cb-power\)"/)
  assert.match(artPad(0, 0, { state: 'ground' }), /stroke="var\(--cb-silk\)"/)
  assert.match(artPad(0, 0, { state: 'what' }), /data-cb-state="free"/)
})

test('surface board: neutral states print in silk, state colours stay; bench keeps the theme tones', () => {
  for (const s of ['ground', 'nc', 'signal']) {
    assert.match(artGlyph(s, 0, 0, { surface: 'board' }), /var\(--cb-silk\)/, s)
    assert.ok(!artGlyph(s, 0, 0).includes('--cb-silk'), s)
    assert.match(artPill('x', s, 0, 0, 'r', { surface: 'board' }), /stroke="var\(--cb-silk\)"/, s)
  }
  assert.match(artGlyph('blocked', 0, 0, { surface: 'board' }), /var\(--cb-bad\)/)
  assert.match(artPill('x', 'caution', 0, 0, 'r', { surface: 'board' }), /var\(--cb-warn\)/)
})

test('pills: filled for assigned and assigned·blocked (+ ✕), outlined otherwise, side l ends at x', () => {
  const a = artPill('laser', 'assigned', 100, 50)
  assert.match(a, /fill="var\(--cb-active\)"/)
  assert.match(a, />LASER</)
  const ab = artPill('button', 'assigned_blocked', 0, 0)
  assert.match(ab, />BUTTON</)
  assert.match(ab, /<path class="cb-art-x"[^>]+stroke="var\(--cb-ink\)"/)
  assert.match(ab, /fill="var\(--cb-bad\)"/)
  // the ✕ sits inside the pill
  const [, rx, rw] = /<rect x="([\d.-]+)" y="[\d.-]+" width="([\d.]+)"/.exec(ab)
  const xs = /d="M([\d.]+) [\d.-]+L([\d.]+)/.exec(ab).slice(1).map(Number)
  assert.ok(xs[0] > Number(rx) + 4 && xs[1] < Number(rx) + Number(rw) - 4, `${xs} in ${rx}+${rw}`)
  assert.match(artPill('strap', 'caution', 0, 0), /<rect[^>]+fill="none"/)
  const l = artPill('SDA', 'assigned', 100, 50, 'l')
  const [, x, w] = /<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)"/.exec(l)
  assert.equal(Number(x) + Number(w), 100)
  assert.equal(artPill('', 'free', 0, 0), '')
})

test('ports: the five kinds, generic without a form claim, unknown draws nothing', () => {
  for (const k of ART_PORT_KINDS) {
    const p = artPort(k, 0, 0)
    assert.match(p, new RegExp(`data-cb-port="${k}"`))
    assert.equal(ART_PORT_SIZE[k].length, 2)
  }
  const g = artPort('generic_usb', 0, 0)
  assert.match(g, /data-cb-schematic="true"/)
  // a neutral metal jack (shell + plain opening), no dashed outline, no tongue
  assert.doesNotMatch(g, /stroke-dasharray/)
  assert.match(g, /fill="var\(--cb-metal\)"/)
  assert.equal((g.match(/<rect/g) || []).length, 2)
  assert.ok(!/data-cb-schematic/.test(artPort('micro_usb', 0, 0)))
  // micro-USB is a trapezoid opening, USB-C a stadium: different shapes
  assert.match(artPort('micro_usb', 0, 0), /<path d="M7 9H37L32 23H12Z"/)
  assert.match(artPort('usb_c', 0, 0), /rx="6"/)
  assert.equal(artPort('lightning', 0, 0), '')
  assert.equal(artPort(undefined, 0, 0), '')
})

test('ic, can and antenna', () => {
  const ic = artIc(0, 0, 44, 44, { pins: 5 })
  assert.equal((ic.match(/fill="var\(--cb-tin\)"/g) || []).length, 10)
  const can = artCan(0, 0, 196, 150, ['ESP32-S3', 'WROOM-1'])
  assert.match(can, /font-size="13" font-weight="800"[^>]*>ESP32-S3</)
  assert.match(can, /fill="var\(--cb-metal-ink\)"[^>]*>WROOM-1</)
  assert.equal((artCan(0, 0, 50, 50, [null, '', undefined]).match(/<text/g) || []).length, 0)
  const ant = artAntenna(0, 0, 208, 58)
  assert.match(ant, /stroke="var\(--cb-copper\)"/)
  assert.match(ant, /stroke-dasharray="4 3"/)
  assert.match(ant, />keep metal clear</)
  // text ≥ 10 px everywhere
  for (const m of samples().join('').matchAll(/font-size="([\d.]+)"/g)) assert.ok(Number(m[1]) >= 10, m[0])
})

test('textWidth: monospace estimate 0.6 em per code point', () => {
  assert.equal(artTextWidth('GPIO35', 10), 36)
  assert.equal(artTextWidth('', 12), 0)
  assert.equal(artTextWidth('µ·✕', 10), 18)
  assert.equal(artTextWidth(1234, 12), 28.8)
  assert.equal(artTextWidth('ab'), 12)
})

test('art.js stays pure: no SDK, DOM or import', () => {
  const src = readFileSync(join(SRC, 'lib', 'art.js'), 'utf8').replace(/^\s*\/\/.*$/gm, '')
  for (const bad of [/\bimport\s/, /\bdocument\b/, /\bwindow\b/, /\bsdk\./, /\bh\(/, /Math\.random/, /\bDate\b/]) assert.ok(!bad.test(src), String(bad))
})
