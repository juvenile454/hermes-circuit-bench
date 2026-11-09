// Part pictograms of station 04 (desktop-src/lib/art-parts.js). Every kind of data/solder/rules.json
// draws (own drawing or the generic part), the height table matches rules.json, flat → tall holds in the drawings,
// a polarity mark appears only with a sourced polarity hint, a transistor never gets pin letters, colours are
// material tokens only (no state colour in the material), nothing forbidden in the SVG.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { sanitizeSvg } from '../desktop-src/lib/wire.js'

// lib files share one scope in the bundle; the SVG helpers (artEl, artEsc, artNum) live in art.js (one
// set of helpers), so the test module concatenates the files like the build does
const __libSrc = ['art.js', 'art-parts.js'].map(f => readFileSync(new URL(`../desktop-src/lib/${f}`, import.meta.url), 'utf8')).join('\n')
const __lib = await import(`data:text/javascript;base64,${Buffer.from(__libSrc).toString('base64')}`)
const {
  SOLDER_ART_KINDS, SOLDER_ART_HEIGHT, SOLDER_ART_HEIGHT_WORDS, solderArtPart, solderArtPolarity, solderArtPackage,
  solderArtHintKind, solderArtTop, solderArtSourced
} = __lib

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const RULES = JSON.parse(readFileSync(join(ROOT, 'circuit_bench', 'data', 'solder', 'rules.json'), 'utf8'))
const PROJECT = JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', 'project.laser-trigger.json'), 'utf8')).result.project
const REQUIRED = ['resistor', 'diode', 'led', 'transistor', 'electrolytic', 'ceramic', 'film', 'capacitor', 'switch', 'header',
  'connector', 'terminal', 'ic', 'module', 'wire_jumper']
const MATERIAL = ['pcb', 'pcb-edge', 'silk', 'metal', 'metal-hi', 'metal-ink', 'tin', 'plastic', 'plastic-edge', 'copper', 'cavity']

test('every kind of rules.json has a pictogram: the 15 named kinds their own drawing, the rest the generic part', () => {
  assert.deepEqual([...SOLDER_ART_KINDS].sort(), [...REQUIRED].sort())
  for (const k of RULES.kinds) {
    const svg = solderArtPart(k.kind)
    assert.match(svg, /^<svg [^>]*viewBox="0 0 96 64"/, k.kind)
    const art = /data-cb-art="([^"]+)"/.exec(svg)[1]
    assert.equal(art, REQUIRED.includes(k.kind) ? k.kind : 'generic', k.kind)
    if (art === 'generic') assert.match(svg, /data-cb-schematic="true"/, `${k.kind}: generic parts are marked schematic`)
  }
  // a kind the rules do not know draws the generic part too (never nothing)
  assert.match(solderArtPart('flux_capacitor'), /data-cb-art="generic"/)
})

test('the height table equals rules.json height_class for every kind (a drawing copy, kept in sync here)', () => {
  const fromRules = Object.fromEntries(RULES.kinds.map(k => [k.kind, k.height_class]))
  assert.deepEqual(SOLDER_ART_HEIGHT, fromRules)
  assert.deepEqual(Object.fromEntries(Object.entries(SOLDER_ART_HEIGHT_WORDS).map(([k, v]) => [k, v])), RULES.order.height_classes)
})

test('flat → tall: every drawn kind of a taller class stands taller than every kind of a lower class', () => {
  const byClass = {}
  for (const k of [...REQUIRED, ...RULES.kinds.map(x => x.kind)]) {
    const c = SOLDER_ART_HEIGHT[k]
    if (c === 4) continue // unknown height: no claim
    for (const pkg of k === 'transistor' ? [null, 'can', 'to92'] : [null]) (byClass[c] ||= []).push(solderArtTop(k, pkg))
  }
  for (let c = 0; c < 3; c++) {
    assert.ok(Math.min(...byClass[c]) > Math.max(...byClass[c + 1]), `class ${c} (${byClass[c]}) vs ${c + 1} (${byClass[c + 1]})`)
  }
})

test('SVG is safe and deterministic, data is escaped, colours are material tokens or currentColor only', () => {
  const states = /var\(--cb-(ok|active|warn|bad|power)(-[a-z]+)?\)/
  for (const k of [...REQUIRED, ...RULES.kinds.map(x => x.kind)]) {
    for (const pol of [null, solderArtPolarity({ kind: k, hints: RULES.kinds.find(x => x.kind === k)?.hints || [] })]) {
      const svg = solderArtPart(k, { polarity: pol, label: `${k} <x>` })
      assert.equal(svg, solderArtPart(k, { polarity: pol, label: `${k} <x>` }), 'deterministic')
      assert.ok(sanitizeSvg(svg).ok, `${k}: ${sanitizeSvg(svg).reason}`)
      assert.ok(!states.test(svg), `${k}: state colour in a pictogram`)
      assert.ok(!/#[0-9a-f]{3,8}\b|rgb\(|hsl\(/i.test(svg), `${k}: raw colour`)
      for (const m of svg.matchAll(/var\(--cb-([a-z-]+)\)/g)) assert.ok(MATERIAL.includes(m[1]), `${k}: token --cb-${m[1]}`)
      assert.ok(!/<text\b/.test(svg), `${k}: no text in a pictogram (pin letters, sizes)`)
      assert.ok(!/<x>/.test(svg), 'label escaped')
    }
  }
  const evil = solderArtPart('"><script>alert(1)</script>', { label: '<b>x</b>' })
  assert.ok(sanitizeSvg(evil).ok, sanitizeSvg(evil).reason)
  assert.ok(!/<script|<b>/.test(evil))
  assert.match(solderArtPart('led'), /aria-hidden="true"/, 'decorative without label')
  assert.match(solderArtPart('led', { label: 'LED' }), /role="img" aria-label="LED"/)
})

test('polarity mark only with a polarity hint that has a source beyond the rule of thumb', () => {
  const rule = k => RULES.kinds.find(x => x.kind === k)
  const marks = Object.fromEntries(RULES.kinds.map(k => [k.kind, solderArtPolarity({ kind: k.kind, hints: k.hints })?.mark || null]))
  assert.deepEqual(Object.entries(marks).filter(([, m]) => m), [['diode', 'cathode-band'], ['transistor', 'pinout-datasheet'], ['led', 'cathode'],
    ['electrolytic', 'minus-stripe']])
  // buzzer: polarity hint, but rule of thumb only → no mark; capacitor of unclear type → no mark; battery/ic → no mark
  for (const k of ['buzzer', 'capacitor', 'battery', 'ic']) assert.equal(marks[k], null, k)
  // no hint, or the hint without a source, or only the rule of thumb → nothing
  assert.equal(solderArtPolarity({ kind: 'electrolytic', hints: [] }), null)
  assert.equal(solderArtPolarity({ kind: 'electrolytic', hints: [{ code: 'polarity', severity: 'danger', text: 'x', source_ids: [] }] }), null)
  assert.equal(solderArtPolarity({ kind: 'diode', hints: [{ code: 'polarity', severity: 'caution', text: 'x', source_ids: ['rule-of-thumb'] }] }), null)
  assert.equal(solderArtPolarity({ kind: 'diode', hints: [{ code: 'heat_sensitive', severity: 'caution', text: 'x', source_ids: ['solder-onsemi-1n4001'] }] }), null)
  assert.equal(solderArtPolarity({ kind: 'transistor', hints: rule('transistor').hints.filter(x => x.code !== 'pinout') }), null)
  assert.equal(solderArtPolarity(null), null)
  assert.ok(solderArtSourced({ source_ids: ['rule-of-thumb', 'solder-x'] }))
  assert.ok(!solderArtSourced({ source_ids: ['rule-of-thumb'] }))
  // the drawing follows the mark: without polarity no data-cb-mark anywhere
  for (const k of ['electrolytic', 'diode', 'led', 'transistor']) {
    const pol = solderArtPolarity({ kind: k, hints: rule(k).hints })
    assert.ok(!/data-cb-mark|data-cb-polarity/.test(solderArtPart(k)), `${k} without polarity`)
    const svg = solderArtPart(k, { polarity: pol })
    assert.match(svg, new RegExp(`data-cb-polarity="${pol.mark}"`))
    if (k !== 'transistor') assert.match(svg, new RegExp(`data-cb-mark="${pol.mark}"`), k)
    else assert.ok(!/data-cb-mark/.test(svg), 'transistor: no pin marks, only the tag pinout: datasheet')
    assert.deepEqual(pol.source_ids, rule(k).hints.find(x => x.code === (k === 'transistor' ? 'pinout' : 'polarity')).source_ids)
  }
  assert.equal(solderArtPolarity({ kind: 'transistor', hints: rule('transistor').hints }).label, 'pinout: datasheet')
  // a polarity object handed to a kind without a drawing changes nothing
  assert.ok(!/data-cb-polarity/.test(solderArtPart('buzzer', { polarity: { mark: 'minus-stripe', label: 'x' } })))
})

test('fixture project: C1 gets the minus stripe, Q1 the datasheet tag, the others nothing', () => {
  const got = PROJECT.solder.steps.map(s => [s.kind, solderArtPolarity(s)?.mark || null])
  assert.deepEqual(got, [['resistor', null], ['transistor', 'pinout-datasheet'], ['electrolytic', 'minus-stripe'], ['switch', null], ['connector', null]])
})

test('transistor body follows the package of the parts (TO-18 metal can), never guessed', () => {
  const q = PROJECT.solder.steps.find(s => s.kind === 'transistor')
  assert.equal(solderArtPackage(q, PROJECT.parts), 'can')
  assert.equal(solderArtPackage({ refs: ['Q9'] }, [{ ref: 'Q9', package: 'TO-92' }]), 'to92')
  assert.equal(solderArtPackage({ refs: ['Q9'] }, [{ ref: 'Q9' }]), null)
  assert.equal(solderArtPackage({ refs: ['Q8', 'Q9'] }, [{ ref: 'Q8', package: 'TO-92' }, { ref: 'Q9', package: 'TO-18' }]), null, 'mixed → neutral')
  assert.equal(solderArtPackage({ refs: ['Q9'] }, []), null)
  assert.match(solderArtPart('transistor', { pkg: 'can' }), /var\(--cb-metal\)/)
  assert.notEqual(solderArtPart('transistor', { pkg: 'can' }), solderArtPart('transistor'))
})

test('hint lines: every hint code of rules.json maps to polarity | heat | safety | tip', () => {
  const hints = [...RULES.kinds.flatMap(k => k.hints), ...RULES.text_rules, ...Object.values(RULES.extra_hints)]
  for (const x of hints) assert.ok(['polarity', 'heat', 'safety', 'tip'].includes(solderArtHintKind(x)), x.code)
  const k = (code, severity = 'caution') => solderArtHintKind({ code, severity })
  assert.equal(k('polarity', 'danger'), 'polarity')
  assert.equal(k('pinout'), 'polarity')
  assert.equal(k('kind_uncertain'), 'polarity')
  assert.equal(k('orientation', 'caution'), 'polarity')
  assert.equal(k('orientation', 'info'), 'tip')
  assert.equal(k('heat_sensitive'), 'heat')
  assert.equal(k('laser_safety', 'danger'), 'safety')
  assert.equal(k('battery_safety', 'danger'), 'safety')
  assert.equal(k('low_voltage_only'), 'safety')
  assert.equal(k('mechanical', 'info'), 'tip')
  assert.equal(k('something_new'), 'tip')
})
