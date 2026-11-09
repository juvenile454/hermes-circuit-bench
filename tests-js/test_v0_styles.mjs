// Style registration: every 13-…–19-styles-*.js makes exactly one
// CB_CSS_PARTS.push, is in the bundle exactly once, and every rule is scoped to .cb-root (inside @media/@container
// too; @keyframes carry the cb- prefix). Styles() appends the parts at render time after the base CSS.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from '../scripts/build-desktop.mjs'
import { contrastRatio } from '../desktop-src/lib/contrast.js'
import { PHOSPHOR } from '../desktop-src/lib/tokens.js'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..', 'desktop-src')
const PART_FILES = readdirSync(SRC).filter(f => /^1[3-9]-styles-.*\.js$/.test(f)).sort()
const product = build({ withFixtures: false })

/** Evaluate tokens + all style files in bundle order (no SDK; h is a recorder) → { CB_CSS, CB_CSS_PARTS, styles } */
async function evalStyles() {
  const files = ['lib/tokens.js', '10-tokens.js', '11-styles-ui2.js', '12-styles.js', ...PART_FILES]
  const parts = files.map(f => readFileSync(join(SRC, f), 'utf8').replace(/^export\s+(?=(const|function))/gm, ''))
  const mod = `function h(t, p, c) { return { t, p, c } }\n${parts.join('\n')}\nexport { CB_CSS, CB_CSS_PARTS, Styles }\n`
  return import(`data:text/javascript;base64,${Buffer.from(mod).toString('base64')}`)
}

/** Every rule head with the stack of at-rules around it (comments removed). */
function rules(css) {
  const out = []
  const stack = []
  let buf = ''
  for (const ch of css.replace(/\/\*[\s\S]*?\*\//g, '')) {
    if (ch === '{') { const head = buf.trim(); out.push({ head, at: [...stack] }); stack.push(head); buf = '' }
    else if (ch === '}') { stack.pop(); buf = '' }
    else if (ch === ';' && stack.length) buf = ''
    else buf += ch
  }
  assert.equal(stack.length, 0, 'unbalanced braces')
  return out
}

function scopeProblems(css) {
  const bad = []
  for (const { head, at } of rules(css)) {
    const inKeyframes = at.some(a => a.startsWith('@keyframes'))
    if (head.startsWith('@keyframes')) { if (!/^@keyframes cb-[a-z0-9-]+$/.test(head)) bad.push(head); continue }
    if (head.startsWith('@')) { if (!/^@(media|container|supports)\b/.test(head)) bad.push(head); continue }
    for (const sel of head.split(',').map(s => s.trim())) {
      if (inKeyframes) { if (!/^(from|to|\d+(\.\d+)?%)$/.test(sel)) bad.push(sel); continue }
      if (!/^\.cb-root(\b|[.[:])/.test(sel) || /(^|\s)(html|body)\b/.test(sel)) bad.push(sel)
    }
  }
  return bad
}

test('the parser finds unscoped rules (self-check)', () => {
  assert.deepEqual(scopeProblems('.cb-root .a{x:1}@media (x){.b{y:2}}@keyframes spin{from{a:1}}@keyframes cb-ok{0%,50%{a:1}}'), ['.b', '@keyframes spin'])
})

test('style part files: 13-styles-kit.js exists; each file makes exactly one CB_CSS_PARTS.push and nothing else', () => {
  assert.ok(PART_FILES.includes('13-styles-kit.js'), PART_FILES.join(', '))
  for (const f of PART_FILES) {
    const src = readFileSync(join(SRC, f), 'utf8')
    assert.equal((src.match(/CB_CSS_PARTS\.push\(/g) || []).length, 1, `${f}: exactly one push`)
    const code = src.replace(/^\s*\/\/.*$/gm, '').trim()
    assert.match(code, /^CB_CSS_PARTS\.push\(`[\s\S]*`\)$/, `${f}: only the push of one template literal`)
    assert.ok(!/\$\{/.test(code), `${f}: no interpolation (static CSS)`)
  }
  assert.match(readFileSync(join(SRC, '10-tokens.js'), 'utf8'), /^const CB_CSS_PARTS = \[\]$/m)
})

test('every style part file is in the bundle exactly once, after 10-tokens.js and 12-styles.js', () => {
  const at = f => product.indexOf(`// --- ${f}\n`)
  for (const f of PART_FILES) {
    assert.equal(product.split(`// --- ${f}\n`).length - 1, 1, `${f} marker`)
    const body = readFileSync(join(SRC, f), 'utf8').trim()
    assert.equal(product.split(body).length - 1, 1, `${f} body`)
    assert.ok(at(f) > at('10-tokens.js') && at(f) > at('12-styles.js'), f)
  }
  assert.equal((product.match(/^const CB_CSS_PARTS = \[\]$/gm) || []).length, 1)
})

test('Styles() renders base CSS + every registered part in file order; each part is scoped to .cb-root', async () => {
  const { CB_CSS, CB_CSS_PARTS, Styles } = await evalStyles()
  assert.equal(CB_CSS_PARTS.length, PART_FILES.length)
  const el = Styles()
  assert.equal(el.t, 'style')
  assert.equal(el.p['data-cb'], 'style')
  assert.equal(el.c, CB_CSS + CB_CSS_PARTS.join(''))
  assert.ok(el.c.indexOf('.cb-btn--agent') > el.c.indexOf('.cb-root .cb-simban{'), 'kit after the base rules (later wins)')
  for (const [i, css] of CB_CSS_PARTS.entries()) {
    const r = rules(css)
    assert.ok(r.length > 0, PART_FILES[i])
    assert.deepEqual(scopeProblems(css), [], PART_FILES[i])
  }
  // and the whole sheet as rendered
  assert.deepEqual(scopeProblems(el.c), [])
})

test('kit rules: agent button is cyan with ink (never the alarm colour), SIM badge solid with stripes, glyph per state', async () => {
  const { CB_CSS_PARTS } = await evalStyles()
  const kit = CB_CSS_PARTS[PART_FILES.indexOf('13-styles-kit.js')]
  const agent = rules(kit).map(r => r.head).filter(h => h.includes('cb-btn--agent'))
  assert.ok(agent.length >= 2)
  const agentCss = [...kit.matchAll(/\.cb-root \.cb-btn--agent[^{]*\{([^}]*)\}/g)].map(m => m[1]).join(';')
  assert.match(agentCss, /background:var\(--cb-active-fill\)/)
  assert.match(agentCss, /color:var\(--cb-ink\)/)
  assert.ok(!/--cb-bad|--cb-warn/.test(agentCss), 'agent button uses the alarm or warn colour')
  assert.ok(contrastRatio(PHOSPHOR.ink, PHOSPHOR.active) >= 7, 'ink on active ≥ 7:1 (Phosphor)')
  const badge = /\.cb-root \.cb-simbadge\{([^}]*)\}/.exec(kit)[1]
  assert.match(badge, /border:1px solid/)
  assert.ok(!/dashed/.test(badge))
  assert.match(kit, /\.cb-simbadge-s\{[^}]*repeating-linear-gradient\(135deg/)
  assert.ok(!/cb-simbadge-t[^{]*\{[^}]*display:none/.test(kit), 'SIMULATED must stay visible')
  for (const s of ['free', 'assigned', 'caution', 'blocked', 'assigned_blocked', 'power', 'ground', 'nc', 'signal']) {
    assert.ok(kit.includes(`.cb-glyph--${s}`), `glyph ${s}`)
  }
  assert.ok(!kit.includes('.cb-statepill'), 'no rules left for the removed state pill')
  // text ≥ 10 px
  for (const m of kit.matchAll(/font-size:(\d+)px/g)) assert.ok(Number(m[1]) >= 10, m[0])
})

test('no other hidden rule removes the word SIMULATED (cb-simban-l is not used by the badge)', () => {
  const kit = readFileSync(join(SRC, '30-ui-kit.js'), 'utf8')
  const fn = kit.slice(kit.indexOf('function SimBadge'), kit.indexOf('const SimBanner'))
  assert.ok(fn.includes("'SIMULATED'"))
  assert.ok(!fn.includes('cb-simban-l'))
  assert.match(fn, /dataCb = 'sim-banner'/)
  assert.match(kit, /^const SimBanner = SimBadge$/m)
})
