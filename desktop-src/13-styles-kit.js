// Kit styles: agent button, SIM badge, state glyph and state pill.
// Registered through CB_CSS_PARTS (10-tokens.js); comes after 11/12, so equal specificity wins here.
CB_CSS_PARTS.push(`
/* Hermes action: active (cyan) fill with ink text, never the alarm colour; ◢ in front (aria-hidden) */
.cb-root .cb-btn--agent{background:var(--cb-active-fill);color:var(--cb-ink);box-shadow:var(--cb-glow-active)}
.cb-root .cb-btn--agent:hover{background:color-mix(in oklab,var(--cb-active-fill) 86%,white)}
.cb-root .cb-btn--agent:focus-visible{outline:2px solid var(--cb-active);outline-offset:2px}
.cb-root .cb-btn-mark{font-size:10px;line-height:1;letter-spacing:0;flex:none}

/* SIM badge: solid frame, diagonal stripes, the word SIMULATED always visible */
.cb-root .cb-simbadge{display:inline-flex;align-items:stretch;gap:0;padding:0;border:1px solid color-mix(in oklab,var(--cb-active) 70%,transparent);
  border-radius:2px;color:var(--cb-active-text);font-size:10px;font-weight:700;letter-spacing:.14em;line-height:16px;white-space:nowrap;overflow:hidden;flex:none}
.cb-root .cb-simbadge-s{width:12px;flex:none;border-right:1px solid color-mix(in oklab,var(--cb-active) 70%,transparent);
  background:repeating-linear-gradient(135deg,color-mix(in oklab,var(--cb-active) 80%,transparent) 0 2px,transparent 2px 5px)}
.cb-root .cb-simbadge-t{padding:1px 7px 1px 6px}
.cb-root .cb-simbadge--sm{line-height:14px}
.cb-root .cb-simbadge--sm .cb-simbadge-s{width:9px}
.cb-root .cb-simbadge--sm .cb-simbadge-t{padding:0 5px}
/* port + SIM badge: the port gives way */
.cb-root b.cb-kv-port{display:flex;align-items:center;gap:8px;min-width:0;overflow:visible;text-overflow:clip}
.cb-root b.cb-kv-port .cb-simbadge{font-weight:700}

/* state symbol (inline SVG, 12 px): shape carries the state, colour only adds to it */
.cb-root .cb-glyph{display:inline-block;width:12px;height:12px;flex:none;vertical-align:-2px;overflow:visible}
.cb-root .cb-glyph--free{color:var(--cb-ok-text)}
.cb-root .cb-glyph--assigned{color:var(--cb-active-text)}
.cb-root .cb-glyph--caution{color:var(--cb-warn-text)}
.cb-root .cb-glyph--blocked,.cb-root .cb-glyph--assigned_blocked{color:var(--cb-bad-text)}
.cb-root .cb-glyph--power{color:var(--cb-power-text)}
.cb-root .cb-glyph--ground,.cb-root .cb-glyph--signal{color:var(--cb-fg-dim)}
.cb-root .cb-glyph--nc{color:var(--cb-fg-faint)}

/* ─── shell: frame, HUD, rail, inspector ─── */
/* the project list shows the compact SIM badge (46-dialogs.js) */
.cb-root .cb-projmeta{display:flex;align-items:center;gap:8px;min-width:0;overflow:visible;text-overflow:clip}
.cb-root .cb-projmeta .cb-simban-w{display:none}
.cb-root .cb-projmeta > .cb-ellip{min-width:0}
.cb-root .cb-hud-count{background:color-mix(in oklab,var(--cb-fg) 12%,transparent)}

/* one scale (step 5, 12-styles.js): controls 24 / 28 / 32 px, gaps 4 / 8 / 12 / 16 / 24 px; card head and foot */
.cb-root .cb-card-tools{margin-left:auto;display:flex;gap:4px;flex:none}
.cb-root .cb-card-foot{margin-top:12px;padding-top:8px;border-top:1px dashed var(--cb-stroke-strong)}
.cb-root .cb-card-foot .cb-src{margin-top:0}
.cb-root .cb-card-foot:empty{display:none}

/* inspector: verdict → reason → the way out (chips) → details → source in the foot */
.cb-root .cb-insp-card .cb-verdict{margin-top:8px}
.cb-root .cb-insp-way{margin-top:12px;display:grid;gap:4px}
.cb-root .cb-insp-way .cb-alts{margin-top:0;gap:8px}
.cb-root .cb-altchip{display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 8px;color:var(--cb-fg);
  border-color:color-mix(in oklab,var(--cb-ok) 45%,var(--cb-stroke-strong))}
.cb-root .cb-altchip b{font-weight:700}
.cb-root .cb-altchip:hover{background:color-mix(in oklab,var(--cb-ok) 10%,transparent);box-shadow:none;border-color:var(--cb-ok)}
.cb-root .cb-insp-card .cb-actions{margin-top:12px}
.cb-root .cb-insp-card .cb-fn{margin-top:12px}

/* assignment table: fixed columns, never wider than the inspector (WT32 audit: td.cb-r 25 px out) */
.cb-root .cb-table--assign{table-layout:fixed}
/* inspector content ≈ 264 px at 1440: pin 38 + mode 58 + verdict 72 + remove 20 → role keeps ≈ 76 px (10 characters) */
.cb-root .cb-table--assign .cb-col-pin{width:38px}
.cb-root .cb-table--assign .cb-col-mode{width:64px}
.cb-root .cb-table--assign td,.cb-root .cb-table--assign th{padding-left:3px;padding-right:3px}
.cb-root .cb-table--assign .cb-col-verdict{width:72px}
.cb-root .cb-table--assign .cb-col-x{width:20px}
.cb-root .cb-table--assign .cb-cell-ellip{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cb-root .cb-table--assign td.cb-dim,.cb-root .cb-table--assign .cb-verdict-cell{font-size:11px}
.cb-root .cb-table--assign td.cb-r,.cb-root .cb-table--assign th.cb-r{padding-left:0;padding-right:0;text-align:center}
/* narrow inspector (1280/1100 windows): the verdict shows its symbol (the word stays for screen readers and in
   the title), the check time gives way to "+ assign" */
.cb-root .cb-insp{container:cbinsp/inline-size}
@container cbinsp (max-width:300px){
  .cb-root .cb-table--assign .cb-col-verdict{width:26px}.cb-root .cb-table--assign .cb-col-mode{width:64px}
  .cb-root .cb-table--assign .cb-vw{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
  .cb-root [data-cb=assignments] [data-cb=checked-at]{display:none}
  .cb-root [data-cb=assignments] [data-cb=assign-new]{margin-left:auto}
}
`)
