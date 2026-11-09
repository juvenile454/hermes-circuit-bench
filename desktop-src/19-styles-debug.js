// DEBUG styles: 06 DEBUG panic anchor, panic analysis (ELF line, frames, register
// bank), frame ↔ log mark, console toolbar that gives way step by step instead of cutting (one CB_CSS_PARTS.push).
CB_CSS_PARTS.push(`
/* 06 DEBUG head: the title and the one panic anchor (the cards below do not repeat the stamp) */
.cb-root .cb-dbghead{display:flex;align-items:center;gap:8px 18px;flex-wrap:wrap;min-width:0}
.cb-root .cb-dbghead > .cb-title{flex:0 1 auto;min-width:0}
.cb-root .cb-panicanchor{display:inline-flex;align-items:center;gap:6px 12px;flex-wrap:wrap;min-width:0}
.cb-root .cb-panicanchor .cb-stamp{font-size:13px;padding:5px 12px;letter-spacing:.14em;white-space:nowrap;animation:cb-anchor-in .5s ease-out 1}
.cb-root .cb-anchor-at{font-size:12px;color:var(--cb-fg);white-space:nowrap}
.cb-root .cb-anchor-at b{font-weight:700;color:var(--cb-bad-text)}
@keyframes cb-anchor-in{from{opacity:0;transform:translateY(-3px)}to{opacity:1;transform:none}}

/* card order = reading order: with a panic the analysis leads (left, both rows), monitor and fix loop beside it */
.cb-root .cb-debuggrid[data-cb-panic=true]{grid-template-columns:minmax(0,7fr) minmax(0,5fr);grid-template-areas:"panic mon" "panic loop"}
@container cb (max-width:1099px){.cb-root .cb-debuggrid[data-cb-panic=true]{grid-template-columns:minmax(0,1fr);grid-template-areas:"panic" "mon" "loop"}}

/* panic analysis */
.cb-root .cb-pa-body{display:grid;gap:10px;margin-top:8px;min-width:0}
.cb-root .cb-pa-body > *{margin-top:0}
.cb-root .cb-pa-lead{margin:0;color:var(--cb-fg);font-size:13px;line-height:1.5;font-weight:600}
.cb-root .cb-pa .cb-actions{margin-top:2px}
/* ELF check: its own line, verdict then the reason, in full text colour */
.cb-root .cb-elfline{display:flex;align-items:baseline;gap:4px 10px;flex-wrap:wrap;padding:5px 9px;border:1px solid var(--cb-stroke-strong);
  border-left-width:3px;background:var(--cb-panel);font-size:12px;color:var(--cb-fg)}
.cb-root .cb-elfline-v{font-weight:700;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--cb-fg);white-space:nowrap}
.cb-root .cb-elfline-why{color:var(--cb-fg)}
.cb-root .cb-elfline--ok{border-color:color-mix(in oklab,var(--cb-ok) 55%,transparent)}.cb-root .cb-elfline--ok .cb-elfline-v{color:var(--cb-ok-text)}
.cb-root .cb-elfline--bad{border-color:color-mix(in oklab,var(--cb-bad) 60%,transparent)}.cb-root .cb-elfline--bad .cb-elfline-v{color:var(--cb-bad-text)}
.cb-root .cb-elfline--faint{border-left-color:var(--cb-fg-dim)}

/* frames: #0 carries the alarm bar; a hovered or focused frame marks its PC in the log */
.cb-root .cb-pa .cb-frames-t{margin-top:0}
.cb-root .cb-frames-t tr.cb-frow--top td{background:color-mix(in oklab,var(--cb-bad) 12%,transparent);font-weight:700}
.cb-root .cb-frames-t tr.cb-frow--top td:first-child{box-shadow:inset 3px 0 0 var(--cb-bad)}
.cb-root .cb-frames-t td:last-child{color:var(--cb-fg-dim)}
.cb-root .cb-frames-t tr.cb-frow--link:hover td,.cb-root .cb-frames-t tr.cb-frow--link:focus-visible td{background:color-mix(in oklab,var(--cb-active) 14%,transparent)}
.cb-root .cb-frames-t tr.cb-frow--link:hover td:last-child,.cb-root .cb-frames-t tr.cb-frow--link:focus-visible td:last-child{color:var(--cb-active-text)}
.cb-root .cb-frames-t tr.cb-frow--link:focus-visible{outline:2px solid var(--cb-active);outline-offset:-2px}

/* register bank: key registers as labelled readouts, the whole dump folded below */
.cb-root .cb-regbank{display:grid;gap:6px;min-width:0}
.cb-root .cb-regkeys{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.cb-root .cb-regkey{display:grid;align-content:start;gap:2px;padding:6px 9px 7px;min-width:0;border:1px solid color-mix(in oklab,var(--cb-bad) 45%,transparent);
  border-left:3px solid var(--cb-bad);background:color-mix(in oklab,var(--cb-bad) 6%,var(--cb-panel))}
.cb-root .cb-regkey:hover,.cb-root .cb-regkey:focus-visible{border-color:var(--cb-active);outline:none}
.cb-root .cb-regkey-n{font-size:11px;font-weight:700;letter-spacing:.12em;color:var(--cb-bad-text)}
.cb-root .cb-regkey-v{font-size:14px;font-weight:700;color:var(--cb-fg);letter-spacing:.02em}
.cb-root .cb-regkey-l{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--cb-fg-dim)}
.cb-root .cb-regkey-note{font-size:11px;color:var(--cb-fg);overflow-wrap:anywhere}
.cb-root .cb-regdump > summary{cursor:pointer;width:max-content;max-width:100%}
.cb-root .cb-regdump > summary .cb-label{color:var(--cb-fg-dim)}
.cb-root .cb-reggrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:2px 10px;margin-top:6px;font-size:11px}
.cb-root .cb-regcell{display:flex;justify-content:space-between;gap:8px;padding:1px 6px;color:var(--cb-fg-dim);white-space:nowrap}
.cb-root .cb-regcell-n{font-weight:600}
.cb-root .cb-regcell--key{color:var(--cb-fg);background:color-mix(in oklab,var(--cb-bad) 10%,transparent);box-shadow:inset 2px 0 0 var(--cb-bad)}
.cb-root .cb-regcell--key .cb-regcell-n{color:var(--cb-bad-text)}
.cb-root .cb-regcell:hover{color:var(--cb-fg);background:color-mix(in oklab,var(--cb-active) 12%,transparent)}
@container cb (max-width:560px){.cb-root .cb-regkeys{grid-template-columns:minmax(0,1fr)}}

/* the marked address in the raw panic lines of the log */
.cb-root .cb-logmark{background:var(--cb-active-fill);color:var(--cb-ink);font-weight:700;border-radius:1px;box-shadow:0 0 0 1px var(--cb-active-fill)}
.cb-root .cb-panic .cb-frame[tabindex]:hover,.cb-root .cb-panic .cb-frame[tabindex]:focus-visible{border-color:var(--cb-active);outline:none}

/* console toolbar: "▼ N new lines" sits here (no pill over the log corner); items give way step by step, never cut */
.cb-root .cb-followbtn{flex:none;color:var(--cb-active-text);border-color:var(--cb-active)}
.cb-root .cb-followbtn:hover{color:var(--cb-active-text);background:color-mix(in oklab,var(--cb-active) 12%,transparent)}
.cb-root .cb-tabs .cb-meta > .cb-consmeta{flex:0 1 auto;overflow:visible;text-overflow:clip;white-space:nowrap}
@container cbcons (max-width:1000px){.cb-root .cb-consport,.cb-root .cb-tabs .cb-meta .cb-simban-w{display:none}}
@container cbcons (max-width:700px){.cb-root .cb-tbl{display:none}.cb-root .cb-tabs .cb-meta{gap:6px;padding-left:8px}}
@container cbcons (max-width:560px){.cb-root .cb-tbx{display:none}}
@container cbcons (max-width:440px){.cb-root .cb-tabs [role=tab]{padding:0 8px;letter-spacing:.1em}
  .cb-root .cb-tabs .cb-meta{padding:0 6px 0 6px}
  .cb-root .cb-meta:has(.cb-followbtn) .cb-pjump{display:none}}
`)
