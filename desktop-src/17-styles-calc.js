// Station 02 CALC styles: card as an instrument (schematic + readout on top),
// unit inside the field, result bands, check chips, formula table, assumptions drawer, fixed source foot, equal card
// heights per grid row. Registered through CB_CSS_PARTS (10-tokens.js); later than 11/12, so equal specificity wins
// over the old calculator rules there. Only --cb-* tokens.
CB_CSS_PARTS.push(`
/* MODULES: summary line of generic cards; the group pick wraps (narrow Bench) */
.cb-root .cb-group--calc{border-right:0;padding-right:0;min-width:0}
.cb-root .cb-group--calc > .cb-seg{flex:0 1 auto;flex-wrap:wrap;min-width:0}
.cb-root .cb-calc-sum{margin:-2px 0 0;font-size:11px;line-height:1.45;color:var(--cb-fg-dim)}
/* narrow inspector, the value wraps */
@container cbinsp (max-width:300px){.cb-root [data-cb=project-parts] td:nth-child(2){white-space:normal}}
/* grid: cards of a row share the height; the foot sits at the bottom of every card */
.cb-root .cb-calcgrid{align-items:stretch}
.cb-root .cb-calc{display:flex;flex-direction:column;gap:8px;container:cbcalc/inline-size;min-width:0}
.cb-root .cb-calc > .cb-card-head{min-height:20px}

/* top = the instrument: headline and bands, schematic, checks and readings. Narrow card: result first (it dominates),
   then the schematic, then the readings; wide card: schematic left, result and readings right. */
.cb-root .cb-calc-top{display:grid;grid-template-columns:minmax(0,1fr);grid-template-areas:"read" "fig" "meas";gap:8px;align-items:start}
@container cbcalc (min-width:600px){.cb-root .cb-calc-top{grid-template-columns:auto minmax(0,1fr);grid-template-areas:"fig read" "fig meas";
  grid-template-rows:auto 1fr;column-gap:16px}}
.cb-root .cb-calc-top > .cb-calc-fig{grid-area:fig}
.cb-root .cb-calc-top > .cb-calc-readout{grid-area:read}
.cb-root .cb-calc-top > .cb-calc-meas{grid-area:meas;display:grid;gap:8px;min-width:0;align-content:start}
.cb-root .cb-calc-fig{justify-self:start;padding:6px 4px 4px;border:1px solid var(--cb-stroke);border-radius:2px;line-height:0;
  background:var(--cb-bg);background-image:linear-gradient(var(--cb-grid) 1px,transparent 1px),linear-gradient(90deg,var(--cb-grid) 1px,transparent 1px);
  background-size:12px 12px;background-position:-1px -1px}
.cb-root .cb-calc-svg{display:block;overflow:visible;font-family:var(--cb-mono)}
.cb-root .cb-calc-readout{display:grid;gap:8px;min-width:0;align-content:start}
.cb-root .cb-calc-readout--idle{padding:8px 10px;border:1px dashed var(--cb-stroke-strong);border-radius:2px}
.cb-root .cb-calc-readout--idle p{margin:0;font-size:11px;line-height:1.5;color:var(--cb-fg-dim)}
.cb-root .cb-calc-main{display:flex;align-items:baseline;gap:4px 10px;flex-wrap:wrap}
.cb-root .cb-calc-main > .cb-label{flex:1 0 100%}
.cb-root .cb-calc-big{font-size:24px;line-height:1.1;font-weight:800;font-variant-numeric:tabular-nums;letter-spacing:.02em;white-space:nowrap}
.cb-root .cb-calc-verdict{font-size:11px;white-space:nowrap}

/* ruler exact → E series */
.cb-root .cb-calc-ruler{display:grid;grid-template-columns:auto minmax(48px,1fr) auto;align-items:end;gap:8px}
.cb-root .cb-calc-rend{display:grid;gap:1px;min-width:0}
.cb-root .cb-calc-rend--to{text-align:right}
.cb-root .cb-calc-rend small,.cb-root .cb-calc-wscale small,.cb-root .cb-calc-mk{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--cb-fg-dim)}
.cb-root .cb-calc-rend b{font-size:13px;font-weight:700;white-space:nowrap;color:var(--cb-fg)}
.cb-root .cb-calc-rend--to b.cb-ok{color:var(--cb-ok-text)}.cb-root .cb-calc-rend--to b.cb-bad{color:var(--cb-bad-text)}
.cb-root .cb-calc-rtrack{position:relative;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:2px;min-width:0;padding-bottom:5px}
.cb-root .cb-calc-rtrack > i{order:2;position:relative;display:block;width:100%;height:2px;background:var(--cb-fg-dim)}
.cb-root .cb-calc-rtrack > i::before{content:"";position:absolute;left:0;top:-4px;width:2px;height:10px;background:var(--cb-fg-dim)}
.cb-root .cb-calc-rtrack > i::after{content:"";position:absolute;right:-1px;top:-4px;border-left:8px solid var(--cb-fg);border-top:5px solid transparent;border-bottom:5px solid transparent}
.cb-root .cb-calc-ruler--down .cb-calc-rtrack > i::after{right:auto;left:-1px;border-left:0;border-right:8px solid var(--cb-fg)}
.cb-root .cb-calc-rtrack > em{order:1;font-style:normal;font-size:11px;color:var(--cb-fg);white-space:nowrap}

/* meter: a value against its limit */
.cb-root .cb-calc-meter,.cb-root .cb-calc-window{display:grid;gap:4px;min-width:0}
.cb-root .cb-calc-mhead{display:flex;align-items:baseline;gap:4px 8px;flex-wrap:wrap;font-size:11px}
.cb-root .cb-calc-mhead > b{font-size:13px;white-space:nowrap}
.cb-root .cb-calc-mlim{margin-left:auto;color:var(--cb-fg-dim);white-space:nowrap}
.cb-root .cb-calc-mlim b{color:var(--cb-fg);font-weight:700}
.cb-root .cb-calc-mtrack,.cb-root .cb-calc-wtrack{position:relative;height:8px;border:1px solid var(--cb-stroke-strong);border-radius:1px;background:
  repeating-linear-gradient(90deg,transparent 0 9px,color-mix(in oklab,var(--cb-fg-faint) 45%,transparent) 9px 10px)}
.cb-root .cb-calc-mtrack::after{content:"";position:absolute;right:-1px;top:-4px;bottom:-4px;width:2px;background:var(--cb-fg)}
.cb-root .cb-calc-mfill{position:absolute;left:0;top:0;bottom:0;display:block}
.cb-root .cb-calc-mfill--fg{background:var(--cb-fg-dim)}
.cb-root .cb-calc-mfill--ok{background:var(--cb-ok)}
.cb-root .cb-calc-mfill--bad{background:var(--cb-bad)}
.cb-root .cb-calc-mscale{display:flex;justify-content:space-between;gap:8px;font-size:10px;color:var(--cb-fg-dim)}
.cb-root .cb-calc-mnote{margin:0;font-size:11px;line-height:1.45;color:var(--cb-fg-dim)}

/* I²C window: the band between R min and R max, the suggested value as a marker */
.cb-root .cb-calc-wbar{position:absolute;inset:0;display:block;opacity:.35}
.cb-root .cb-calc-wbar.cb-calc-mfill--fg{background:var(--cb-fg-dim)}
.cb-root .cb-calc-wmark{position:absolute;top:-5px;width:2px;height:16px;margin-left:-1px;background:var(--cb-fg)}
.cb-root .cb-calc-wscale{display:flex;justify-content:space-between;align-items:baseline;gap:4px 8px;flex-wrap:wrap;font-size:11px}
.cb-root .cb-calc-wscale b{white-space:nowrap}
.cb-root .cb-calc-wmid b{font-size:13px}

/* input with the unit inside the field */
.cb-root .cb-calc-in{display:grid;grid-template-columns:repeat(auto-fill,minmax(118px,1fr));gap:4px 10px}
.cb-root .cb-calc-field label{white-space:normal;overflow:visible;text-overflow:clip;line-height:1.3}
.cb-root .cb-calc-box{position:relative;display:block;min-width:0}
.cb-root .cb-calc-box--unit input{padding-right:30px}
.cb-root .cb-calc-unit{position:absolute;right:1px;top:1px;bottom:1px;display:flex;align-items:center;padding:0 7px;font-size:11px;color:var(--cb-fg-dim);
  border-left:1px solid var(--cb-stroke);pointer-events:none}
.cb-root .cb-calc-hint{white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:break-word;line-height:1.35}

/* one action row on every card */
.cb-root .cb-calc-acts{margin-top:0;align-items:center}

/* result detail */
.cb-root .cb-calc-out{display:grid;gap:6px;border-top:0;padding-top:0;min-width:0}
.cb-root .cb-calc-checks{display:grid;gap:4px;min-width:0}
.cb-root .cb-calc-chips{display:flex;flex-wrap:wrap;gap:4px}
.cb-root .cb-calc-chip{display:inline-flex;align-items:center;gap:5px;padding:1px 6px;border:1px solid var(--cb-stroke-strong);border-radius:2px;font-size:11px;
  line-height:16px;white-space:nowrap;color:var(--cb-fg)}
.cb-root .cb-calc-chip b{font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase}
.cb-root .cb-calc-chip-s{font-weight:700}
.cb-root .cb-calc-chip--ok{border-color:color-mix(in oklab,var(--cb-ok) 55%,transparent)}
.cb-root .cb-calc-chip--ok .cb-calc-chip-s,.cb-root .cb-calc-chip--ok b{color:var(--cb-ok-text)}
.cb-root .cb-calc-chip--bad{border-color:var(--cb-bad);background:color-mix(in oklab,var(--cb-bad) 12%,transparent)}
.cb-root .cb-calc-chip--bad .cb-calc-chip-s,.cb-root .cb-calc-chip--bad b{color:var(--cb-bad-text)}
.cb-root .cb-calc-chip--dim{border-style:dashed}
.cb-root .cb-calc-chip--dim .cb-calc-chip-s,.cb-root .cb-calc-chip--dim b{color:var(--cb-fg-dim)}
.cb-root .cb-calc-chkd{margin:0;font-size:11px;line-height:1.45;color:var(--cb-fg-dim)}
.cb-root .cb-calc-warnl{margin:0;display:flex;gap:8px;align-items:baseline;font-size:11px;line-height:1.45;padding:3px 0 3px 8px;border-left:2px solid var(--cb-stroke-strong)}
.cb-root .cb-calc-warnl > b{flex:none;font-size:10px;letter-spacing:.12em;text-transform:uppercase}
.cb-root .cb-calc-warnl--bad{border-left-color:var(--cb-bad)}
.cb-root .cb-calc-warnl--warn{border-left-color:var(--cb-warn)}

/* drawers: formula table and assumptions */
.cb-root .cb-calc-drawer{min-width:0;border-top:1px dashed var(--cb-stroke);padding-top:6px}
.cb-root .cb-calc-drawer > summary{display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 8px}
.cb-root .cb-calc-akeys{font-size:11px;color:var(--cb-fg-dim);min-width:0;overflow-wrap:break-word}
.cb-root .cb-calc-eqs{display:grid;gap:2px;margin-top:6px;padding:6px 8px;border-left:2px solid var(--cb-active);background:var(--cb-bg)}
.cb-root .cb-calc-eqs code{font:inherit;font-size:11px;line-height:1.5;color:var(--cb-fg);white-space:normal;overflow-wrap:normal;word-break:normal}
.cb-root table.cb-calc-steps{width:100%;margin-top:6px;border-collapse:collapse;font-size:11px;line-height:1.45}
.cb-root .cb-calc-steps th,.cb-root .cb-calc-steps td{padding:3px 4px;border-bottom:1px dashed var(--cb-stroke);text-align:left;vertical-align:baseline}
.cb-root .cb-calc-steps thead th{font-size:10px;font-weight:400;letter-spacing:.14em;text-transform:uppercase;color:var(--cb-fg-dim)}
.cb-root .cb-calc-steps tbody th{font-weight:700;color:var(--cb-fg);white-space:nowrap}
.cb-root .cb-calc-steps td{color:var(--cb-fg-dim);white-space:normal;overflow-wrap:normal;word-break:normal}
.cb-root .cb-calc-steps td.cb-r{text-align:right;color:var(--cb-active-text);font-weight:600;white-space:nowrap}
.cb-root .cb-calc-passed{display:grid;gap:2px;margin-top:8px}
.cb-root .cb-calc-alist{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 10px;margin:6px 0 0;font-size:11px;line-height:1.45}
.cb-root .cb-calc-alist dt{color:var(--cb-fg);font-weight:600}
.cb-root .cb-calc-alist dd{margin:0;color:var(--cb-fg-dim);min-width:0;overflow-wrap:break-word}

/* fixed foot with the sources: full labels, wrapping, never cut */
.cb-root .cb-calc-foot{margin-top:auto;display:flex;align-items:baseline;gap:8px;padding-top:8px;border-top:1px solid var(--cb-stroke);font-size:11px;min-width:0}
.cb-root .cb-calc-foot .cb-k{flex:none;color:var(--cb-fg-dim)}
.cb-root .cb-calc-srcs{display:flex;flex-wrap:wrap;gap:2px 12px;min-width:0}
.cb-root .cb-calc-srcs button{color:var(--cb-active-text);text-align:left;line-height:1.45;min-width:0;overflow-wrap:break-word}
.cb-root .cb-calc-srcs button:hover{text-decoration:underline}
.cb-root .cb-calc-src0{color:var(--cb-fg-dim);line-height:1.45}
`)
