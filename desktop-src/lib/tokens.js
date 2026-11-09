// Bench Phosphor tokens. Pure data, no SDK. 10-tokens.js turns them into CSS variables.
// Phosphor = fixed dark values, independent of the app theme. Follow = the app's own theme variables.

export const PHOSPHOR = {
  bg: '#040806',
  panel: '#07100b',
  raised: '#0b1710',
  fg: '#c9f5d6',
  'fg-dim': '#86b898',
  'fg-faint': '#52775f',
  stroke: '#143322',
  'stroke-strong': '#1f5236',
  ok: '#39ff88',
  active: '#2de2ff',
  warn: '#ffc23d',
  // The design spec says #ff3d6e; that measures 5.89:1 on --cb-bg (< 7:1). Same hue, lifted to 7.44:1.
  bad: '#ff6b8f',
  power: '#b98cff',
  ink: '#040806', // text on filled state colours (buttons, stamps)
  // text in a state colour: in Phosphor the pure colours already reach ≥ 7:1
  'ok-text': '#39ff88',
  'active-text': '#2de2ff',
  'warn-text': '#ffc23d',
  'bad-text': '#ff6b8f',
  'power-text': '#b98cff'
}

/** Share of the state colour in its follow-theme text variant (rest: --ui-text-primary), light app themes only.
 *  55 % is the largest share that keeps every variant ≥ 4.5:1 on Nous light bg, card and raised (violet is the limit). */
export const FOLLOW_TEXT_MIX = 55

// Follow + light app theme: Hermes' state colours are tuned for dots and fills (#c08532 amber is 3.1:1 on white),
// so text in a state colour mixes toward the theme's text colour until it reaches ≥ 4.5:1. Dark app themes
// keep the pure colours (all ≥ 5.6:1 on Nous dark). light-dark() follows the color-scheme the app sets on <html>.
const followText = v => `light-dark(color-mix(in oklab, var(${v}) ${FOLLOW_TEXT_MIX}%, var(--ui-text-primary)), var(${v}))`

export const FOLLOW = {
  bg: 'var(--dt-background)',
  panel: 'var(--dt-card)',
  raised: 'color-mix(in oklab, var(--dt-card) 92%, var(--ui-text-primary))',
  fg: 'var(--ui-text-primary)',
  'fg-dim': 'var(--ui-text-secondary)',
  'fg-faint': 'var(--ui-text-tertiary)',
  stroke: 'var(--ui-stroke-tertiary)',
  'stroke-strong': 'var(--ui-stroke-secondary)',
  ok: 'var(--ui-green)',
  active: 'var(--ui-cyan)',
  warn: 'var(--ui-yellow)',
  bad: 'var(--ui-red)',
  power: 'var(--ui-purple)',
  ink: 'var(--dt-background)',
  'ok-text': followText('--ui-green'),
  'active-text': followText('--ui-cyan'),
  'warn-text': followText('--ui-yellow'),
  'bad-text': followText('--ui-red'),
  'power-text': followText('--ui-purple')
}

/** Model materials: the board model is an object, so these are fixed values in
 *  both looks. They live outside PHOSPHOR/FOLLOW because FOLLOW holds app variables only (test_ui1_contrast.mjs);
 *  10-tokens.js sets them once on .cb-root and the theme look never overrides them. Rules (test_v0_tokens.mjs):
 *  OKLCH chroma ≤ 0.06 (no state hue), silk on pcb and metal-ink on metal ≥ 4.5:1, state rings on pcb ≥ 3:1.
 *  Start values from the board model design study; pcb darkened from #0f2e1f so the Follow + Nous light red
 *  ring (#cf2d56) also reaches 3:1, pcb-edge desaturated from #1d4a32 (chroma 0.065). */
export const MATERIAL = {
  pcb: '#0c281a', // board face (gradient start; artDefs darkens toward the end)
  'pcb-edge': '#204634', // board rim / outline against the bench background
  silk: '#c4d2c7', // silkscreen print
  metal: '#9aa4a0', // shield can, port shells
  'metal-hi': '#d7dedb', // metal highlight (gradient start)
  'metal-ink': '#1f2826', // print on the shield can
  tin: '#aeb6b2', // pads
  plastic: '#151a18', // header strips, IC bodies, button housings
  'plastic-edge': '#36413d', // their outline
  copper: '#9a8a70', // antenna meander
  cavity: '#0b0f0d' // port openings
}

// Theme "Bench Phosphor" mutedForeground: halfway between fg and fg-dim (app icons, status bar)
export const THEME_MUTED = '#a8d6b7'

export const MONO = '"JetBrains Mono", "Fira Code", "Cascadia Code", var(--dt-font-mono), ui-monospace, "DejaVu Sans Mono", monospace'

/** Contrast pairs checked by tests (name, foreground, background, minimum ratio). */
export const CONTRAST_PAIRS = [
  ['fg on bg', PHOSPHOR.fg, PHOSPHOR.bg, 7],
  ['fg-dim on bg', PHOSPHOR['fg-dim'], PHOSPHOR.bg, 7],
  ['ok on bg', PHOSPHOR.ok, PHOSPHOR.bg, 7],
  ['active on bg', PHOSPHOR.active, PHOSPHOR.bg, 7],
  ['warn on bg', PHOSPHOR.warn, PHOSPHOR.bg, 7],
  ['bad on bg', PHOSPHOR.bad, PHOSPHOR.bg, 7],
  ['power on bg', PHOSPHOR.power, PHOSPHOR.bg, 7],
  ['ok on panel', PHOSPHOR.ok, PHOSPHOR.panel, 7],
  ['power on panel', PHOSPHOR.power, PHOSPHOR.panel, 7],
  ['fg-faint on bg (decoration)', PHOSPHOR['fg-faint'], PHOSPHOR.bg, 3],
  ['fg on panel', PHOSPHOR.fg, PHOSPHOR.panel, 7],
  ['fg-dim on panel', PHOSPHOR['fg-dim'], PHOSPHOR.panel, 7],
  ['fg-dim on raised', PHOSPHOR['fg-dim'], PHOSPHOR.raised, 7],
  ['bad on panel', PHOSPHOR.bad, PHOSPHOR.panel, 7],
  ['warn on panel', PHOSPHOR.warn, PHOSPHOR.panel, 7],
  ['active on panel', PHOSPHOR.active, PHOSPHOR.panel, 7],
  ['fg-faint on panel (decoration)', PHOSPHOR['fg-faint'], PHOSPHOR.panel, 3],
  ['ink on ok (primary button)', PHOSPHOR.ink, PHOSPHOR.ok, 7],
  ['ink on active (selected segment, used tag)', PHOSPHOR.ink, PHOSPHOR.active, 7],
  ['ink on bad (stamp, danger button)', PHOSPHOR.ink, PHOSPHOR.bad, 7],
  ['ink on warn', PHOSPHOR.ink, PHOSPHOR.warn, 7],
  ['theme mutedForeground on bg', THEME_MUTED, PHOSPHOR.bg, 7],
  ['theme mutedForeground on sidebar', THEME_MUTED, '#030604', 7]
]
