// Styles: one <style> per surface root, every selector under .cb-root. No Tailwind classes.

const CB_CSS = CB_TOKEN_CSS + `
.cb-root{font-family:var(--cb-mono);font-size:12px;line-height:1.45;color:var(--cb-fg);-webkit-font-smoothing:antialiased;
  font-variant-ligatures:none;text-align:left}
.cb-root *,.cb-root *::before,.cb-root *::after{box-sizing:border-box}
.cb-root button{font:inherit;color:inherit;background:none;border:0;padding:0;margin:0;cursor:pointer;text-align:inherit;letter-spacing:inherit}
.cb-root button:disabled{cursor:default}
.cb-root :focus-visible{outline:1px solid var(--cb-active);outline-offset:2px}
.cb-root input,.cb-root select{font:inherit;color:var(--cb-fg);background:var(--cb-bg);border:1px solid var(--cb-stroke-strong);
  border-radius:2px;padding:6px 8px;outline:none;min-width:0}
.cb-root input::placeholder{color:var(--cb-fg-dim);opacity:.8}
.cb-root input:focus,.cb-root select:focus{border-color:var(--cb-active);box-shadow:var(--cb-glow-active)}
.cb-root .cb-ok{color:var(--cb-ok-text)}.cb-root .cb-warn{color:var(--cb-warn-text)}.cb-root .cb-bad{color:var(--cb-bad-text)}
.cb-root .cb-active{color:var(--cb-active-text)}.cb-root .cb-power{color:var(--cb-power-text)}.cb-root .cb-faint{color:var(--cb-fg-faint)}
.cb-root .cb-dim{color:var(--cb-fg-dim)}.cb-root .cb-fg{color:var(--cb-fg)}
.cb-root .cb-label{text-transform:uppercase;letter-spacing:.14em;font-size:10px;color:var(--cb-fg-dim);font-weight:400}
.cb-root .cb-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.cb-root .cb-mono-num{font-variant-numeric:tabular-nums}

/* page shell */
.cb-root.cb-page{position:relative;width:100%;height:100%;min-height:0;overflow:hidden;background:var(--cb-bg);container:cb/size}
.cb-root.cb-page::after,.cb-root.cb-pane::after{content:"";position:absolute;inset:0;pointer-events:none;z-index:40;
  background:repeating-linear-gradient(to bottom,transparent 0 2px,var(--cb-scan) 2px 3px)}
.cb-root .cb-shell{position:absolute;inset:0;display:grid;--cb-rail-w:188px;--cb-insp-w:340px;--cb-cons-h:184px;
  grid-template-rows:52px minmax(0,1fr) var(--cb-cons-h);grid-template-columns:var(--cb-rail-w) minmax(0,1fr) var(--cb-insp-w);
  grid-template-areas:"hud hud hud" "rail main insp" "rail cons cons"}
.cb-root .cb-shell[data-cb-cons=collapsed],.cb-root .cb-shell[data-cb-cons=pane],.cb-root .cb-shell[data-cb-cons=idle]{--cb-cons-h:34px}
/* 06 DEBUG: the log is the subject, the panic block (≈15 lines) needs the room */
.cb-root[data-cb-station=debug] .cb-shell[data-cb-cons=open]{--cb-cons-h:260px}
.cb-root .cb-shell[data-cb-insp=none]{grid-template-columns:var(--cb-rail-w) minmax(0,1fr);grid-template-areas:"hud hud" "rail main" "rail cons"}
.cb-root .cb-work{display:contents}
.cb-root .cb-main{grid-area:main;position:relative;min-width:0;min-height:0;overflow:auto;padding:14px 18px 18px;
  --cb-grid-q:color-mix(in oklab,var(--cb-grid) 60%,transparent);
  background-color:var(--cb-bg);background-image:linear-gradient(var(--cb-grid-q) 1px,transparent 1px),
  linear-gradient(90deg,var(--cb-grid-q) 1px,transparent 1px);background-size:24px 24px;scrollbar-width:thin;
  scrollbar-color:var(--cb-stroke-strong) transparent}
.cb-root .cb-insp{grid-area:insp;min-width:0;min-height:0;overflow:auto;border-left:1px solid var(--cb-stroke);padding:12px 14px;
  display:flex;flex-direction:column;gap:10px;background:var(--cb-bg);scrollbar-width:thin;scrollbar-color:var(--cb-stroke-strong) transparent}
.cb-root .cb-station{animation:cb-fadein .12s ease-out}

/* HUD */
.cb-root .cb-hud{grid-area:hud;display:flex;align-items:center;gap:6px;padding:0 12px;min-width:0;white-space:nowrap;
  border-bottom:1px solid var(--cb-stroke);background:linear-gradient(to bottom,color-mix(in oklab,var(--cb-fg) 3%,var(--cb-bg)),var(--cb-bg));
  overflow:hidden}
.cb-root .cb-brand{display:flex;align-items:baseline;gap:8px;font-weight:700;letter-spacing:.18em;font-size:14px;color:var(--cb-ok-text);
  text-shadow:var(--cb-glow-ok);flex:none}
.cb-root .cb-brand small{font-weight:400;letter-spacing:.1em;font-size:11px;color:var(--cb-fg-dim);text-shadow:none}
.cb-root .cb-sep{width:1px;height:24px;background:var(--cb-stroke-strong);flex:none}
.cb-root .cb-pill{display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 8px;border:1px solid var(--cb-stroke-strong);
  background:var(--cb-panel);border-radius:2px;white-space:nowrap;min-width:0;flex:0 0 auto;overflow:hidden}
.cb-root .cb-pill[data-cb=hud-link]{flex:0 1 auto}
.cb-root .cb-pill[data-cb=hud-project]{flex:0 1 auto;min-width:72px}
.cb-root .cb-pill b{color:var(--cb-fg);font-weight:600;overflow:hidden;text-overflow:ellipsis;min-width:0}
.cb-root button.cb-pill:hover{border-color:var(--cb-fg-faint)}
.cb-root .cb-hudsim{display:inline-flex;align-items:center;gap:6px;flex:none;min-width:0}
.cb-root .cb-hudsim .cb-simdev{color:var(--cb-fg-dim);font-weight:400}
.cb-root .cb-dot{width:7px;height:7px;border-radius:50%;flex:none;background:var(--cb-fg-faint)}
/* static */
.cb-root .cb-dot--ok{background:var(--cb-ok);box-shadow:var(--cb-glow-ok)}
.cb-root .cb-dot--active{background:var(--cb-active);box-shadow:var(--cb-glow-active)}
.cb-root .cb-dot--off{background:transparent;border:1px solid var(--cb-fg-dim)}
.cb-root .cb-dot--bad{background:var(--cb-bad);box-shadow:var(--cb-glow-bad)}
.cb-root .cb-kpis{display:flex;gap:0;margin-left:auto;flex:none}
.cb-root .cb-kpi{display:flex;flex-direction:column;gap:1px;padding:0 8px;border-left:1px solid var(--cb-stroke-strong);white-space:nowrap;flex:none}
.cb-root .cb-kpi .cb-v{display:inline-flex;align-items:baseline;font-size:12px;font-weight:400;font-variant-numeric:tabular-nums;line-height:16px;color:var(--cb-fg)}
.cb-root .cb-kpi .cb-v b{font-weight:700}
.cb-root .cb-kpi .cb-v small{font-size:10px;font-weight:400;color:var(--cb-fg-dim);margin-left:6px;text-transform:uppercase;letter-spacing:.06em}
/* key figures as words: symbol + number in the state colour, the word in fg; narrow: symbol + number only */
.cb-root .cb-kpi-i{display:inline-flex;align-items:baseline;gap:3px}
.cb-root .cb-kpi-i + .cb-kpi-i{margin-left:10px}
.cb-root .cb-kpi-i .cb-kpi-w{color:var(--cb-fg);margin-left:1px}
.cb-root .cb-kpi-i.cb-dim .cb-kpi-w{color:var(--cb-fg-dim)}
.cb-root .cb-kpi-bar{margin-left:6px;letter-spacing:-.05em}
.cb-root .cb-hud .cb-btn{flex:none}

/* buttons, segments, chips */
.cb-root .cb-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;font-size:11px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--cb-ink);background:var(--cb-ok-fill);height:28px;padding:0 12px;line-height:1;border:1px solid transparent;border-radius:2px;
  box-shadow:var(--cb-glow-ok);font-weight:700;white-space:nowrap;flex:none}
.cb-root .cb-btn:hover{background:color-mix(in oklab,var(--cb-ok-fill) 86%,white)}
.cb-root .cb-btn--ghost{background:transparent;color:var(--cb-fg);border-color:var(--cb-fg-faint);box-shadow:none}
.cb-root .cb-btn--ghost:hover{background:var(--cb-panel);border-color:var(--cb-fg-dim)}
.cb-root .cb-btn--quiet{background:transparent;color:var(--cb-fg-dim);border-color:var(--cb-stroke-strong);box-shadow:none;padding:0 10px;font-weight:600}
.cb-root .cb-btn--quiet:hover{color:var(--cb-fg);border-color:var(--cb-fg-faint);background:var(--cb-panel)}
.cb-root .cb-btn--warn{background:var(--cb-warn-fill);color:var(--cb-ink);box-shadow:var(--cb-glow-warn)}
.cb-root .cb-btn--danger{background:var(--cb-bad-fill);color:var(--cb-ink);box-shadow:var(--cb-glow-bad)}
.cb-root .cb-btn--danger:hover{background:color-mix(in oklab,var(--cb-bad-fill) 86%,white)}
.cb-root .cb-btn--sm{height:24px;padding:0 8px;font-size:10px}
.cb-root .cb-btn--lg{height:32px;padding:0 16px}
.cb-root .cb-btn:disabled{opacity:.45;box-shadow:none;filter:saturate(.4)}
.cb-root .cb-seg{display:inline-flex;border:1px solid var(--cb-stroke-strong);border-radius:2px;flex:none}
.cb-root .cb-seg button{height:26px;padding:0 10px;color:var(--cb-fg-dim);border-right:1px solid var(--cb-stroke-strong);white-space:nowrap}
.cb-root .cb-seg button:last-child{border-right:0}
.cb-root .cb-seg button:hover{color:var(--cb-fg);background:var(--cb-panel)}
.cb-root .cb-seg button[aria-pressed=true]{color:var(--cb-ink);background:var(--cb-active-fill);box-shadow:var(--cb-glow-active);font-weight:700}
.cb-root .cb-chipbtn{padding:4px 9px;border:1px solid color-mix(in oklab,var(--cb-ok) 60%,transparent);color:var(--cb-ok-text);border-radius:2px;
  font-variant-numeric:tabular-nums}
.cb-root .cb-chipbtn:hover,.cb-root .cb-chipbtn[aria-pressed=true]{background:color-mix(in oklab,var(--cb-ok) 14%,transparent);box-shadow:var(--cb-glow-ok)}
.cb-root .cb-tag{display:inline-block;padding:1px 6px;border:1px solid var(--cb-stroke-strong);color:var(--cb-fg-dim);font-size:10px;border-radius:2px;text-transform:uppercase;letter-spacing:.06em}
.cb-root .cb-stamp{display:inline-block;padding:3px 8px;font-weight:800;letter-spacing:.2em;font-size:11px;color:var(--cb-ink);
  background:var(--cb-bad-fill);box-shadow:var(--cb-glow-bad);border-radius:1px;white-space:nowrap}
.cb-root .cb-stamp--warn{background:var(--cb-warn-fill);box-shadow:var(--cb-glow-warn)}
.cb-root .cb-stamp--ok{background:var(--cb-ok-fill);box-shadow:var(--cb-glow-ok)}
.cb-root .cb-stamp--none{background:transparent;color:var(--cb-fg-dim);border:1px solid var(--cb-stroke-strong);box-shadow:none}
.cb-root .cb-stamp--active{background:var(--cb-active-fill);box-shadow:var(--cb-glow-active)}

/* corner brackets */
.cb-root .cb-bracket{position:relative}
.cb-root .cb-bracket::before,.cb-root .cb-bracket::after{content:"";position:absolute;width:10px;height:10px;border-color:var(--cb-ok);opacity:.45;pointer-events:none}
.cb-root .cb-bracket::before{top:-1px;left:-1px;border-top:1px solid;border-left:1px solid}
.cb-root .cb-bracket::after{bottom:-1px;right:-1px;border-bottom:1px solid;border-right:1px solid}
.cb-root .cb-bracket--bad::before,.cb-root .cb-bracket--bad::after{border-color:var(--cb-bad)}

/* rail */
.cb-root .cb-rail{grid-area:rail;border-right:1px solid var(--cb-stroke);padding:14px 10px 12px;display:flex;flex-direction:column;
  gap:0;background:var(--cb-bg);min-height:0;overflow:auto;scrollbar-width:none}
.cb-root .cb-rail-label{margin:0 0 10px 8px}
.cb-root .cb-stage{display:grid;grid-template-columns:16px minmax(0,1fr) auto;align-items:center;gap:8px 6px;padding:6px 8px;min-height:40px;
  border:1px solid transparent;color:var(--cb-fg-dim);border-radius:1px;width:100%;position:relative}
.cb-root .cb-stage:hover{background:var(--cb-panel);color:var(--cb-fg)}
.cb-root .cb-stage-ic{width:16px;height:16px;flex:none;overflow:visible;color:var(--cb-fg-dim)}
.cb-root .cb-stage-txt{display:flex;flex-direction:column;gap:1px;min-width:0}
.cb-root .cb-stage-l1{display:flex;align-items:baseline;gap:6px;min-width:0}
.cb-root .cb-stage .cb-n{color:var(--cb-fg-dim);font-size:10px;font-variant-numeric:tabular-nums;flex:none}
.cb-root .cb-stage .cb-t{letter-spacing:.12em;text-transform:uppercase;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--cb-fg)}
.cb-root .cb-stage .cb-sw{font-size:10px;letter-spacing:.04em;color:var(--cb-fg-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cb-root .cb-stage .cb-s{font-size:11px;font-variant-numeric:tabular-nums;white-space:nowrap;display:inline-flex;align-items:center;gap:3px}
.cb-root .cb-stage .cb-s-g{flex:none;overflow:visible}
.cb-root .cb-stage .cb-s[data-cb-mark=panic]{font-weight:700;letter-spacing:.08em}
/* current station: panel surface, frame and a short green edge (identity accent), no green fill or glow (L8) */
.cb-root .cb-stage[aria-current=page]{border-color:var(--cb-stroke-strong);color:var(--cb-fg);background:var(--cb-panel);box-shadow:inset 2px 0 0 var(--cb-ok)}
.cb-root .cb-stage[aria-current=page] .cb-t{font-weight:700}
.cb-root .cb-stage[aria-current=page] .cb-stage-ic{color:var(--cb-fg)}
.cb-root .cb-stage[data-cb-tone=bad] .cb-stage-ic{color:var(--cb-bad-text)}
.cb-root .cb-stage[data-cb-alert=true] .cb-s{color:var(--cb-bad-text);text-shadow:var(--cb-glow-bad)}
/* Wow 4: the fix loop closed — each station lights up once, top to bottom */
.cb-root .cb-rail[data-cb-sweep=on] .cb-stage{animation:cb-sweep .9s ease-out both;animation-delay:calc(var(--cb-i,0) * 140ms)}
.cb-root .cb-trace{margin:0 0 0 16px;width:2px;flex:0 0 6px;background:var(--cb-stroke-strong)}
.cb-root .cb-trace[data-cb-done=true]{background:color-mix(in oklab,var(--cb-ok) 55%,var(--cb-stroke-strong))}
.cb-root .cb-rail-foot{margin-top:auto;border-top:1px solid var(--cb-stroke);padding:12px 6px 0;display:grid;gap:6px;color:var(--cb-fg-dim);font-size:11px}
.cb-root .cb-rail-foot div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* station title + toolbar */
.cb-root .cb-title{display:flex;align-items:baseline;gap:12px;min-width:0;flex-wrap:wrap;row-gap:4px}
.cb-root .cb-title h1{margin:0;font-size:18px;letter-spacing:.24em;font-weight:700;color:var(--cb-fg);
  display:inline-flex;align-items:baseline;white-space:nowrap;line-height:1.2}
.cb-root .cb-title h1 .cb-decode{font-size:18px;letter-spacing:.24em;font-weight:700;color:inherit;font-family:var(--cb-mono)}
.cb-root .cb-cursor{display:inline-block;width:9px;height:15px;background:var(--cb-ok);margin-left:6px;transform:translateY(2px);
  box-shadow:var(--cb-glow-ok);animation:cb-blink 1s steps(2) 3}
.cb-root .cb-toolbar{display:flex;gap:8px;margin:10px 0 8px;align-items:center;flex-wrap:wrap;row-gap:8px}
.cb-root .cb-toolbar .cb-push{margin-left:auto}
.cb-root .cb-group{display:inline-flex;align-items:center;gap:8px;padding-right:10px;border-right:1px solid var(--cb-stroke)}
.cb-root .cb-group > .cb-label{flex:none}
.cb-root .cb-switch{display:inline-flex;align-items:center;gap:7px;padding:5px 9px;border:1px solid var(--cb-stroke-strong);
  color:var(--cb-fg-dim);border-radius:2px;white-space:nowrap}
.cb-root .cb-switch[aria-checked=true]{color:var(--cb-active-text);border-color:color-mix(in oklab,var(--cb-active) 55%,transparent)}
.cb-root .cb-switch i{width:22px;height:10px;border:1px solid currentColor;border-radius:6px;position:relative;display:inline-block}
.cb-root .cb-switch i::after{content:"";position:absolute;top:1px;left:1px;width:6px;height:6px;border-radius:50%;background:currentColor}
.cb-root .cb-switch[aria-checked=true] i::after{left:13px}
.cb-root .cb-whatif{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  border:1px dashed color-mix(in oklab,var(--cb-active) 55%,transparent);color:var(--cb-active-text);background:color-mix(in oklab,var(--cb-active) 6%,transparent)}
.cb-root .cb-note{display:flex;align-items:center;gap:10px;margin:0 0 12px;padding:7px 10px;border:1px solid var(--cb-stroke-strong);
  background:var(--cb-panel);color:var(--cb-fg)}
.cb-root .cb-note--warn{border-color:color-mix(in oklab,var(--cb-warn) 50%,transparent);color:var(--cb-warn-text)}
.cb-root .cb-note--bad{border-color:color-mix(in oklab,var(--cb-bad) 55%,transparent);color:var(--cb-bad-text)}
.cb-root .cb-note .cb-x{margin-left:auto;color:var(--cb-fg-dim)}

/* inspector + cards + tables */
.cb-root .cb-card{border:1px solid var(--cb-stroke-strong);background:var(--cb-panel);padding:11px 12px;min-width:0}
.cb-root .cb-card-head{display:flex;align-items:center;gap:8px;min-width:0;min-height:24px}
.cb-root .cb-card-head .cb-label:last-child,.cb-root .cb-card-head .cb-push{margin-left:auto}
.cb-root .cb-verdict{display:flex;align-items:center;gap:10px;margin-top:8px;flex-wrap:wrap}
.cb-root .cb-verdict .cb-big{font-size:22px;font-weight:800;letter-spacing:.08em;font-variant-numeric:tabular-nums}
.cb-root .cb-why{margin:8px 0 0;line-height:1.55;color:var(--cb-fg)}
.cb-root .cb-nowrap{white-space:nowrap}
.cb-root .cb-why b{color:var(--cb-fg);font-weight:700}
.cb-root .cb-why em{color:var(--cb-warn-text);font-style:normal}
.cb-root .cb-fn{display:flex;flex-wrap:wrap;gap:5px;margin-top:9px}
.cb-root .cb-src{margin-top:9px;display:flex;align-items:baseline;gap:8px;color:var(--cb-active-text);font-size:11px;min-width:0}
.cb-root .cb-src .cb-k{color:var(--cb-fg-dim);flex:none}
.cb-root .cb-src button{color:var(--cb-active-text);text-align:left;min-width:0;line-height:1.45}
.cb-root .cb-src button:hover{text-decoration:underline}
.cb-root .cb-alts{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
.cb-root .cb-actions{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.cb-root .cb-modes-sum{display:flex;gap:10px;align-items:baseline;margin-top:8px;font-size:11px}
.cb-root .cb-modes-sum .cb-label{flex:none}
.cb-root table.cb-table{width:100%;border-collapse:collapse;margin-top:6px}
.cb-root .cb-table td,.cb-root .cb-table th{padding:4px 4px;border-bottom:1px dashed var(--cb-stroke-strong);text-align:left;white-space:nowrap}
.cb-root .cb-table th{font-weight:400}
.cb-root .cb-table td.cb-r,.cb-root .cb-table th.cb-r{text-align:right}
.cb-root .cb-table tr[data-cb-row]{cursor:pointer}
.cb-root .cb-table tr[data-cb-row]:hover td{background:color-mix(in oklab,var(--cb-fg) 5%,transparent)}
.cb-root .cb-table tr[data-cb-pulse=true] td{animation:cb-rowpulse .6s ease-in-out 2}
.cb-root .cb-table .cb-x{color:var(--cb-fg-faint);padding:0 4px}
.cb-root .cb-table .cb-x:hover{color:var(--cb-bad-text)}
.cb-root .cb-hint{color:var(--cb-warn-text);margin-top:10px;line-height:1.5}

/* console + panic card (pane) / panic strip (page) */
.cb-root .cb-cons{grid-area:cons;border-top:1px solid var(--cb-stroke-strong);display:grid;grid-template-columns:minmax(0,1fr) auto;
  background:var(--cb-cons-bg);min-height:0;min-width:0}
.cb-root .cb-cons--page{display:flex;flex-direction:column}
.cb-root .cb-cons--page > .cb-console{flex:1 1 auto}
.cb-root .cb-panicstrip{flex:none;display:flex;align-items:center;gap:12px;min-width:0;height:30px;padding:0 8px 0 12px;
  border-bottom:1px solid var(--cb-stroke);box-shadow:inset 3px 0 0 var(--cb-bad);background:color-mix(in oklab,var(--cb-bad) 7%,transparent)}
.cb-root .cb-panicstrip-mark{flex:none;font-weight:800;font-size:11px;letter-spacing:.16em;color:var(--cb-bad-text)}
.cb-root .cb-panicstrip-t{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--cb-fg)}
.cb-root .cb-panicstrip-at{color:var(--cb-fg-dim)}
.cb-root .cb-panicstrip .cb-panic-actions{flex:none;margin:0}
.cb-root .cb-console{display:flex;flex-direction:column;min-height:0;min-width:0;container:cbcons/inline-size}
.cb-root .cb-tabs{display:flex;align-items:stretch;border-bottom:1px solid var(--cb-stroke);min-width:0;flex:none;height:33px}
.cb-root .cb-tabs [role=tab]{flex:none;padding:0 14px;color:var(--cb-fg-dim);letter-spacing:.14em;font-size:10px;border-right:1px solid var(--cb-stroke);
  display:inline-flex;align-items:center;gap:6px;text-transform:uppercase}
.cb-root .cb-tabs [role=tab]:hover{color:var(--cb-fg)}
.cb-root .cb-tabs [role=tab][aria-selected=true]{color:var(--cb-fg);background:var(--cb-panel);box-shadow:inset 0 -2px 0 var(--cb-ok)}
/* the bar never runs over the tabs: overflow is cut at the meta's own edge (safe end alignment), the port line shrinks
   first, narrow consoles drop the sim chip (the HUD shows it) and shorten the buttons */
.cb-root .cb-tabs .cb-meta{flex:1 1 auto;display:flex;align-items:center;justify-content:safe flex-end;gap:8px;padding:0 8px 0 12px;min-width:0;
  white-space:nowrap;overflow:hidden}
.cb-root .cb-tabs .cb-meta > .cb-consmeta{min-width:0}
/* the SIM badge never gives way (SIMULATED visible wherever a Bench surface is); only its word BOARD */
@container cbcons (max-width:760px){.cb-root .cb-tabs .cb-meta > .cb-simban .cb-simban-w{display:none}.cb-root .cb-tabs [role=tab]{padding:0 10px}
  .cb-root .cb-tabs .cb-meta > .cb-consmeta{display:none}}
@container cbcons (max-width:600px){.cb-root .cb-cmd-long{display:none}}
.cb-root .cb-tabs .cb-meta > .cb-label{overflow:hidden;text-overflow:ellipsis;min-width:0}
.cb-root .cb-tabs .cb-meta > button{flex:none}
/* tools never give way to the meta */
.cb-root .cb-cons-tools{flex:none;display:flex;align-items:center;gap:8px;padding:0 8px 0 0}
.cb-root .cb-iconbtn{display:inline-flex;align-items:center;justify-content:center;height:24px;color:var(--cb-fg-dim);padding:0 8px;border:1px solid var(--cb-stroke);
  border-radius:2px;font-size:11px;white-space:nowrap;line-height:1}
.cb-root .cb-iconbtn:hover{color:var(--cb-fg);border-color:var(--cb-stroke-strong)}
.cb-root .cb-log-inner{min-height:100%}
.cb-root .cb-log{flex:1 1 auto;min-height:0;overflow:auto;padding:7px 14px 10px;line-height:1.6;font-size:11.5px;color:var(--cb-fg-dim);
  scrollbar-width:thin;scrollbar-color:var(--cb-stroke-strong) transparent;position:relative}
.cb-root .cb-line{display:grid;grid-template-columns:12.5ch minmax(0,1fr);column-gap:8px;min-height:1.6em}
.cb-root .cb-line--blank{min-height:.8em}.cb-root .cb-line--blank .cb-ts{visibility:hidden}
.cb-root .cb-line > span:last-child{white-space:pre-wrap;overflow-wrap:anywhere}
.cb-root .cb-line .cb-ts{color:var(--cb-fg-dim);opacity:.8;font-variant-numeric:tabular-nums}
.cb-root .cb-line--hl{color:var(--cb-fg)}
.cb-root .cb-line--rom{color:var(--cb-fg-dim)}
.cb-root .cb-line--panic{color:var(--cb-bad-text);font-weight:700}
.cb-root .cb-panicblk{position:relative;margin:2px 0 2px -10px;padding:0 0 0 8px;border-left:2px solid var(--cb-bad);
  background:linear-gradient(to right,color-mix(in oklab,var(--cb-bad) 7%,transparent),transparent 70%);overflow-x:auto;scrollbar-width:thin}
/* dump lines never break inside a value */
.cb-root .cb-panicblk .cb-line + .cb-line > span:last-child{white-space:pre;overflow-wrap:normal}
@container cbcons (max-width:820px){.cb-root .cb-panicblk .cb-line + .cb-line{grid-template-columns:minmax(0,1fr)}
  .cb-root .cb-panicblk .cb-line + .cb-line .cb-ts{display:none}}
/* outside 06 DEBUG the strip is the only alarm */
.cb-root.cb-page:not([data-cb-station=debug]) .cb-cons--page .cb-panicblk{background:none}
.cb-root.cb-page:not([data-cb-station=debug]) .cb-cons--page .cb-line--panic{color:var(--cb-fg)}
.cb-root.cb-page:not([data-cb-station=debug]) .cb-cons--page .cb-line--bt{color:var(--cb-fg-dim)}
.cb-root .cb-panicblk:not(.cb-panicblk--live){border-left-style:dashed}
.cb-root .cb-pjump{flex:none;color:var(--cb-fg-dim)}
.cb-root .cb-pjump--live{color:var(--cb-bad-text);border-color:var(--cb-bad)}
.cb-root .cb-cons-idle{flex:1 1 auto;display:inline-flex;align-items:baseline;gap:8px;min-width:0;color:var(--cb-fg-dim);font-size:11px}
.cb-root .cb-cons-idle .cb-linkbtn,.cb-root .cb-cons-empty .cb-linkbtn{flex:none}
.cb-root .cb-line--bt{color:color-mix(in oklab,var(--cb-bad) 72%,var(--cb-fg))}
.cb-root .cb-line--gap,.cb-root .cb-line--epoch{color:var(--cb-warn-text);font-style:normal}
.cb-root .cb-cons-empty{padding:16px 14px;color:var(--cb-fg-dim);display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.cb-root .cb-panic{width:440px;border-left:1px solid var(--cb-stroke-strong);padding:10px 14px;display:flex;flex-direction:column;gap:7px;
  background:linear-gradient(to right,color-mix(in oklab,var(--cb-bad) 9%,transparent),transparent 60%);min-height:0;overflow:hidden;min-width:0}
.cb-root .cb-panic > *{flex:none}
.cb-root .cb-panic > .cb-frames{flex:0 1 auto;min-height:0;overflow:hidden}
.cb-root .cb-panic-hint{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}
.cb-root .cb-panic-actions{margin-top:auto}
.cb-root .cb-alarm{display:flex;align-items:center;gap:10px;min-width:0;flex-wrap:wrap;row-gap:4px}
/* one pulse */
.cb-root .cb-alarm .cb-stamp{animation:cb-pulse .6s ease-in-out 1}
.cb-root .cb-alarm .cb-label:last-child,.cb-root .cb-alarm .cb-elf{margin-left:auto}
.cb-root .cb-elf{font-size:11px;letter-spacing:.1em;text-transform:uppercase;white-space:nowrap}
.cb-root .cb-elf--ok{color:var(--cb-ok-text)}.cb-root .cb-elf--bad{color:var(--cb-bad-text)}.cb-root .cb-elf--faint{color:var(--cb-fg-dim)}
.cb-root .cb-frames{display:grid;gap:4px}
.cb-root .cb-frame{display:grid;grid-template-columns:22px minmax(0,1fr) auto;gap:8px;padding:4px 8px;font-size:11px;border:1px solid var(--cb-stroke);background:var(--cb-panel);min-width:0}
.cb-root .cb-frame .cb-i{color:var(--cb-fg-dim)}
.cb-root .cb-frame .cb-f{color:var(--cb-fg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.cb-root .cb-frame .cb-l{color:var(--cb-active-text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:120px}
.cb-root .cb-panic .cb-hint{line-height:1.4}
.cb-root .cb-frame--top{border-color:color-mix(in oklab,var(--cb-bad) 60%,transparent)}
.cb-root .cb-frame--top .cb-f{color:var(--cb-bad-text)}
.cb-root .cb-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}

/* notices as toasts (no layout shift) */
.cb-root .cb-toasts{position:absolute;top:12px;right:18px;z-index:6;display:grid;gap:6px;max-width:min(440px,72%);pointer-events:none}
.cb-root .cb-toasts .cb-note{margin:0;pointer-events:auto;box-shadow:0 8px 24px rgba(0,0,0,.45)}

/* empty / error / loading */
.cb-root .cb-empty{max-width:560px;margin:40px auto 0;padding:24px;border:1px solid var(--cb-stroke-strong);background:var(--cb-panel)}
.cb-root .cb-empty h2{display:flex;align-items:baseline;gap:8px;margin:8px 0;font-size:15px;letter-spacing:.14em;text-transform:uppercase;color:var(--cb-fg)}
.cb-root .cb-empty .cb-actions{margin-top:16px}
.cb-root .cb-empty-mark{flex:none}
.cb-root .cb-empty p{margin:0 0 6px;color:var(--cb-fg-dim);line-height:1.6}
.cb-root .cb-empty code{color:var(--cb-active-text)}
.cb-root .cb-empty--bad h2{color:var(--cb-bad-text)}
.cb-root .cb-empty--warn h2{color:var(--cb-warn-text)}
.cb-root .cb-loading{padding:40px;color:var(--cb-fg-dim);letter-spacing:.14em;text-transform:uppercase;font-size:11px}
.cb-root .cb-loading::after{content:"▌";margin-left:4px;color:var(--cb-ok-text);animation:cb-blink 1s steps(2) infinite}

/* modal (own DOM, inside the page root) */
.cb-root .cb-modal-back{position:absolute;inset:0;z-index:60;background:color-mix(in oklab,black 78%,transparent);backdrop-filter:blur(1.5px);display:flex;align-items:center;justify-content:center;padding:20px}
.cb-root .cb-modal{width:min(440px,100%);border:1px solid var(--cb-stroke-strong);background:var(--cb-panel);padding:16px 18px;
  box-shadow:0 20px 60px rgba(0,0,0,.6)}
.cb-root .cb-modal h2{margin:4px 0 12px;font-size:14px;letter-spacing:.16em;text-transform:uppercase;color:var(--cb-fg)}
.cb-root .cb-form{display:grid;grid-template-columns:72px minmax(0,1fr);gap:9px 12px;align-items:center}
.cb-root .cb-form label{color:var(--cb-fg-dim);font-size:10px;letter-spacing:.14em;text-transform:uppercase}
.cb-root .cb-form .cb-err{grid-column:2;color:var(--cb-bad-text);font-size:11px;margin-top:-4px}
.cb-root .cb-modal-foot{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}
.cb-root .cb-modal .cb-preview{margin-top:12px;padding:8px 10px;border:1px dashed var(--cb-stroke-strong);color:var(--cb-fg-dim);line-height:1.5}

/* placeholders */
.cb-root .cb-soon{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px;margin-top:8px}
.cb-root .cb-soon .cb-card{color:var(--cb-fg-dim);line-height:1.6}
.cb-root .cb-soon .cb-card b{color:var(--cb-fg);display:block;margin:0 0 4px;letter-spacing:.06em}
.cb-root .cb-soon .cb-card b.cb-ok{color:var(--cb-ok-text)}

/* serial pane */
.cb-root.cb-pane{position:relative;height:100%;width:100%;display:flex;flex-direction:column;background:var(--cb-cons-bg);
  overflow:hidden;container:cbpane/inline-size}
.cb-root.cb-pane .cb-cons{border-top:0;flex:1 1 auto;display:grid}

/* status bar chip (app theme colours, the status bar is app chrome) */
.cb-root.cb-chip{display:inline-flex;align-items:center;gap:6px;height:100%;padding:0 8px;font-size:11px;letter-spacing:.06em;
  color:var(--cb-fg-dim);white-space:nowrap;border-radius:3px}
.cb-root.cb-chip:hover{color:var(--cb-fg);background:color-mix(in oklab,var(--cb-fg) 8%,transparent)}
.cb-root.cb-chip b{font-weight:600;color:var(--cb-fg)}
.cb-root.cb-chip .cb-g{font-weight:700}

/* narrow containers */
@container cb (max-width:1240px){.cb-root .cb-shell{--cb-rail-w:172px;--cb-insp-w:300px}
  .cb-root .cb-kpi .cb-v small,.cb-root [data-cb=hud-board] .cb-label,.cb-root [data-cb=hud-project] .cb-label,.cb-root .cb-kpi-bar,.cb-root .cb-hud .cb-simban-w{display:none}
  .cb-root .cb-brand{font-size:13px;letter-spacing:.14em}}
@container cb (max-width:1180px){.cb-root .cb-brand small{display:none}}
/* low windows (1100×800): denser pin rows and toolbar while the console is open; 06 DEBUG console a little lower */
@container cb (max-height:800px){
  .cb-root .cb-shell[data-cb-cons=open] .cb-toolbar{margin:6px 0 4px;row-gap:6px}
  .cb-root[data-cb-station=debug] .cb-shell[data-cb-cons=open]{--cb-cons-h:230px}
}
/* 1100×800 and smaller: PLAN keeps J1-22/J3-22 above the open console; the log still shows 6 lines */
@container cb (max-height:760px){.cb-root[data-cb-station=plan] .cb-shell[data-cb-cons=open]{--cb-cons-h:150px}}
/* < 1100 px icon rail, inspector beside; stacked only < 800 px */
@container cb (max-width:1099px){
  .cb-root .cb-shell{--cb-rail-w:58px;--cb-insp-w:280px}
  .cb-root .cb-rail{padding:12px 6px}
  .cb-root .cb-stage{grid-template-columns:1fr;justify-items:center;padding:7px 2px;gap:2px}
  .cb-root .cb-stage-txt,.cb-root .cb-rail-label,.cb-root .cb-rail-foot{display:none}.cb-root .cb-stage-ic{display:block}
  .cb-root .cb-trace{margin-left:auto;margin-right:auto}
  .cb-root .cb-hud [data-cb=hud-board]{display:none}
  .cb-root .cb-kpi-w{display:none}.cb-root .cb-kpi-i + .cb-kpi-i{margin-left:8px}
}
@container cb (max-width:899px){.cb-root .cb-shell{--cb-insp-w:256px}.cb-root .cb-main{padding:12px 12px 16px}
  .cb-root .cb-insp{padding:10px 10px}}
@container cb (max-width:799px){
  .cb-root .cb-shell{grid-template-columns:var(--cb-rail-w) minmax(0,1fr);grid-template-areas:"hud hud" "rail main" "rail cons"}
  .cb-root .cb-work{display:block;grid-area:main;min-height:0;overflow:auto;position:relative;background-color:var(--cb-bg);
    --cb-grid-q:color-mix(in oklab,var(--cb-grid) 60%,transparent);
    background-image:linear-gradient(var(--cb-grid-q) 1px,transparent 1px),linear-gradient(90deg,var(--cb-grid-q) 1px,transparent 1px);background-size:24px 24px}
  .cb-root .cb-work .cb-main{overflow:visible;background:none}
  .cb-root .cb-work .cb-main--fill{height:100%;min-height:380px}
  .cb-root .cb-work .cb-insp{overflow:visible;border-left:0;border-top:1px solid var(--cb-stroke);display:grid;
    grid-template-columns:repeat(auto-fit,minmax(300px,1fr));align-items:start;background:transparent;padding:14px 18px 18px}
}
@container cb (max-width:960px){.cb-root .cb-kpi[data-cb=kpi-build],.cb-root .cb-kpi[data-cb=kpi-solder]{display:none}
  .cb-root .cb-pill[data-cb=hud-link] b{max-width:150px;text-overflow:ellipsis}}
@container cb (max-width:820px){.cb-root [data-cb=hud-project] .cb-label{display:none}}
@container cb (max-width:700px){
  .cb-root .cb-kpis,.cb-root .cb-brand small,.cb-root .cb-sep,.cb-root [data-cb=hud-link] b{display:none}
  .cb-root .cb-main{padding:12px 12px 16px}
}
@container cbpane (max-width:760px){.cb-root .cb-panic{width:300px}}
@container cbpane (max-width:560px){.cb-root .cb-panic{display:none}}

/* motion */
@keyframes cb-pulse{0%,100%{opacity:1}50%{opacity:.45}}
@keyframes cb-blink{50%{opacity:.35}}
@keyframes cb-fadein{from{opacity:0}to{opacity:1}}
@keyframes cb-sweep{0%,100%{box-shadow:none}30%,45%{background:color-mix(in oklab,var(--cb-ok) 24%,transparent);border-color:var(--cb-ok);
  box-shadow:inset 3px 0 0 var(--cb-ok),var(--cb-glow-ok)}}
@keyframes cb-rowpulse{0%,100%{background:transparent}50%{background:color-mix(in oklab,var(--cb-active) 22%,transparent)}}
@media (prefers-reduced-motion:reduce){
  .cb-root *,.cb-root *::before,.cb-root *::after{animation:none!important;transition:none!important}
  .cb-root.cb-page::after,.cb-root.cb-pane::after{display:none}
}
` + CB_CSS_UI2

/** The own stylesheet: base CSS + the registered parts of 13-…–19-styles-*.js (CB_CSS_PARTS, 10-tokens.js), joined at
 *  render time so every part file has run. */
function Styles() {
  return h('style', { 'data-cb': 'style' }, CB_CSS + CB_CSS_PARTS.join(''))
}
