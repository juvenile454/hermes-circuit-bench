// Station 04 SOLDER styles: pictograms, hint lines by kind, done steps that
// fold and open (no ellipsis: overrides 11-styles-ui2.js:151), the progress formula, the height strip, the part list.
CB_CSS_PARTS.push(`
.cb-root .cb-solder-prog{display:flex;align-items:center;gap:14px;margin:10px 0 12px;flex-wrap:wrap}
.cb-root .cb-solder-formula{font-size:13px;color:var(--cb-fg-dim);letter-spacing:.02em;font-variant-numeric:tabular-nums}
.cb-root .cb-solder-formula b{font-size:15px;font-weight:700}
.cb-root .cb-solder-formula .cb-solder-nowrefs{color:var(--cb-active-text)}
.cb-root .cb-solder-prog .cb-bar{flex:1 1 160px;max-width:360px;height:8px}

/* pictograms: side view on the board; annotations (cathode symbol, unclear outline) draw in currentColor */
.cb-root .cb-part-pic{display:inline-flex;flex:none;color:var(--cb-fg-dim);line-height:0}
.cb-root .cb-part-pic svg{display:block;overflow:visible}
.cb-root .cb-part-pic--lg{padding:6px 8px 4px;border:1px solid var(--cb-stroke);background:color-mix(in oklab,var(--cb-fg) 3%,var(--cb-bg))}
.cb-root .cb-part-pic--md{padding:4px 6px 2px;border:1px solid var(--cb-stroke);background:color-mix(in oklab,var(--cb-fg) 2%,var(--cb-bg))}
.cb-root .cb-part-pic--sm{align-self:center}

/* step cards */
.cb-root .cb-steps-list{display:grid;gap:8px;max-width:960px}
.cb-root .cb-step-body{min-width:0}
.cb-root .cb-step-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;min-height:22px}
.cb-root .cb-step-head .cb-btn{flex:none}
.cb-root .cb-step-main{display:flex;gap:14px;align-items:flex-start;margin-top:8px;flex-wrap:wrap}
.cb-root .cb-step-fig{display:flex;flex-direction:column;align-items:flex-start;gap:6px;flex:none}
.cb-root .cb-step-text{flex:1 1 260px;min-width:0}
.cb-root .cb-step-act{margin-top:0;line-height:1.5;color:var(--cb-fg);white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:anywhere}
.cb-root .cb-step--todo{background:var(--cb-bg);border-color:var(--cb-stroke)}
.cb-root .cb-step--todo .cb-step-act,.cb-root .cb-step--todo .cb-step-head b,.cb-root .cb-step--todo .cb-step-refs{color:var(--cb-fg-dim)}
.cb-root .cb-step--todo .cb-part-pic{opacity:.7}
.cb-root .cb-step--done{padding:5px 11px;align-items:center}
.cb-root .cb-step--done.cb-step--open{align-items:start}
.cb-root .cb-step--done .cb-step-act{white-space:normal;overflow:visible;text-overflow:clip;color:var(--cb-fg-dim);margin-top:0}
.cb-root .cb-step-line{gap:8px}
.cb-root .cb-step-donew{font-size:11px}
.cb-root .cb-step-more{font-size:11px;color:var(--cb-fg-dim);padding:2px 6px;border:1px solid var(--cb-stroke);border-radius:2px;line-height:1.3}
.cb-root .cb-step-more:hover{color:var(--cb-fg);border-color:var(--cb-stroke-strong)}
.cb-root .cb-step-more:focus-visible{outline:2px solid var(--cb-active);outline-offset:1px}
.cb-root .cb-step-detail{margin:6px 0 2px;padding:6px 0 0;border-top:1px dashed var(--cb-stroke)}
.cb-root .cb-step--done .cb-part-pic{opacity:.8}

/* polarity tag: only with a sourced hint; outlined (a tag, not a state fill) */
.cb-root .cb-pol{display:inline-flex;align-items:center;gap:5px;padding:0 6px;border:1px solid var(--cb-stroke-strong);border-radius:2px;
  font-size:10px;line-height:16px;letter-spacing:.1em;text-transform:uppercase;color:var(--cb-fg);white-space:nowrap}
.cb-root .cb-pol > span{font-weight:700;letter-spacing:0}

/* hint lines: symbol, category, text + sources; tone by severity, never colour alone (symbol + word) */
.cb-root .cb-shints{margin:8px 0 0;padding:0;list-style:none;display:grid;gap:5px;font-size:11px;line-height:1.5}
.cb-root .cb-shint{display:grid;grid-template-columns:16px 70px minmax(0,1fr);gap:8px;align-items:baseline}
.cb-root .cb-shint-sym{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border:1px solid currentColor;border-radius:2px;
  font-size:11px;font-weight:700;line-height:1;align-self:start;margin-top:1px}
.cb-root .cb-shint-cat{font-size:10px;letter-spacing:.12em;text-transform:uppercase;font-weight:700;padding-top:1px}
.cb-root .cb-shint-t{color:var(--cb-fg);min-width:0;overflow-wrap:anywhere}
.cb-root .cb-shint--danger .cb-shint-sym,.cb-root .cb-shint--danger .cb-shint-cat{color:var(--cb-bad-text)}
.cb-root .cb-shint--danger .cb-shint-sym{background:color-mix(in oklab,var(--cb-bad) 14%,transparent)}
.cb-root .cb-shint--caution .cb-shint-sym,.cb-root .cb-shint--caution .cb-shint-cat{color:var(--cb-warn-text)}
.cb-root .cb-shint--info .cb-shint-sym,.cb-root .cb-shint--info .cb-shint-cat{color:var(--cb-fg-dim)}
.cb-root .cb-shint--info .cb-shint-t{color:var(--cb-fg-dim)}
.cb-root .cb-step--todo .cb-shint-t{color:var(--cb-fg-dim)}
.cb-root .cb-shint-src{display:inline-flex;flex-wrap:wrap;gap:0 6px;align-items:baseline;color:var(--cb-fg-dim);font-size:11px;letter-spacing:.02em}
.cb-root .cb-shint-src .cb-k{color:var(--cb-fg-dim)}
.cb-root .cb-shint-src-sep{color:var(--cb-fg-faint)}
.cb-root .cb-shint-src button{color:var(--cb-active-text);font-size:11px}
.cb-root .cb-shint-src button:hover{text-decoration:underline}

/* height strip (rule of thumb) */
.cb-root .cb-heights{margin:0 0 12px;max-width:960px}
.cb-root .cb-heights-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:5px}
.cb-root .cb-heights-why{font-size:11px;color:var(--cb-fg-dim)}
.cb-root .cb-heights-rot{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--cb-fg-dim);padding:0 5px;border:1px dashed var(--cb-stroke-strong);border-radius:2px}
.cb-root .cb-heights-row{display:flex;flex-wrap:wrap;gap:6px;margin:0;padding:0;list-style:none}
.cb-root .cb-hcell{display:flex;flex-direction:column;align-items:center;gap:2px;padding:3px 4px 2px;border:1px solid var(--cb-stroke);background:var(--cb-bg)}
.cb-root .cb-hcell-pic{display:block;line-height:0;color:var(--cb-fg-dim)}
.cb-root .cb-hcell-pic svg{display:block}
.cb-root .cb-hcell-n{font-size:10px;color:var(--cb-fg-dim);font-variant-numeric:tabular-nums;letter-spacing:.06em}
.cb-root .cb-hcell--done .cb-hcell-pic{opacity:.6}
.cb-root .cb-hcell--done .cb-hcell-n{color:var(--cb-ok-text)}
.cb-root .cb-hcell--now{border-color:var(--cb-active);box-shadow:inset 0 -2px 0 var(--cb-active)}
.cb-root .cb-hcell--now .cb-hcell-n{color:var(--cb-active-text);font-weight:700}

/* plan source: part list, reasons for disabled buttons, CSV import folded */
.cb-root .cb-sparts{margin:10px 0 4px;padding:0;list-style:none;display:grid;gap:2px;font-size:11px}
.cb-root .cb-spart{display:grid;grid-template-columns:14px 38px minmax(0,1fr) auto;gap:6px;align-items:baseline;padding:2px 5px;border:1px solid transparent}
.cb-root .cb-spart-mark{color:var(--cb-fg-dim);text-align:center}
.cb-root .cb-spart-ref{color:var(--cb-fg);font-weight:700}
.cb-root .cb-spart-what{color:var(--cb-fg);min-width:0;overflow-wrap:anywhere}
.cb-root .cb-spart-step{color:var(--cb-fg-dim);font-variant-numeric:tabular-nums;font-size:10px;letter-spacing:.06em}
.cb-root .cb-spart--done .cb-spart-mark{color:var(--cb-ok-text)}
.cb-root .cb-spart--done .cb-spart-what,.cb-root .cb-spart--done .cb-spart-ref{color:var(--cb-fg-dim)}
.cb-root .cb-spart--now{border-color:var(--cb-active);background:color-mix(in oklab,var(--cb-active) 7%,transparent)}
.cb-root .cb-spart--now .cb-spart-mark,.cb-root .cb-spart--now .cb-spart-step{color:var(--cb-active-text);font-weight:700}
.cb-root .cb-spart--none .cb-spart-step{color:var(--cb-warn-text)}
.cb-root .cb-solder-why{margin:4px 0 0;font-size:11px;line-height:1.45;color:var(--cb-fg-dim);white-space:normal}
.cb-root .cb-solder-csv{margin-top:12px;border-top:1px solid var(--cb-stroke);padding-top:8px}
.cb-root .cb-solder-csv > summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:6px}
.cb-root .cb-solder-csv > summary::-webkit-details-marker{display:none}
.cb-root .cb-solder-csv > summary::before{content:'▸';color:var(--cb-fg-dim);font-size:11px}
.cb-root .cb-solder-csv[open] > summary::before{content:'▾'}
.cb-root .cb-solder-csv > summary:focus-visible{outline:2px solid var(--cb-active);outline-offset:2px}
`)
