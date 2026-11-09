// Board model styles: the DOM layer above the SVG drawing. Every
// measure comes from the CSS variables boardGeomVars() sets on [data-cb=board] (lib/board-geom.js); labels and tags
// sit in fixed columns outside the pcb and use the bench colours, everything printed on the pcb uses the material.
CB_CSS_PARTS.push(`
/* box: exactly the geometry, centred in the main column; no frame (the pcb is the object) */
.cb-root .cb-board-wrap{display:flex;justify-content:center;padding:0;min-width:0;margin:2px 0 0}
.cb-root .cb-board.cb-board[data-cb=board]{position:relative;display:block;flex:none;width:var(--cb-board-w);height:var(--cb-board-h);max-width:none;
  padding:0;margin:0;border:0;background:none}
.cb-root .cb-board-art{position:absolute;inset:0;pointer-events:none}
.cb-root .cb-board-art svg{display:block;overflow:visible}
.cb-root .cb-board-art text{font-family:var(--cb-mono)}

/* header ids printed on the pcb above the strips */
.cb-root .cb-board > .cb-board-hdr{position:absolute;top:1px;width:44px;margin-left:-22px;padding:0;text-align:center;font-size:10px;
  line-height:14px;letter-spacing:.14em;color:var(--cb-silk);font-weight:700;pointer-events:auto}
.cb-root .cb-board > .cb-board-hdr:nth-child(2){left:calc(var(--cb-gutter) + var(--cb-strip-x))}
.cb-root .cb-board > .cb-board-hdr:nth-child(3){left:calc(var(--cb-gutter) + var(--cb-body-w) - var(--cb-strip-x))}

/* pin columns: one row per slot, pitch = row + gap; the row ends with the pad cell over the strip */
.cb-root .cb-board .cb-col{position:absolute;top:var(--cb-top);width:var(--cb-row-w);display:flex;flex-direction:column;gap:var(--cb-row-gap);padding:0;min-width:0}
.cb-root .cb-board .cb-col--l{left:0}
.cb-root .cb-board .cb-col--r{right:0}
.cb-root .cb-board .cb-pin{display:flex;align-items:center;height:var(--cb-row-h);width:100%;padding:0;margin:0;border:0;border-radius:2px;
  background:none;color:inherit;font:inherit;text-align:inherit;position:relative;column-gap:0;cursor:default}
.cb-root .cb-board button.cb-pin{cursor:pointer}
.cb-root .cb-board .cb-col--l .cb-pin{justify-content:flex-end;padding-left:2px}
.cb-root .cb-board .cb-col--r .cb-pin{justify-content:flex-start;padding-right:2px}
.cb-root .cb-board .cb-pin .cb-name{flex:none;width:var(--cb-name-w);font-size:12px;font-weight:600;line-height:var(--cb-row-h);white-space:nowrap;overflow:hidden;
  color:var(--cb-fg-dim);font-variant-numeric:tabular-nums}
.cb-root .cb-board .cb-col--l .cb-name{text-align:right}
.cb-root .cb-board .cb-col--r .cb-name{text-align:left;margin-left:5px}
.cb-root .cb-board .cb-pglyph{flex:none;width:12px;height:12px}
.cb-root .cb-board .cb-col--l .cb-pglyph{margin-left:5px}
.cb-root .cb-board .cb-pin .cb-pad{flex:none;width:12px;height:12px;border:0;border-radius:50%;background:none;box-shadow:none;transform:none}
.cb-root .cb-board .cb-col--l .cb-pad{margin:0 1px 0 13px}
.cb-root .cb-board .cb-col--r .cb-pad{margin:0 13px 0 1px}
.cb-root .cb-board .cb-pin .cb-ptag{flex:0 1 auto;min-width:0;max-width:var(--cb-tag-w);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-size:10px;line-height:13px;letter-spacing:.04em;text-transform:uppercase;padding:0 5px;border:1px solid transparent;border-radius:2px;color:var(--cb-fg-dim)}
.cb-root .cb-board .cb-col--l .cb-ptag{margin-right:6px}
.cb-root .cb-board .cb-col--r .cb-ptag{margin-left:6px}
.cb-root .cb-board .cb-ptag:empty{padding:0;border:0;margin:0}
/* selection caret in the name gap */
.cb-root .cb-board .cb-mark{flex:none;width:0;height:8px;position:relative;color:var(--cb-active-text)}
.cb-root .cb-board .cb-mark::after{content:"";position:absolute;top:0;width:0;height:0;border-top:4px solid transparent;border-bottom:4px solid transparent}
.cb-root .cb-board .cb-col--l .cb-mark::after{left:0;border-left:4px solid currentColor}
.cb-root .cb-board .cb-col--r .cb-mark::after{right:0;border-right:4px solid currentColor}
.cb-root .cb-board .cb-pin[data-cb-state$=bad] .cb-mark,.cb-root .cb-board .cb-mark[data-cb-mark=req]{color:var(--cb-bad-text)}

/* states on the labels (the pad ring is in the SVG): free/assigned/caution/blocked/power/neutral */
.cb-root .cb-board .cb-pin[data-cb-state=free] .cb-name{color:var(--cb-fg)}
.cb-root .cb-board .cb-pin[data-cb-state=used] .cb-name{color:var(--cb-active-text)}
.cb-root .cb-board .cb-pin[data-cb-state=used] .cb-ptag{color:var(--cb-ink);background:var(--cb-active-fill);border-color:var(--cb-active-fill);font-weight:700}
.cb-root .cb-board .cb-pin[data-cb-state=used-warn] .cb-name{color:var(--cb-warn-text)}
.cb-root .cb-board .cb-pin[data-cb-state=used-warn] .cb-ptag{color:var(--cb-ink);background:var(--cb-warn-fill);border-color:var(--cb-warn-fill);font-weight:700}
.cb-root .cb-board .cb-pin[data-cb-state=warn] .cb-name{color:var(--cb-warn-text)}
.cb-root .cb-board .cb-pin[data-cb-state=warn] .cb-ptag{color:var(--cb-warn-text);border-color:color-mix(in oklab,var(--cb-warn) 60%,transparent)}
.cb-root .cb-board .cb-pin[data-cb-state=bad] .cb-name,.cb-root .cb-board .cb-pin[data-cb-state=used-bad] .cb-name{color:var(--cb-bad-text);text-decoration:line-through;
  text-decoration-thickness:1px}
.cb-root .cb-board .cb-pin[data-cb-state=bad] .cb-ptag{color:var(--cb-bad-text);border-color:color-mix(in oklab,var(--cb-bad) 60%,transparent)}
.cb-root .cb-board .cb-pin[data-cb-state=used-bad] .cb-ptag{color:var(--cb-ink);background:var(--cb-bad-fill);border-color:var(--cb-bad-fill);font-weight:700}
.cb-root .cb-board .cb-pin[data-cb-state=power] .cb-name{color:var(--cb-power-text)}
.cb-root .cb-board .cb-pin[data-cb-state=ground] .cb-name,.cb-root .cb-board .cb-pin[data-cb-state=reset] .cb-name,
.cb-root .cb-board .cb-pin[data-cb-state=nc] .cb-name,.cb-root .cb-board .cb-pin[data-cb-state=unchecked] .cb-name{color:var(--cb-fg-dim);font-weight:400}
.cb-root .cb-board .cb-pin[data-cb-state=signal] .cb-name{color:var(--cb-fg-dim)}
.cb-root .cb-board .cb-pin[data-cb-state=nc] .cb-ptag,.cb-root .cb-board .cb-pin[data-cb-state=signal] .cb-ptag{border:1px dashed var(--cb-stroke-strong);color:var(--cb-fg-dim)}

/* interaction: hover, focus ring, selection (row tint + the SVG ring), suggestion, agent pulse (opacity only) */
.cb-root .cb-board button.cb-pin:hover{background:color-mix(in oklab,var(--cb-fg) 7%,transparent)}
.cb-root .cb-board button.cb-pin:focus-visible{outline:2px solid var(--cb-active);outline-offset:1px}
.cb-root .cb-board .cb-pin[aria-pressed=true]{background:color-mix(in oklab,var(--cb-active) 11%,transparent);outline:1px solid color-mix(in oklab,var(--cb-active) 70%,transparent);
  outline-offset:0;box-shadow:none}
.cb-root .cb-board .cb-pin[aria-pressed=true][data-cb-state$=bad]{background:color-mix(in oklab,var(--cb-bad) 12%,transparent);outline-color:color-mix(in oklab,var(--cb-bad) 75%,transparent)}
.cb-root .cb-board .cb-pin[data-cb-suggest=true]{outline:1px dashed var(--cb-ok);outline-offset:0}
.cb-root .cb-board .cb-pin[data-cb-pulse=true]{animation:none}
.cb-root .cb-board .cb-pin[data-cb-pulse=true]::after{content:"";position:absolute;inset:0;border-radius:2px;pointer-events:none;
  background:color-mix(in oklab,var(--cb-active) 28%,transparent);opacity:0;animation:cb-bpulse .3s ease-in-out 2}
@keyframes cb-bpulse{50%{opacity:1}}
/* the selection ring on the pad: the one permanently animated element, static under reduced motion */
.cb-root .cb-board-art .cb-bsel{transform-box:fill-box;transform-origin:center;animation:cb-bselring 1.6s ease-in-out infinite}
@keyframes cb-bselring{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.45;transform:scale(1.18)}}

/* header separator (WT32: PROG → IO): the id printed at the strip, a dashed rule across the label columns */
.cb-root .cb-board .cb-col .cb-hdr-sep{height:var(--cb-row-h);display:block;position:relative;padding:0;gap:0}
.cb-root .cb-board .cb-col .cb-hdr-sep::before{content:"";position:absolute;top:50%;border-top:1px dashed var(--cb-stroke-strong);flex:none}
.cb-root .cb-board .cb-col .cb-hdr-sep::after{content:none}
.cb-root .cb-board .cb-col--l .cb-hdr-sep::before{left:2px;right:30px}
.cb-root .cb-board .cb-col--r .cb-hdr-sep::before{left:30px;right:2px}
.cb-root .cb-board .cb-hdr-sep > span{position:absolute;top:0;transform:translateX(-50%);font-size:10px;line-height:var(--cb-row-h);letter-spacing:.12em;font-weight:700;color:var(--cb-silk)}
.cb-root .cb-board .cb-col--l .cb-hdr-sep > span{left:calc(100% - 7px)}
.cb-root .cb-board .cb-col--r .cb-hdr-sep > span{left:7px}

/* reservation brackets: transparent anchors in the lane (drawing in the SVG), title = the full text */
.cb-root .cb-board .cb-bbracket{position:absolute;width:15px;pointer-events:auto;cursor:help}
.cb-root .cb-board .cb-col--l .cb-bbracket{left:calc(100% + 2px)}
.cb-root .cb-board .cb-col--r .cb-bbracket{right:calc(100% + 2px)}

/* anchors over the drawing (module, antenna, ports, buttons): transparent, a silk outline on hover */
.cb-root .cb-board .cb-module{position:absolute;inset:0;display:block;padding:0;min-height:0;pointer-events:none}
.cb-root .cb-board .cb-usb,.cb-root .cb-board .cb-btns{display:contents}
.cb-root .cb-board .cb-banchor{position:absolute;display:block;pointer-events:auto;border-radius:3px;border:0;background:none;width:auto;height:auto;margin:0}
.cb-root .cb-board .cb-banchor:hover{outline:1px dashed color-mix(in oklab,var(--cb-silk) 70%,transparent);outline-offset:2px}
.cb-root .cb-board .cb-bport[data-cb-live=true]{outline:2px solid var(--cb-active);outline-offset:3px}
/* notes printed on the pcb (variant unknown, PSRAM reservation): silk on the material, the shape carries the tone */
.cb-root .cb-board .cb-bnote{position:absolute;display:flex;align-items:center;justify-content:center;gap:6px;padding:2px 6px;text-align:center;
  font-size:10px;line-height:13px;font-weight:700;letter-spacing:.06em;color:var(--cb-silk);border:0;
  border-radius:2px;background:none;pointer-events:auto}
/* notes are silk print (no dashed box); caution notes carry the ◇ glyph, a hairline under the
   line keeps them apart from the parts */
.cb-root .cb-board .cb-bnote > span{border-bottom:1px solid color-mix(in oklab,var(--cb-silk) 35%,transparent);padding-bottom:1px}
.cb-root .cb-board .cb-bnote .cb-glyph path{stroke:var(--cb-warn)}

/* legend: the board's symbols with their words */
.cb-root .cb-legend{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:4px 14px;margin:0 0 8px;color:var(--cb-fg-dim);font-size:11px;line-height:14px}
.cb-root .cb-legend > span{display:inline-flex;align-items:center;gap:5px;white-space:nowrap}
/* PLAN head: title + meta, Suggest pins at the right; the toolbar below stays one line: the group labels give
   way first when the station is narrow */
.cb-root .cb-planhead{display:flex;align-items:center;gap:12px;min-width:0}
.cb-root .cb-planhead > .cb-title{flex:1 1 auto}
.cb-root .cb-planhead > .cb-btn{flex:none}
.cb-root [data-cb=plan-toolbar]{container:cbtool/inline-size;margin:8px 0 6px}
@container cbtool (max-width:760px){.cb-root [data-cb=plan-toolbar] .cb-group > .cb-label{display:none}.cb-root [data-cb=plan-toolbar] .cb-group{padding-right:8px}}
/* legend as caption */
.cb-root .cb-legend--cap{justify-content:center;margin:8px auto 0;max-width:var(--cb-cap-w,100%)}
.cb-root .cb-legend-sug i{display:inline-block;width:12px;height:12px;border:1.5px dashed var(--cb-ok);border-radius:50%}

/* what-if line: one flat row inside the toolbar (S2 fits at 1100×800) */
.cb-root [data-cb=plan-toolbar] .cb-whatif{min-height:0;padding:1px 4px 1px 8px;gap:6px;line-height:16px}
.cb-root [data-cb=plan-toolbar] .cb-whatif .cb-btn--sm{padding:1px 7px;line-height:16px}

.cb-root .cb-board-empty{border:1px dashed var(--cb-stroke-strong);padding:22px;max-width:680px;margin:0 auto}

/* compact model and live twin: the SVG scales with its box, the stamp and caption are DOM */
.cb-root .cb-twin{min-width:0}
.cb-root .cb-twin-box{position:relative}
.cb-root .cb-twin-art svg{display:block;width:100%;height:auto;overflow:visible}
.cb-root .cb-twin-stamp{position:absolute;transform:translate(-50%,-50%);pointer-events:none;white-space:nowrap}
.cb-root .cb-twin-stamp .cb-stamp{font-size:11px;padding:2px 7px;letter-spacing:.14em}
/* chat card hover coupling */
.cb-root .cb-twin-ring{position:absolute;width:14px;height:14px;transform:translate(-50%,-50%);border:2px solid var(--cb-active);border-radius:50%;
  box-shadow:var(--cb-glow-active);pointer-events:none}
.cb-root .cb-dpin[data-cb-hot=true] > *{background:color-mix(in oklab,var(--cb-active) 12%,transparent)}
.cb-root .cb-twin-cap{display:flex;flex-wrap:wrap;justify-content:space-between;gap:2px 10px;margin-top:6px;font-size:10px;line-height:13px;letter-spacing:.06em;
  color:var(--cb-fg-dim)}
.cb-root .cb-twin-cap-t{color:var(--cb-fg);font-weight:700;letter-spacing:.08em}
/* the pulse port → module: opacity only, one 600 ms cycle, only while the job runs (the dots exist only then) */
.cb-root .cb-twin-dot{opacity:.85}
@media (prefers-reduced-motion:no-preference){
  .cb-root .cb-twin-dot{opacity:0;animation:cb-twin-pulse .6s linear infinite}
  .cb-root .cb-twin-dot--1{animation-delay:.15s}.cb-root .cb-twin-dot--2{animation-delay:.3s}.cb-root .cb-twin-dot--3{animation-delay:.45s}
}
@keyframes cb-twin-pulse{0%,100%{opacity:0}25%{opacity:1}55%{opacity:0}}

/* chat card, view pins: model left, figures + assignments right, the legend across */
.cb-root.cb-dcard[data-cb-view=pins]{max-width:700px}
.cb-root.cb-dcard[data-cb-view=pins]{container-type:inline-size}
.cb-root .cb-dpins{display:flex;flex-wrap:wrap;gap:10px 18px;margin-top:10px;align-items:stretch}
.cb-root .cb-dpins-board{flex:1 1 250px;max-width:330px;padding:8px 8px 6px;border:1px solid var(--cb-stroke);background:color-mix(in oklab,var(--cb-panel) 85%,transparent)}
.cb-root .cb-dpins-side{flex:1 1 230px;min-width:0;display:flex;flex-direction:column;gap:8px}
.cb-root .cb-dkpis{margin:0;display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 14px;font-size:13px;letter-spacing:.02em;font-weight:400}
.cb-root .cb-dkpis-l{flex:1 1 100%}
.cb-root .cb-dkpi{display:inline-flex;align-items:baseline;gap:4px;white-space:nowrap}
.cb-root .cb-dkpi b{font-weight:700;font-variant-numeric:tabular-nums}
.cb-root .cb-dkpi-w{color:var(--cb-fg)}
.cb-root .cb-dkpi.cb-dim .cb-dkpi-w{color:var(--cb-fg-dim)}
.cb-root .cb-dpins-list{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:12px max-content max-content max-content minmax(0,1fr) max-content;
  column-gap:8px;row-gap:3px;align-items:center;font-size:12px;line-height:18px}
.cb-root .cb-dpin{display:contents}
.cb-root .cb-dpin-role{font-weight:700;color:var(--cb-fg);letter-spacing:.04em}
.cb-root .cb-dpin-io{color:var(--cb-active-text);font-variant-numeric:tabular-nums}
.cb-root .cb-dpin--blocked .cb-dpin-io{color:var(--cb-bad-text)}
.cb-root .cb-dpin--caution .cb-dpin-io{color:var(--cb-warn-text)}
.cb-root .cb-dpin-at,.cb-root .cb-dpin-w,.cb-root .cb-dpin-mode{font-size:11px;white-space:nowrap}
.cb-root .cb-dpin-mode{min-width:0;overflow:hidden}
@container (max-width:600px){
  .cb-root .cb-dpins-list{grid-template-columns:12px max-content max-content minmax(0,1fr) max-content}
  .cb-root .cb-dpin-mode{display:none}
}
.cb-root .cb-dpins-foot{margin-top:auto;display:flex;flex-direction:column;gap:5px;padding-top:8px;border-top:1px dashed var(--cb-stroke);font-size:11px;line-height:15px}
.cb-root .cb-dpins-res,.cb-root .cb-dpins-spec{display:flex;flex-wrap:wrap;align-items:baseline;gap:3px 10px;min-width:0}
.cb-root .cb-dpins-foot .cb-label{flex:none;min-width:56px}
.cb-root .cb-dpins-spec > span{color:var(--cb-fg);white-space:nowrap}
.cb-root .cb-dpins-spec > span:not(:last-child)::after{content:' ·';color:var(--cb-fg-dim)}
.cb-root .cb-dres{display:inline-flex;align-items:center;gap:5px;white-space:nowrap;color:var(--cb-fg-dim)}
.cb-root .cb-dres b{font-weight:700;letter-spacing:.06em}
.cb-root .cb-dres--warn b{color:var(--cb-warn-text)}.cb-root .cb-dres--bad b{color:var(--cb-bad-text)}
.cb-root .cb-dres i{flex:none;width:12px;height:9px;border:1.5px dashed var(--cb-warn);border-radius:1px}
.cb-root .cb-dres--bad i{border-color:var(--cb-bad)}
.cb-root .cb-dpin-w{text-align:right}
.cb-root .cb-dpin--more{display:block;grid-column:1 / -1;font-size:11px}
.cb-root .cb-dpins-legend{flex:1 1 100%;justify-content:flex-start;margin:0;padding-top:8px;border-top:1px solid var(--cb-stroke)}
.cb-root.cb-dcard[data-cb-view=pins] .cb-actions{margin-top:10px;justify-content:flex-end}

/* live twin cards in 05 FLASH (inspector) and 06 DEBUG (monitor card) */
.cb-root .cb-twin-card .cb-twin{margin-top:8px}
.cb-root .cb-twin-note{display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 8px;margin:8px 0 0;font-size:11px;line-height:15px;min-width:0}
.cb-root .cb-twin-note b{font-weight:700;color:var(--cb-fg);overflow-wrap:anywhere;min-width:0}
.cb-root .cb-twin-note .cb-active-t{color:var(--cb-active-text)}
.cb-root .cb-twin-row{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;margin-top:10px;padding-top:10px;border-top:1px solid var(--cb-stroke)}
.cb-root .cb-twin-row > .cb-twin{flex:1 1 200px;max-width:280px}
.cb-root .cb-twin-row > .cb-twin-lab{flex:1 1 100%}
.cb-root .cb-twin-leds{flex:1 1 130px;display:flex;flex-direction:column;gap:6px;min-width:0}
.cb-root .cb-twin-led{display:inline-flex;align-items:center;gap:6px;font-size:11px;line-height:14px;white-space:nowrap}
.cb-root .cb-twin-led b{font-weight:700;letter-spacing:.1em;color:var(--cb-fg)}
.cb-root .cb-twin-led i{flex:none;width:9px;height:9px;border-radius:50%;border:1.5px solid var(--cb-stroke-strong);background:none}
.cb-root .cb-twin-led[data-cb-on=true] i{background:var(--cb-ok);border-color:var(--cb-ok);box-shadow:var(--cb-glow-ok)}
.cb-root .cb-twin-led[data-cb-on=true] .cb-dim{color:var(--cb-ok-text)}
`)
