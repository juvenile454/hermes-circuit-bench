// WIRE styles: the schematic frame with its header, the fitted plan, stroke widths
// per data-kind (lines 1.5 px, bodies and ports 2 px, selection 2 px plus pulse), net colours per data-net
// (supply power, ground fg-dim, signal fg, hover/selection active), the wiring table with fixed columns and net chips,
// warning cards. Attribute selectors only: the SVG itself stays self-contained (currentColor, no <style>).
// The supply/ground names match lib/wire.js WIRE_RAILS / WIRE_GROUND (tests-js/test_vwire_station.mjs).
CB_CSS_PARTS.push(`
/* MODULES: grouped block pick, wraps */
.cb-root .cb-group--wblocks{flex-wrap:wrap;min-width:0;row-gap:6px}
.cb-root .cb-wblocks{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;min-width:0}
.cb-root .cb-wblocks-g{display:inline-flex;align-items:center;gap:6px}
.cb-root .cb-wblocks-k{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--cb-fg-dim)}
/* focusable rows */
.cb-root .cb-wiretable tbody tr:focus-visible,.cb-root .cb-wparts tbody tr:focus-visible{outline:2px solid var(--cb-active);outline-offset:-2px}
.cb-root table.cb-wiretable td.cb-fg{white-space:normal;text-overflow:clip;overflow-wrap:break-word}
/* narrow Bench (1100×800 beside the chat): the block name gives way in the schematic head (it is in the parameter card);
   the net chip keeps its letters (thin cell padding) */
@container cb (max-width:899px){.cb-root .cb-svghead-b{display:none}
  .cb-root .cb-wiretable td:last-child{padding-left:3px;padding-right:2px}
  .cb-root table.cb-wiretable .cb-wcol-from{width:26%}.cb-root table.cb-wiretable .cb-wcol-to{width:24%}.cb-root table.cb-wiretable .cb-wcol-net{width:50%}}
/* frame: header bar (title, net legend, Save SVG), the stage that fits and centres the plan, caption */
.cb-root .cb-main--fill > .cb-svgwrap{min-height:auto}
.cb-root .cb-svgwrap{flex-direction:column;align-items:stretch;padding:0;background:color-mix(in oklab,var(--cb-panel) 96%,transparent)}
.cb-root .cb-svghead{display:flex;align-items:center;gap:14px;min-width:0;min-height:34px;padding:4px 8px 4px 12px;border-bottom:1px solid var(--cb-stroke);flex:none}
.cb-root .cb-svghead > .cb-label{white-space:nowrap;min-width:0;overflow:hidden;text-overflow:ellipsis}
.cb-root .cb-netlegend{display:flex;align-items:center;gap:12px;flex:none;font-size:10px;letter-spacing:.08em;text-transform:uppercase}
.cb-root .cb-netkey{display:inline-flex;align-items:center;gap:5px;white-space:nowrap}
.cb-root .cb-netkey .cb-glyph{width:12px;height:12px;color:inherit}
.cb-root .cb-svghead-act{margin-left:auto;flex:none;display:flex;gap:6px}
.cb-root .cb-svgstage{flex:1 1 auto;display:flex;align-items:stretch;justify-content:center;padding:12px 14px 26px;min-width:0;overflow-x:auto}
.cb-root .cb-svgwrap .cb-svgstage .cb-svg{flex:1 1 auto;align-self:stretch;position:relative}
/* the box takes the whole stage (no auto margins: they would stop the stretch); the SVG adds no intrinsic height
   of its own (width:100% would make it as tall as its aspect ratio): it fills the box, scaled with meet and centred;
   the box's min size (viewBox in px) keeps scale ≥ 1 */
.cb-root .cb-svgwrap .cb-svgstage .cb-svg svg{position:absolute;inset:0;width:100%;height:100%}
.cb-root .cb-svgcap{left:12px;bottom:7px}

/* strokes per role, in screen pixels whatever the scale */
.cb-root .cb-svg svg path,.cb-root .cb-svg svg circle,.cb-root .cb-svg svg polygon,.cb-root .cb-svg svg rect{vector-effect:non-scaling-stroke}
.cb-root .cb-svg svg [data-kind=wire]{stroke-width:1.5px}
.cb-root .cb-svg svg [data-kind=body],.cb-root .cb-svg svg [data-kind=port]{stroke-width:2px}
.cb-root .cb-svg svg [data-kind=junction]{stroke-width:1px;fill:currentColor}
.cb-root .cb-svg svg text[data-kind=pin]{fill:var(--cb-fg-dim)}

/* net colours: supply, ground, signal (default fg) */
.cb-root .cb-svg svg [data-net="3V3"],.cb-root .cb-svg svg [data-net="5V"]{color:var(--cb-power-text)}
.cb-root .cb-svg svg [data-net=GND]{color:var(--cb-fg-dim)}

/* hover / selection: the part or net in active, its lines 2.5 px, everything else's ink steps back (texts stay) */
.cb-root .cb-svg svg [data-cb-on=true]{color:var(--cb-active-text)}
.cb-root .cb-svg svg text[data-cb-on=true]{fill:var(--cb-active-text)}
.cb-root .cb-svg svg [data-kind=wire][data-cb-on=true],.cb-root .cb-svg svg [data-kind=body][data-cb-on=true],
  .cb-root .cb-svg svg [data-kind=port][data-cb-on=true]{stroke-width:2.5px}
.cb-root .cb-svg svg rect[data-cb-on=true]{fill:color-mix(in oklab,var(--cb-active) 9%,transparent)}
.cb-root .cb-svg[data-cb-hl] svg path:not([data-cb-on=true]),.cb-root .cb-svg[data-cb-hl] svg circle:not([data-cb-on=true]){opacity:.4}
.cb-root .cb-svg svg path,.cb-root .cb-svg svg circle{transition:opacity .12s,color .12s}
@media (prefers-reduced-motion:no-preference){
  .cb-root .cb-svg svg [data-kind=wire][data-cb-on=true]{animation:cb-wire-pulse 1.4s ease-in-out infinite}
}
@keyframes cb-wire-pulse{0%,100%{stroke-opacity:1}50%{stroke-opacity:.55}}

/* wiring table: fixed columns with a grid, the net as a chip in its colour */
.cb-root table.cb-wiretable{table-layout:fixed}
.cb-root .cb-wiretable .cb-wcol-from{width:28%}
.cb-root .cb-wiretable .cb-wcol-to{width:26%}
.cb-root .cb-wiretable .cb-wcol-net{width:46%}
.cb-root .cb-wiretable td,.cb-root .cb-wiretable th{padding:3px 5px;border-bottom:1px solid var(--cb-stroke);overflow:hidden;text-overflow:ellipsis}
.cb-root .cb-wiretable td + td,.cb-root .cb-wiretable th + th{border-left:1px solid var(--cb-stroke)}
.cb-root .cb-wiretable thead th{border-bottom-color:var(--cb-stroke-strong)}
.cb-root .cb-netchip{display:inline-flex;align-items:center;max-width:100%;padding:0 5px;border:1px solid color-mix(in oklab,currentColor 55%,transparent);
  border-radius:2px;font-size:11px;line-height:16px;vertical-align:middle;color:var(--cb-fg)}
.cb-root .cb-netchip-t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.cb-root .cb-netchip--power{color:var(--cb-power-text);background:color-mix(in oklab,var(--cb-power) 10%,transparent)}
.cb-root .cb-netchip--ground{color:var(--cb-fg-dim)}
.cb-root .cb-netchip--signal{color:var(--cb-fg)}
.cb-root .cb-wiretable tr[aria-selected=true] .cb-netchip{color:var(--cb-active-text);border-color:var(--cb-active)}
.cb-root .cb-wparts tr[data-cb-ref]{cursor:pointer}

/* warning card under the parts (danger: the alarm colour as frame and mark, the text itself unchanged) */
.cb-root .cb-wwarn{border-color:color-mix(in oklab,var(--cb-warn) 60%,transparent);background:color-mix(in oklab,var(--cb-warn) 6%,var(--cb-panel))}
.cb-root .cb-wwarn--danger{border-color:color-mix(in oklab,var(--cb-bad) 70%,transparent);background:color-mix(in oklab,var(--cb-bad) 7%,var(--cb-panel))}
.cb-root .cb-wwarn .cb-card-head{gap:8px}
.cb-root .cb-wwarn-mark{display:inline-grid;place-items:center;width:16px;height:16px;flex:none;border-radius:2px;font-size:11px;font-weight:700;
  background:var(--cb-warn-fill);color:var(--cb-ink)}
.cb-root .cb-wwarn--danger .cb-wwarn-mark{background:var(--cb-bad-fill)}
.cb-root .cb-wwarn--danger .cb-label{color:var(--cb-bad-text)}
.cb-root .cb-wwarn:not(.cb-wwarn--danger) .cb-label{color:var(--cb-warn-text)}
.cb-root .cb-wwarn-t{margin:6px 0 0;font-size:12px;line-height:1.5;color:var(--cb-fg)}
`)
