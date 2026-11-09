// Station styles: stations 02–06, dialogs, directive card, media card, settings page. Same rules as 12-styles.js:
// every selector under .cb-root, information ≥ 11 px, uppercase labels ≥ 10 px, fg-faint only for decoration.

const CB_CSS_UI2 = `
/* shared station parts */
.cb-root .cb-push{margin-left:auto}
.cb-root .cb-ellip{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cb-root .cb-sec{display:flex;flex-direction:column;gap:8px;min-width:0}
.cb-root .cb-sec--active{border-color:color-mix(in oklab,var(--cb-active) 55%,var(--cb-stroke-strong))}
.cb-root .cb-sec--ok{border-color:color-mix(in oklab,var(--cb-ok) 55%,var(--cb-stroke-strong));
  background:linear-gradient(to bottom,color-mix(in oklab,var(--cb-ok) 6%,var(--cb-panel)),var(--cb-panel) 55%)}
.cb-root .cb-fixed{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:4px}
.cb-root .cb-sec--bad{border-color:color-mix(in oklab,var(--cb-bad) 55%,var(--cb-stroke-strong));
  background:linear-gradient(to bottom,color-mix(in oklab,var(--cb-bad) 6%,var(--cb-panel)),var(--cb-panel) 50%)}
.cb-root .cb-secn{flex:none;min-width:22px;height:18px;padding:0 4px;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--cb-stroke-strong);
  color:var(--cb-fg-dim);font-size:10px;letter-spacing:.06em;font-variant-numeric:tabular-nums}
.cb-root .cb-sec--active .cb-secn{border-color:var(--cb-active);color:var(--cb-active-text)}
.cb-root .cb-sec-aside{margin-left:auto;font-size:11px;white-space:nowrap}
.cb-root .cb-kv{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 12px;align-items:baseline;min-width:0}
.cb-root .cb-kv > span{color:var(--cb-fg-dim);font-size:10px;letter-spacing:.14em;text-transform:uppercase}
.cb-root .cb-kv > b{font-weight:600;color:var(--cb-fg);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cb-root .cb-kv--dialog{gap:7px 14px}.cb-root .cb-kv--dialog > b{white-space:normal;overflow-wrap:anywhere}
.cb-root .cb-jobline{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:11px;min-width:0}
.cb-root .cb-jobline .cb-bar{flex:1 1 80px;max-width:180px}
.cb-root .cb-hintline{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;color:var(--cb-fg-dim);font-size:11px;margin-top:6px}
.cb-root .cb-linkbtn{color:var(--cb-active-text);font-size:11px;white-space:nowrap}
.cb-root .cb-linkbtn:hover{text-decoration:underline}
.cb-root .cb-pre{margin:6px 0 0;padding:8px 10px;background:var(--cb-cons-bg);border:1px solid var(--cb-stroke);
  color:var(--cb-fg-dim);font:inherit;font-size:11px;line-height:1.5;white-space:pre-wrap;overflow-wrap:anywhere;max-height:220px;overflow:auto}
.cb-root [data-cb-focus=true]{outline:2px solid var(--cb-active);outline-offset:3px;box-shadow:var(--cb-glow-active);animation:cb-pulse 1.2s ease-in-out 3}
.cb-root .cb-bar{position:relative;height:6px;background:color-mix(in oklab,var(--cb-fg) 8%,transparent);border:1px solid var(--cb-stroke);overflow:hidden;min-width:40px}
.cb-root .cb-bar i{position:absolute;inset:0 auto 0 0;background:var(--cb-active);box-shadow:var(--cb-glow-active)}
.cb-root .cb-bar--ok i{background:var(--cb-ok);box-shadow:var(--cb-glow-ok)}.cb-root .cb-bar--warn i{background:var(--cb-warn);box-shadow:var(--cb-glow-warn)}
.cb-root .cb-bar--ind i{width:30%;animation:cb-indet 1.1s ease-in-out infinite alternate}
.cb-root .cb-checks{display:grid;gap:3px;margin-top:4px}
.cb-root .cb-chk{display:grid;grid-template-columns:14px minmax(0,1fr);gap:6px;font-size:11px;line-height:1.45}
.cb-root .cb-assume{margin-top:4px}.cb-root .cb-assume summary,.cb-root .cb-formula summary{cursor:pointer;list-style:none;display:inline-flex;align-items:center;gap:6px}
.cb-root .cb-assume summary::-webkit-details-marker,.cb-root .cb-formula summary::-webkit-details-marker{display:none}
.cb-root .cb-assume summary::before,.cb-root .cb-formula summary::before{content:"▸";color:var(--cb-fg-dim);font-size:10px}
.cb-root .cb-assume[open] summary::before,.cb-root .cb-formula[open] summary::before{content:"▾"}
.cb-root .cb-assume ul{margin:6px 0 0;padding:0 0 0 14px;display:grid;gap:3px;font-size:11px;line-height:1.45}
.cb-root .cb-assume b{color:var(--cb-fg);font-weight:600}
.cb-root .cb-simban{display:inline-flex;align-items:center;gap:2px;color:var(--cb-active-text);letter-spacing:.14em;font-size:10px;font-weight:700;white-space:nowrap}
.cb-root .cb-simrow{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:8px 0 10px;padding:6px 10px;
  border:1px dashed color-mix(in oklab,var(--cb-active) 50%,transparent);background:color-mix(in oklab,var(--cb-active) 5%,transparent);font-size:11px}
.cb-root .cb-field{display:grid;grid-template-rows:auto auto auto;gap:3px;min-width:0}
.cb-root .cb-field label{color:var(--cb-fg-dim);font-size:10px;letter-spacing:.14em;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cb-root .cb-field input,.cb-root .cb-field select{width:100%;padding:5px 7px}
.cb-root .cb-field--err input{border-color:var(--cb-bad)}
.cb-root .cb-fhint{font-size:11px;color:var(--cb-fg-dim);min-height:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cb-root .cb-field--wide .cb-fhint{white-space:normal;overflow-wrap:anywhere}
.cb-root .cb-textarea{width:100%;font:inherit;font-size:11px;color:var(--cb-fg);background:var(--cb-bg);border:1px solid var(--cb-stroke-strong);border-radius:2px;
  padding:6px 8px;resize:vertical;margin-top:4px}
.cb-root .cb-textarea:focus{outline:none;border-color:var(--cb-active)}
.cb-root .cb-inline-in{width:170px;padding:4px 7px;font-size:11px}

/* 05 FLASH */
.cb-root .cb-flashgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:10px}
.cb-root .cb-ports{display:grid;gap:4px}
.cb-root .cb-port{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;padding:4px 6px;border:1px solid var(--cb-stroke);background:var(--cb-bg)}
.cb-root .cb-port--sim{border-style:dashed}
.cb-root .cb-port--sel{border-color:color-mix(in oklab,var(--cb-active) 60%,var(--cb-stroke-strong));background:color-mix(in oklab,var(--cb-active) 6%,var(--cb-bg))}
.cb-root .cb-port-pick{display:flex;align-items:center;gap:8px;min-width:0;font-size:11px;overflow:hidden;text-align:left}
.cb-root .cb-port-pick > .cb-radio{flex:none}
.cb-root .cb-port-txt{display:grid;gap:1px;min-width:0;flex:1 1 auto}
.cb-root .cb-port-l1,.cb-root .cb-port-l2{display:flex;align-items:baseline;gap:8px;min-width:0}
.cb-root .cb-port-l1 > .cb-tagx,.cb-root .cb-port-l2 > .cb-ok{flex:none}
.cb-root .cb-port-pick b{font-weight:600;white-space:nowrap}
.cb-root .cb-radio{width:10px;height:10px;border-radius:50%;border:1px solid var(--cb-fg-dim);flex:none}
.cb-root .cb-port--sel .cb-radio{border-color:var(--cb-active);background:radial-gradient(circle,var(--cb-active) 0 3px,transparent 3.5px)}
.cb-root .cb-tagx{flex:none;padding:0 5px;border:1px solid var(--cb-stroke-strong);font-size:10px;letter-spacing:.12em;color:var(--cb-fg-dim)}
.cb-root .cb-detect{border-top:1px dashed var(--cb-stroke-strong);padding-top:8px}
.cb-root .cb-fwgrid{display:grid;grid-template-columns:minmax(0,1fr) 72px;gap:8px}
.cb-root .cb-meter{display:grid;grid-template-columns:44px minmax(0,1fr) 52px;gap:8px;align-items:center;font-size:11px}
.cb-root .cb-meter b{text-align:right;font-variant-numeric:tabular-nums}
.cb-root .cb-build{display:grid;gap:5px}

/* 06 DEBUG */
.cb-root .cb-debuggrid{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);grid-template-rows:auto 1fr;gap:12px;margin-top:10px;align-items:start;
  grid-template-areas:"mon panic" "loop panic"}
.cb-root .cb-debuggrid > [data-cb=monitor]{grid-area:mon}.cb-root .cb-debuggrid > [data-cb=fix-loop]{grid-area:loop}
.cb-root .cb-debuggrid > [data-cb=panic-analysis],.cb-root .cb-debuggrid > [data-cb=debug-calm]{grid-area:panic}
.cb-root .cb-monrow{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.cb-root .cb-monrow select{min-width:0;flex:1 1 160px}
.cb-root .cb-bootok{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;padding:8px 10px;border:1px solid color-mix(in oklab,var(--cb-ok) 50%,transparent);
  background:color-mix(in oklab,var(--cb-ok) 6%,transparent)}
.cb-root .cb-bootok code{color:var(--cb-ok-text);font:inherit;font-weight:700}
.cb-root .cb-frames-t td{font-size:11px}
.cb-root .cb-frames-t td:nth-child(2){max-width:220px;overflow:hidden;text-overflow:ellipsis}
.cb-root .cb-interp{margin:2px 0 0;padding:0 0 0 14px;display:grid;gap:3px;line-height:1.5}
.cb-root .cb-draft{color:var(--cb-fg)}
.cb-root .cb-loop{margin:2px 0 0;padding:0;list-style:none;display:grid;gap:5px}
.cb-root .cb-loop-step{display:grid;grid-template-columns:14px max-content minmax(0,1fr);gap:8px;align-items:baseline;font-size:11px}
.cb-root .cb-loop-step b{font-weight:600;text-transform:uppercase;letter-spacing:.1em;font-size:10px;color:var(--cb-fg-dim)}
.cb-root .cb-loop-step--done b{color:var(--cb-fg)}.cb-root .cb-loop-step--cur b{color:var(--cb-active-text)}

/* 02 CALC */
.cb-root .cb-calcgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:10px}
.cb-root .cb-calc-in{margin-top:6px}
.cb-root .cb-kv--calc{grid-template-columns:max-content minmax(0,1fr)}
.cb-root .cb-kv--calc > b{white-space:normal;overflow-wrap:anywhere}

/* 03 WIRE */
.cb-root .cb-wireparams{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:4px 10px;margin:8px 0 2px}
/* the drawing fills the rest of the main area and scales into it (viewBox, meet); in the stacked layout it
   keeps its aspect ratio with a sensible minimum */
.cb-root .cb-main--fill{display:flex;flex-direction:column}
.cb-root .cb-main--fill > *{flex:none}
.cb-root .cb-main--fill > .cb-svgwrap{flex:1 1 auto}
.cb-root .cb-svgwrap{position:relative;border:1px solid var(--cb-stroke-strong);display:flex;
  justify-content:center;min-height:0}
.cb-root .cb-svgwrap .cb-svg{flex:1 1 auto;min-width:0;min-height:0;display:flex}
.cb-root .cb-svgwrap .cb-svg svg{width:100%;height:100%}
.cb-root .cb-svgcap{position:absolute;font-size:11px;color:var(--cb-fg-dim);pointer-events:none}
.cb-root .cb-svg{color:var(--cb-fg);width:100%}
.cb-root .cb-svg svg{display:block;width:100%;height:auto}
.cb-root .cb-svg text{fill:currentColor;stroke:none}
.cb-root .cb-svg [data-ref]{transition:color .12s,fill .12s}
.cb-root .cb-wiretable tr[aria-selected=true] td,.cb-root .cb-table tr[aria-selected=true] td{background:color-mix(in oklab,var(--cb-active) 12%,transparent)}
.cb-root .cb-wiretable td{font-size:11px}

/* 04 SOLDER */
.cb-root .cb-stale{max-width:900px;align-items:center;margin:0 0 12px}
.cb-root .cb-stale-t{display:grid;gap:2px;min-width:0}.cb-root .cb-stale-t b{font-weight:600}
.cb-root .cb-step{display:grid;grid-template-columns:24px 30px minmax(0,1fr);gap:10px;align-items:start;padding:9px 11px;border:1px solid var(--cb-stroke-strong);background:var(--cb-panel)}
.cb-root .cb-step--cur{border-color:var(--cb-active);background:color-mix(in oklab,var(--cb-active) 6%,var(--cb-panel));box-shadow:inset 3px 0 0 var(--cb-active)}
.cb-root .cb-step--cur .cb-check{box-shadow:var(--cb-glow-active)}
.cb-root .cb-step--done{background:color-mix(in oklab,var(--cb-ok) 3%,var(--cb-bg));border-color:var(--cb-stroke)}
.cb-root .cb-step--done .cb-step-n,.cb-root .cb-step--done .cb-step-head b{color:var(--cb-fg-dim)}
.cb-root .cb-step--done .cb-check{width:18px;height:18px;font-size:12px;box-shadow:none}
.cb-root .cb-step:not(.cb-step--done):not(.cb-step--cur) .cb-step-act{color:var(--cb-fg-dim)}
.cb-root .cb-step-refs{color:var(--cb-fg);font-weight:600}
.cb-root .cb-now{padding:0 6px;border:1px solid var(--cb-active);color:var(--cb-active-text);font-size:10px;letter-spacing:.16em;font-weight:700;box-shadow:var(--cb-glow-active)}
.cb-root .cb-check{width:20px;height:20px;border:1px solid var(--cb-fg-dim);border-radius:2px;display:inline-flex;align-items:center;justify-content:center;
  color:var(--cb-ink);font-weight:800;font-size:13px}
.cb-root .cb-check[aria-checked=true]{background:var(--cb-ok-fill);border-color:var(--cb-ok-fill);box-shadow:var(--cb-glow-ok)}
.cb-root .cb-step--cur .cb-check{border-color:var(--cb-active)}
.cb-root .cb-step-n{font-size:15px;font-weight:700;color:var(--cb-fg-dim);font-variant-numeric:tabular-nums;line-height:20px}
.cb-root .cb-step--cur .cb-step-n{color:var(--cb-active-text)}
.cb-root .cb-step-head b{text-transform:uppercase;letter-spacing:.12em;font-size:11px;color:var(--cb-fg)}
.cb-root .cb-step-hints{margin:5px 0 0;padding:0;list-style:none;display:grid;gap:2px;font-size:11px;line-height:1.45}

/* directive card + media card (chat) */
.cb-root.cb-dcard{position:relative;max-width:560px;margin:6px 0;padding:10px 12px;border:1px solid var(--cb-stroke-strong);background:var(--cb-bg);color:var(--cb-fg);
  background-image:linear-gradient(var(--cb-grid) 1px,transparent 1px),linear-gradient(90deg,var(--cb-grid) 1px,transparent 1px);background-size:24px 24px}
.cb-root .cb-dcard-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;min-width:0}
.cb-root .cb-brand--sm{font-size:11px;letter-spacing:.16em}
.cb-root .cb-dcard-head b{font-weight:700}
.cb-root .cb-dcard-hl{margin-top:8px;font-size:15px;font-weight:700;letter-spacing:.06em}
.cb-root .cb-kv--dcard{margin-top:6px}.cb-root .cb-kv--dcard > b{white-space:normal;overflow-wrap:anywhere}
.cb-root .cb-svg--media{margin-top:8px}.cb-root .cb-svg--media svg{max-height:300px}
.cb-root .cb-svg--dcard{padding:8px;border:1px solid var(--cb-stroke);background:color-mix(in oklab,var(--cb-panel) 85%,transparent)}
.cb-root .cb-svg--dcard svg{max-height:230px}
/* chat card: crash frames */
.cb-root .cb-dframe{margin-top:8px}.cb-root .cb-dframe:not(.cb-frame--top) .cb-f{color:var(--cb-fg-dim)}

/* settings page (app chrome: follows the app theme) */
.cb-root.cb-settings{max-width:760px;color:var(--cb-fg);font-size:12px}
.cb-root .cb-set-h{margin:0 0 4px;font-size:15px;letter-spacing:.14em;text-transform:uppercase}
.cb-root .cb-setrow{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px;align-items:center;padding:12px 0;border-bottom:1px solid var(--cb-stroke)}
.cb-root .cb-settitle{font-weight:700;color:var(--cb-fg)}
.cb-root .cb-setdesc{color:var(--cb-fg-dim);line-height:1.5;margin-top:2px}
.cb-root .cb-setctl{display:flex;justify-content:flex-end}

/* console: timestamps off */
.cb-root .cb-log--nots .cb-line{grid-template-columns:minmax(0,1fr)}.cb-root .cb-log--nots .cb-ts{display:none}
.cb-root .cb-tabs .cb-meta .cb-simban{flex:none}
.cb-root .cb-consmeta{color:var(--cb-fg-dim);font-size:11px;overflow:hidden;text-overflow:ellipsis;min-width:0}
@container cb (max-width:1240px){.cb-root [data-cb=hud-link] .cb-simdev{display:none}}
/* narrow tile beside the chat: brand and project chip give way, the sim marker shrinks, the action stays */
@container cb (max-width:600px){.cb-root .cb-hud [data-cb=hud-brand],.cb-root .cb-hud [data-cb=hud-project]{display:none}
  .cb-root .cb-hud .cb-simban-w{display:none}}
@container cb (max-width:1099px){.cb-root .cb-flashgrid,.cb-root .cb-calcgrid,.cb-root .cb-debuggrid{grid-template-columns:minmax(0,1fr)}
  .cb-root .cb-debuggrid{grid-template-rows:none;grid-template-areas:"mon" "panic" "loop"}}
/* project manager (HUD project pill) */
.cb-root .cb-modal--wide{width:min(640px,100%)}
.cb-root .cb-note--ok{border-color:color-mix(in oklab,var(--cb-ok) 45%,transparent);color:var(--cb-ok-text)}
.cb-root .cb-projlist{list-style:none;margin:0;padding:0;display:grid;gap:6px;max-height:min(52vh,420px);overflow:auto}
.cb-root .cb-projrow{display:flex;align-items:center;gap:12px;padding:8px 10px;border:1px solid var(--cb-stroke-strong);min-width:0}
.cb-root .cb-projrow[aria-current=true]{border-color:color-mix(in oklab,var(--cb-ok) 45%,var(--cb-stroke-strong))}
.cb-root .cb-projmain{flex:1 1 auto;min-width:0;display:grid;gap:3px}
.cb-root .cb-projtitle{display:flex;align-items:center;gap:8px;min-width:0}
.cb-root .cb-projtitle b{color:var(--cb-fg);font-weight:600;white-space:nowrap}
.cb-root .cb-projmeta{font-size:11px;white-space:nowrap}
.cb-root .cb-projact,.cb-root .cb-projconfirm{display:flex;align-items:center;gap:6px;flex:none}
.cb-root .cb-hud-count{min-width:16px;padding:0 4px;border-radius:2px;text-align:center;font-variant-numeric:tabular-nums}
@container cb (max-width:380px){.cb-root .cb-hud [data-cb=hud-projects] .cb-hud-count{display:none}}
/* parts list (02 CALC inspector): remove per row */
.cb-root .cb-part-x{width:1%}
.cb-root .cb-part-x .cb-iconbtn:hover{color:var(--cb-bad-text);border-color:color-mix(in oklab,var(--cb-bad) 55%,transparent)}
.cb-root .cb-part-acts{display:inline-flex;gap:6px;justify-content:flex-end}
.cb-root .cb-part-ask td{background:color-mix(in oklab,var(--cb-warn) 7%,transparent)}
@keyframes cb-indet{from{left:0}to{left:70%}}
/* chips and boards (S2, C6, S3 variants, WT32-ETH01); state never by colour alone */
/* PLAN toolbar selects (DevKit by chip, S3 module by PSRAM kind): same height and frame as the segmented controls */
.cb-root .cb-tsel{height:29px;padding:0 6px;font-size:12px;max-width:200px;border-radius:2px;cursor:pointer}
.cb-root .cb-tsel:hover{border-color:var(--cb-active)}

/* PLAN: compact what-if line and toolbar spacing, so a 2×22 DevKit (S2) fits at 1440×900 in what-if too */
.cb-root .cb-whatif{padding:3px 10px;margin:0 0 8px}
.cb-root [data-cb=plan-toolbar] .cb-whatif{margin:0;flex:none;white-space:nowrap}
.cb-root .cb-whatif .cb-btn--sm{padding:2px 8px}
.cb-root [data-cb=plan-toolbar]{row-gap:6px}
.cb-root [data-cb=station-plan] .cb-legend{margin-bottom:8px}
.cb-root .cb-shell[data-cb-cons=open] [data-cb=station-plan] .cb-board{padding:6px 0 8px}
/* long board labels (WT32 "485_EN") widen their name cell instead of being clipped; names stay aligned to the pads */
.cb-root .cb-col--l .cb-pin{grid-template-columns:minmax(0,1fr) minmax(40px,max-content) 14px}
.cb-root .cb-col--r .cb-pin{grid-template-columns:14px minmax(40px,max-content) minmax(0,1fr)}

/* board-level warnings: one line each above the board (PLAN), a card in the inspector */
.cb-root .cb-bwarns{margin:0 0 8px}
.cb-root .cb-bwarn-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px}
.cb-root .cb-bwarn{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:10px;align-items:baseline;padding:4px 8px;
  border:1px solid var(--cb-stroke-strong);background:var(--cb-panel);font-size:12px;line-height:1.4}
.cb-root .cb-bwarn-k{font-size:10px;font-weight:700;letter-spacing:.14em;padding:1px 6px;border-radius:2px;white-space:nowrap}
.cb-root .cb-bwarn--bad{border-color:color-mix(in oklab,var(--cb-bad) 70%,transparent);border-left:3px solid var(--cb-bad);
  background:color-mix(in oklab,var(--cb-bad) 8%,var(--cb-panel))}
.cb-root .cb-bwarn--bad .cb-bwarn-k{color:var(--cb-ink);background:var(--cb-bad-fill)}
.cb-root .cb-bwarn--bad .cb-bwarn-m{color:var(--cb-fg);font-weight:600}
.cb-root .cb-bwarn--warn{border-color:color-mix(in oklab,var(--cb-warn) 55%,transparent);border-left:3px solid var(--cb-warn)}
.cb-root .cb-bwarn--warn .cb-bwarn-k{color:var(--cb-warn-text);border:1px solid color-mix(in oklab,var(--cb-warn) 60%,transparent)}
.cb-root .cb-bwarn--dim .cb-bwarn-k{color:var(--cb-fg-dim);border:1px solid var(--cb-stroke-strong)}
.cb-root .cb-bwarn-card .cb-bwarn-list{margin-top:8px}
.cb-root .cb-bwarn-card .cb-bwarn{grid-template-columns:minmax(0,1fr);gap:3px}
.cb-root .cb-bwarn-card .cb-bwarn-k{justify-self:start}

/* shared header tables (WT32: PROG then IO on each side) */
.cb-root .cb-hdr-sep{height:14px;display:flex;align-items:center;justify-content:center;color:var(--cb-fg-dim);gap:6px}
.cb-root .cb-hdr-sep::before,.cb-root .cb-hdr-sep::after{content:"";flex:1 1 auto;border-top:1px dashed var(--cb-stroke-strong)}

/* nc and signal pins: own pad shapes, plus the word in the tag */
.cb-root .cb-pin[data-cb-state=nc] .cb-name{color:var(--cb-fg-dim);font-weight:400}
.cb-root .cb-pin[data-cb-state=nc] .cb-pad{border-style:dashed;border-radius:1px;
  background:linear-gradient(45deg,transparent calc(50% - 1px),var(--cb-fg-dim) calc(50% - 1px) calc(50% + 1px),transparent calc(50% + 1px))}
.cb-root .cb-pin[data-cb-state=nc] .cb-ptag,.cb-root .cb-pin[data-cb-state=signal] .cb-ptag{color:var(--cb-fg-dim);border:1px dashed var(--cb-stroke-strong)}
.cb-root .cb-pin[data-cb-state=nc] .cb-ptag{letter-spacing:.02em}
.cb-root .cb-pin[data-cb-state=signal] .cb-name{color:var(--cb-fg-dim);font-weight:600}
.cb-root .cb-pin[data-cb-state=signal] .cb-pad{border-style:dotted;border-color:var(--cb-fg-dim);border-radius:1px}

/* module drawing: no buttons → nothing drawn */
.cb-root .cb-btns:empty{display:none}
`
