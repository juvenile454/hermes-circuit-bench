// FLASH styles: flash dialog (target, hash groups with copy, memory bars, check list in
// words), job phase word, flash map (written images on an address axis), port connector symbols.
// Registered through CB_CSS_PARTS (10-tokens.js); comes after 11/12/13, so equal specificity wins here.
CB_CSS_PARTS.push(`
.cb-root .cb-vf-chk-at{white-space:nowrap}
/* dialog: three instrument blocks, each with its comment label */
.cb-root .cb-modal:has([data-cb=flash-hash]){width:min(560px,100%);max-height:calc(100% - 8px);overflow:auto}
.cb-root .cb-vf-dlg{display:grid;gap:10px;min-width:0}
.cb-root .cb-vf-block{display:grid;gap:6px;min-width:0;padding:8px 10px;border:1px solid var(--cb-stroke);background:var(--cb-bg)}
.cb-root .cb-vf-block > .cb-label{font-size:10px}
.cb-root .cb-vf-algo{color:var(--cb-fg-dim)}
.cb-root .cb-vf-block .cb-kv--dialog{gap:5px 14px}

/* hash: eight groups of eight in a 4 × 2 grid (gaps instead of spaces: the text stays one hash) */
.cb-root .cb-vf-hashrow{display:flex;align-items:flex-start;gap:10px;min-width:0}
.cb-root .cb-vf-hash{display:grid;grid-template-columns:repeat(4,max-content);gap:3px 12px;font-size:12px;line-height:1.45;letter-spacing:.04em;
  color:var(--cb-fg);min-width:0;flex:1 1 auto}
.cb-root .cb-vf-hg{white-space:nowrap}
.cb-root .cb-vf-hg:nth-child(odd){color:var(--cb-fg)}
.cb-root .cb-vf-hg:nth-child(even){color:var(--cb-fg-dim)}
.cb-root .cb-vf-hashshort{display:inline-flex;gap:6px;white-space:nowrap}
.cb-root .cb-vf-copy{flex:none;font-size:11px;white-space:nowrap}

/* memory: label · bar · percent · optional bytes */
.cb-root .cb-vf-mem{display:grid;gap:5px;margin-top:4px}
.cb-root .cb-vf-meter{display:grid;grid-template-columns:84px minmax(60px,1fr) 52px;gap:8px;align-items:center;font-size:11px;min-width:0}
.cb-root .cb-vf-meter:has(> :nth-child(4)){grid-template-columns:84px minmax(60px,1fr) 52px max-content}
/* a level gauge: 10 px track with quarter ticks (25/50/75 %) */
.cb-root .cb-vf-meter .cb-bar{height:10px;background:
  linear-gradient(90deg,transparent calc(25% - 1px),var(--cb-stroke-strong) calc(25% - 1px) 25%,transparent 25% calc(50% - 1px),var(--cb-stroke-strong) calc(50% - 1px) 50%,
  transparent 50% calc(75% - 1px),var(--cb-stroke-strong) calc(75% - 1px) 75%,transparent 75%),
  color-mix(in oklab,var(--cb-fg) 8%,transparent)}
.cb-root .cb-vf-meter .cb-bar i{z-index:1}
.cb-root .cb-vf-meter > b{text-align:right;font-weight:600}
.cb-root .cb-vf-meter > .cb-label{text-transform:uppercase}

/* check list in words: symbol · state word · sentence */
.cb-root .cb-vf-checks{list-style:none;margin:0;padding:0;display:grid;gap:4px}
.cb-root .cb-vf-chk{display:grid;grid-template-columns:14px 96px minmax(0,1fr);gap:8px;align-items:baseline;font-size:11px;min-width:0}
.cb-root .cb-vf-chk-s{font-weight:700;text-align:center}
.cb-root .cb-vf-chk-w{font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;white-space:nowrap}
.cb-root .cb-vf-chk-t{color:var(--cb-fg);min-width:0;overflow-wrap:anywhere}
.cb-root .cb-vf-chk--differs .cb-vf-chk-t{color:var(--cb-bad-text)}

/* job line: kind · phase word · percent */
.cb-root .cb-vf-phase{display:inline-flex;align-items:baseline;gap:6px;min-width:0}
.cb-root .cb-vf-phase > b{font-weight:600}
.cb-root .cb-vf-phase-w{font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--cb-active-text)}

/* port list: wrapping description (no ellipsis), connector symbol in front */
.cb-root .cb-port-l2{flex-wrap:wrap;row-gap:1px}
.cb-root .cb-vf-portdesc{min-width:0;white-space:normal;overflow-wrap:anywhere}
.cb-root .cb-vf-portsym{flex:none;width:30px;height:21px;display:block}

/* flash map: address axis with numbered marks, legend below (offsets and names, no sizes) */
.cb-root .cb-vf-map{display:grid;gap:6px;margin-top:8px;padding:8px 10px;border:1px solid var(--cb-stroke);background:var(--cb-bg)}
.cb-root .cb-vf-axis{position:relative;height:44px;margin:0 10px}
.cb-root .cb-vf-axis-line{position:absolute;left:0;right:-8px;top:21px;height:2px;background:var(--cb-stroke-strong)}
.cb-root .cb-vf-axis-line::after{content:"";position:absolute;right:-2px;top:-4px;border:5px solid transparent;border-left-color:var(--cb-stroke-strong);border-right:0}
.cb-root .cb-vf-mark{position:absolute;top:0;width:0;height:44px}
.cb-root .cb-vf-mark > i{position:absolute;left:-1px;top:14px;width:2px;height:16px;background:var(--cb-active)}
.cb-root .cb-vf-mark > b{position:absolute;left:-8px;top:0;width:16px;height:13px;line-height:13px;text-align:center;font-size:10px;font-weight:700;
  color:var(--cb-ink);background:var(--cb-active-fill)}
.cb-root .cb-vf-mark--lo > b{top:31px}
.cb-root .cb-vf-legend{list-style:none;margin:0;padding:0;display:grid;gap:3px}
.cb-root .cb-vf-legend li{display:grid;grid-template-columns:16px max-content minmax(0,1fr) max-content;gap:8px;align-items:baseline;font-size:11px}
.cb-root .cb-vf-n{width:16px;line-height:13px;text-align:center;font-size:10px;font-weight:700;color:var(--cb-ink);background:var(--cb-active-fill)}
.cb-root .cb-vf-name{min-width:0;overflow-wrap:anywhere}
/* the backend's refusal under the locked Flash button; detection warnings above the record */
.cb-root .cb-vf-gate{margin:8px 0 0}
.cb-root .cb-vf-gate b{font-weight:600}
.cb-root .cb-vf-gate-hint{display:block;margin-top:2px;color:var(--cb-fg-dim)}
.cb-root .cb-vf-gate .cb-linkbtn{margin-top:2px}
.cb-root .cb-vf-dwarn{margin:0 0 8px}
`)
