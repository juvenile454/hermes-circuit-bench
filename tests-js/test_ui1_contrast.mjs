// Bench Phosphor contrast: text and state colours ≥ 7:1, --cb-fg-faint (decoration) ≥ 3:1.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { contrastRatio, luminance, hexToRgb, mixHex, contrastReport, resolveCss, composite } from '../desktop-src/lib/contrast.js'
import { PHOSPHOR, FOLLOW, CONTRAST_PAIRS } from '../desktop-src/lib/tokens.js'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..', 'desktop-src')

test('WCAG maths', () => {
  assert.deepEqual(hexToRgb('#0f0'), [0, 255, 0])
  assert.equal(Math.round(contrastRatio('#000000', '#ffffff') * 100) / 100, 21)
  assert.equal(contrastRatio('#123456', '#123456'), 1)
  assert.ok(Math.abs(luminance('#ffffff') - 1) < 1e-9)
  assert.equal(mixHex('#ffffff', '#000000', 0.5), '#808080')
  assert.throws(() => hexToRgb('green'))
})

test('Phosphor colour pairs meet their contrast minimum', () => {
  const rows = contrastReport(CONTRAST_PAIRS)
  const table = rows.map(r => `${r.pass ? 'ok  ' : 'FAIL'} ${r.ratio.toFixed(2).padStart(6)}:1 (min ${r.min}) ${r.name}`).join('\n')
  console.log(table)
  assert.deepEqual(rows.filter(r => !r.pass), [], table)
})

test('the mockup red #ff3d6e would fail 7:1; the token was lifted', () => {
  assert.ok(contrastRatio('#ff3d6e', PHOSPHOR.bg) < 7)
  assert.ok(contrastRatio(PHOSPHOR.bad, PHOSPHOR.bg) >= 7)
})

test('follow-theme tokens point at app variables only', () => {
  assert.deepEqual(Object.keys(FOLLOW).sort(), Object.keys(PHOSPHOR).sort())
  for (const v of Object.values(FOLLOW)) assert.match(v, /var\(--(ui|dt)-/)
})

// ─── Follow app theme + Nous (light app) ─────────────────────────────────────────────────────────────────────
// App values read from the Hermes checkout (read only), commit bf0203a794 (2026-10-22):
//   apps/shared/src/theme-presets.ts       THEME_PRESET_PALETTES.nous.colors / .darkColors (background, foreground, card)
//   apps/desktop/src/styles.css            :root / :root.dark --ui-red|yellow|green|cyan|purple, --ui-text-* (94/74/54 %
//                                          of --ui-base), --ui-bg-chrome / --ui-bg-editor mixes, --theme-neutral-*
//   apps/desktop/src/themes/context.tsx    mixesFor(): --theme-mix-chrome 92 % light / 74 % dark, --theme-mix-card 22 / 38 %;
//                                          --theme-foreground = colors.foreground (overrides the CSS default)
const NOUS = {
  light: {
    '--ui-base': '#1f2328',
    '--ui-bg-chrome': 'color-mix(in srgb, #ffffff 92%, #f3f3f3)',
    '--ui-bg-editor': 'color-mix(in srgb, #f6f8fa 22%, #fcfcfc)',
    '--ui-red': '#cf2d56', '--ui-yellow': '#c08532', '--ui-green': '#1f8a65', '--ui-cyan': '#4c7f8c', '--ui-purple': '#9e94d5'
  },
  dark: {
    '--ui-base': '#e6edf3',
    '--ui-bg-chrome': 'color-mix(in srgb, #0d1117 74%, #0d0d0e)',
    '--ui-bg-editor': 'color-mix(in srgb, #010409 38%, #161618)',
    '--ui-red': '#e75e78', '--ui-yellow': '#c08532', '--ui-green': '#55a583', '--ui-cyan': '#6f9ba6', '--ui-purple': '#9e94d5'
  }
}
const APP_COMMON = {
  '--ui-text-primary': 'color-mix(in srgb, var(--ui-base) 94%, transparent)',
  '--ui-text-secondary': 'color-mix(in srgb, var(--ui-base) 74%, transparent)',
  '--ui-text-tertiary': 'color-mix(in srgb, var(--ui-base) 54%, transparent)',
  '--ui-stroke-tertiary': 'color-mix(in srgb, var(--ui-base) 5%, transparent)',
  '--ui-stroke-secondary': 'color-mix(in srgb, var(--ui-base) 7%, transparent)',
  '--dt-background': 'var(--ui-bg-chrome)',
  '--dt-card': 'var(--ui-bg-editor)'
}

/** The bench variables in look "theme" (tokens.js FOLLOW + 10-tokens.js fills/console) for one Nous scheme. */
function followVars(scheme) {
  const vars = { ...APP_COMMON, ...NOUS[scheme] }
  for (const [k, v] of Object.entries(FOLLOW)) vars[`--cb-${k}`] = v
  const css = readFileSync(join(SRC, '10-tokens.js'), 'utf8')
  const theme = css.slice(css.indexOf('.cb-root[data-cb-look=theme]'), css.lastIndexOf('`'))
  for (const m of theme.matchAll(/(--cb-(?:cons-bg|[a-z]+-fill)):([^;]+);/g)) vars[m[1]] = m[2]
  return vars
}
const opaque = (expr, vars, scheme, under) => {
  const c = resolveCss(expr, vars, scheme)
  return composite(c, under ? opaque(under, vars, scheme) : '#000000')
}

for (const scheme of ['light', 'dark']) {
  test(`Follow + Nous ${scheme}: text ≥ 4.5:1, state text variants ≥ 4.5:1, ink on fills ≥ 4.5:1, console without black`, () => {
    const vars = followVars(scheme)
    const bg = opaque('var(--cb-bg)', vars, scheme)
    const grounds = { bg, panel: opaque('var(--cb-panel)', vars, scheme, 'var(--cb-bg)'), raised: opaque('var(--cb-raised)', vars, scheme, 'var(--cb-bg)'),
      console: opaque('var(--cb-cons-bg)', vars, scheme, 'var(--cb-bg)') }
    const pairs = []
    for (const [gname, g] of Object.entries(grounds)) {
      for (const t of ['fg', 'fg-dim', 'ok-text', 'active-text', 'warn-text', 'bad-text', 'power-text']) {
        pairs.push([`${t} on ${gname}`, opaque(`var(--cb-${t})`, vars, scheme, `var(--cb-${gname === 'bg' ? 'bg' : gname === 'console' ? 'cons-bg' : gname})`), g, 4.5])
      }
      if (gname !== 'raised') pairs.push([`fg-faint on ${gname} (decoration)`, opaque('var(--cb-fg-faint)', vars, scheme, 'var(--cb-bg)'), g, 3])
    }
    for (const s of ['ok', 'active', 'warn', 'bad']) pairs.push([`ink on ${s}-fill (buttons, stamps, tags)`, opaque('var(--cb-ink)', vars, scheme), opaque(`var(--cb-${s}-fill)`, vars, scheme, 'var(--cb-bg)'), 4.5])
    // text colours mixed in the stylesheets (backtrace lines, PSRAM note …) on the console / panel
    const sheets = ['11-styles-ui2.js', '12-styles.js'].map(f => readFileSync(join(SRC, f), 'utf8')).join('\n')
    for (const m of new Set([...sheets.matchAll(/(?<=[{;\s])color:(color-mix\([^;{}]*\))[;}]/g)].map(x => x[1]))) {
      pairs.push([`mixed text ${m} on console`, opaque(m, vars, scheme, 'var(--cb-cons-bg)'), grounds.console, 4.5])
    }
    const rows = contrastReport(pairs)
    const table = rows.map(r => `${r.pass ? 'ok  ' : 'FAIL'} ${r.ratio.toFixed(2).padStart(6)}:1 (min ${r.min}) ${r.name}`).join('\n')
    console.log(`Nous ${scheme} (bg ${bg})\n${table}`)
    assert.deepEqual(rows.filter(r => !r.pass), [], table)
    // the console is the card colour in Follow, never a black mix (the light console measured (173,173,173))
    assert.equal(grounds.console, grounds.panel)
    assert.ok(luminance(grounds.console) > 0.85 || scheme === 'dark')
  })
}

test('the pure Nous light state colours fail as text (why the -text variants exist)', () => {
  const vars = followVars('light')
  const bg = opaque('var(--cb-bg)', vars, 'light')
  assert.equal(bg, '#fefefe')
  assert.ok(contrastRatio('#c08532', bg) < 4.5) // amber 3.13:1
  assert.ok(contrastRatio('#9e94d5', bg) < 4.5) // violet 2.72:1
})

test('Phosphor text variants are the pure colours; no stylesheet uses a pure state colour as text colour', () => {
  for (const k of ['ok', 'active', 'warn', 'bad', 'power']) assert.equal(PHOSPHOR[`${k}-text`], PHOSPHOR[k])
  const sheets = readdirSync(SRC).filter(f => /^1\d-.*\.js$/.test(f)).map(f => readFileSync(join(SRC, f), 'utf8')).join('\n')
  assert.deepEqual([...sheets.matchAll(/(?<=[{;\s])color:var\(--cb-(ok|warn|bad|active|power)\)/g)].map(m => m[0]), [])
})

test('resolveCss evaluates the token syntax (oklab mixes with alpha, light-dark, var fallbacks)', () => {
  assert.deepEqual(resolveCss('#fff'), { hex: '#ffffff', alpha: 1 })
  assert.equal(resolveCss('light-dark(#000000, #ffffff)', {}, 'dark').hex, '#ffffff')
  assert.equal(resolveCss('color-mix(in srgb, #ffffff 50%, #000000)').hex, '#808080')
  assert.equal(resolveCss('var(--x, #123456)').hex, '#123456')
  assert.equal(Math.round(resolveCss('color-mix(in srgb, #000000 94%, transparent)').alpha * 100), 94)
  assert.equal(resolveCss('color-mix(in oklab, #ff0000 100%, #0000ff)').hex, '#ff0000')
  assert.throws(() => resolveCss('rgb(1 2 3)'))
})
