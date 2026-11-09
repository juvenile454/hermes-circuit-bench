// Tokens → CSS variables on the own root only. Look "phosphor" = fixed values, "theme" = app vars.
// Model materials (MATERIAL) are set once on .cb-root and are the same in both looks.

function tokenVars(map) {
  return Object.entries(map).map(([k, v]) => `--cb-${k}:${v};`).join('')
}

const CB_TOKEN_CSS = `
.cb-root{--cb-mono:${MONO};${tokenVars(PHOSPHOR)}
${tokenVars(MATERIAL)}
--cb-glow-ok:0 0 10px color-mix(in oklab,var(--cb-ok) 55%,transparent);
--cb-glow-active:0 0 10px color-mix(in oklab,var(--cb-active) 50%,transparent);
--cb-glow-bad:0 0 12px color-mix(in oklab,var(--cb-bad) 60%,transparent);
--cb-glow-warn:0 0 10px color-mix(in oklab,var(--cb-warn) 45%,transparent);
--cb-grid:color-mix(in oklab,var(--cb-ok) 3%,transparent);
--cb-scan:rgba(0,0,0,.18);
--cb-cons-bg:color-mix(in oklab,black 25%,var(--cb-bg));
--cb-ok-fill:var(--cb-ok);--cb-active-fill:var(--cb-active);--cb-warn-fill:var(--cb-warn);--cb-bad-fill:var(--cb-bad);}
.cb-root[data-cb-look=theme]{${tokenVars(FOLLOW)}
--cb-glow-ok:none;--cb-glow-active:none;--cb-glow-bad:none;--cb-glow-warn:none;
--cb-grid:color-mix(in oklab,var(--cb-fg) 4%,transparent);--cb-scan:transparent;
--cb-cons-bg:var(--cb-panel);
--cb-ok-fill:var(--cb-ok-text);--cb-active-fill:var(--cb-active-text);--cb-warn-fill:var(--cb-warn-text);--cb-bad-fill:var(--cb-bad-text);}
`
// --cb-cons-bg: the console is darker than the bench only in Phosphor; Follow uses the card colour (no black).
// --cb-*-fill: fills that carry --cb-ink text (buttons, stamps, tags). Follow uses the text variants there, so ink
// (= the app background) on the fill has the same ≥ 4.5:1 as the text variant on the background.

// Style registration: every 13-…–19-styles-*.js makes exactly one
// CB_CSS_PARTS.push(<template literal>). Styles() (12-styles.js) appends them at render time in file order; later files win.
const CB_CSS_PARTS = []
