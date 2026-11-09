// Module styles: dialog, bus card, module rows; only cb-mod-*, one push
CB_CSS_PARTS.push(`
.cb-root .cb-mod-pad{padding:12px 0}
.cb-root .cb-mod-list{list-style:none;margin:6px 0 0;padding:0;display:grid;gap:4px;min-width:0}
.cb-root .cb-mod-row{display:grid;grid-template-columns:auto auto minmax(0,1fr);gap:8px;align-items:baseline;min-width:0;font-size:12px;line-height:1.45;overflow-wrap:anywhere}
.cb-root .cb-mod-row--f{grid-template-columns:14px minmax(0,1fr)}
.cb-root .cb-mod-row--r{grid-template-columns:14px minmax(0,1fr) auto}
.cb-root .cb-mod-row--2{grid-template-columns:64px minmax(0,1fr)}
.cb-root .cb-mod-sym{display:inline-flex;justify-content:center;min-width:12px;font-size:12px;font-weight:700}
.cb-root .cb-mod-row--bad .cb-mod-sym,.cb-root .cb-mod-row--bad b,.cb-root .cb-mod-t-bad{color:var(--cb-bad-text)}
.cb-root .cb-mod-row--warn .cb-mod-sym,.cb-root .cb-mod-row--warn b,.cb-root .cb-mod-t-warn{color:var(--cb-warn-text)}
.cb-root .cb-mod-row--ok .cb-mod-sym,.cb-root .cb-mod-row--ok b,.cb-root .cb-mod-t-ok{color:var(--cb-ok-text)}
.cb-root .cb-mod-row--dim .cb-mod-sym,.cb-root .cb-mod-dim,.cb-root .cb-mod-t-dim,.cb-root .cb-mod-k,.cb-root .cb-mod-page,.cb-root .cb-mod-catl,.cb-root .cb-mod-open td,.cb-root .cb-mod-sum{color:var(--cb-fg-dim)}
.cb-root .cb-mod-k,.cb-root .cb-mod-page,.cb-root .cb-mod-catl,.cb-root .cb-mod-nums,.cb-root .cb-mod-open td,.cb-root .cb-mod-grp .cb-mod-dim,.cb-root .cb-mod-pins .cb-mod-dim,.cb-root .cb-mod-railhead .cb-mod-push,.cb-root .cb-mod-grphead span{font-size:11px}
.cb-root .cb-mod-page,.cb-root .cb-mod-catl,.cb-root .cb-mod-ellip{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.cb-root .cb-mod-push{margin-left:auto}
.cb-root .cb-mod-link{color:var(--cb-active-text);font-size:12px;padding:0;white-space:nowrap;text-align:left}
.cb-root .cb-mod-link:hover,.cb-root .cb-mod-link:focus-visible{text-decoration:underline}
.cb-root .cb-mod-note{font-size:11px;line-height:1.5;margin:6px 0 0;overflow-wrap:anywhere}
.cb-root .cb-mod-dlg{max-height:min(60vh,540px);overflow:auto;min-width:0;padding-right:2px}
.cb-root .cb-mod-filter{display:grid;grid-template-columns:minmax(0,1fr) 200px;gap:8px}
.cb-root .cb-mod-search,.cb-root .cb-mod-cat{width:100%;min-width:0}
.cb-root .cb-mod-sum{margin:8px 0 6px;font-size:11px}
.cb-root .cb-mod-items{list-style:none;margin:0;padding:0;display:grid;gap:6px}
.cb-root .cb-mod-item{display:grid;gap:5px;width:100%;text-align:left;padding:7px 10px;border:1px solid var(--cb-stroke-strong);min-width:0}
.cb-root .cb-mod-item:hover,.cb-root .cb-mod-item:focus-visible,.cb-root .cb-mod-item[aria-current=true]{border-color:var(--cb-active)}
.cb-root .cb-mod-itemhead{display:flex;gap:8px;align-items:baseline;min-width:0;font-size:12px}
.cb-root .cb-mod-itemhead .cb-mod-ellip{flex:1 1 auto}
.cb-root .cb-mod-tags{display:flex;flex-wrap:wrap;gap:4px 6px;min-width:0}
.cb-root .cb-mod-tag{padding:0 6px;border:1px solid var(--cb-stroke-strong);font-size:11px;line-height:17px;color:var(--cb-fg-dim);white-space:nowrap}
.cb-root .cb-mod-tag--pwr{border-color:color-mix(in oklab,var(--cb-power) 55%,var(--cb-stroke-strong))}
.cb-root .cb-mod-tag--warn{border-color:var(--cb-warn);color:var(--cb-warn-text)}
.cb-root .cb-mod-dhead{display:grid;gap:6px;margin-bottom:10px}
.cb-root .cb-mod-dgrid{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:4px 16px}
.cb-root .cb-mod-sec{margin-top:10px;min-width:0}
.cb-root .cb-mod-pins{width:100%;border-collapse:collapse;font-size:12px;margin-top:4px}
.cb-root .cb-mod-pins td{padding:2px 6px 2px 0;vertical-align:baseline;border-bottom:1px dashed var(--cb-stroke);overflow-wrap:anywhere}
.cb-root .cb-mod-pins .cb-mod-nw{white-space:nowrap;overflow-wrap:normal}
.cb-root .cb-mod-dcol,.cb-root .cb-mod-rail{display:grid;gap:2px;align-content:start;min-width:0}
.cb-root .cb-mod-fact{display:grid;grid-template-columns:60px minmax(0,1fr);gap:8px;align-items:baseline;font-size:12px;line-height:1.5;margin-top:3px}
.cb-root .cb-mod-srcrow{margin-top:12px}
.cb-root .cb-mod-addbox{margin:2px 0 4px;padding:10px;border:1px dashed var(--cb-stroke-strong);display:grid;gap:6px}
.cb-root .cb-mod-inline{display:flex;gap:8px;align-items:center;font-size:12px;min-width:0;overflow-wrap:anywhere}
.cb-root .cb-mod-inline select{padding:3px 6px}
.cb-root .cb-mod-addrow{display:flex;align-items:center;gap:12px;justify-content:space-between}
.cb-root .cb-mod-addrow .cb-mod-note{margin:0}
.cb-root .cb-mod-addrow > button{flex:none}
.cb-root .cb-mod-bus{margin-top:12px}
.cb-root .cb-mod-head{flex-wrap:wrap;row-gap:2px}
.cb-root .cb-mod-head > *{white-space:nowrap}
.cb-root .cb-mod-busbox{margin-top:6px;padding-bottom:6px;border-bottom:1px dashed var(--cb-stroke-strong);display:grid;gap:2px}
.cb-root .cb-mod-rails,.cb-root .cb-mod-reqs{margin-top:10px;display:grid;gap:6px}
.cb-root .cb-mod-railhead{display:flex;flex-wrap:wrap;gap:0 8px;align-items:baseline;font-size:12px}
.cb-root .cb-mod-meter{position:relative;height:6px;margin:3px 0;border:1px solid var(--cb-stroke-strong);overflow:hidden}
.cb-root .cb-mod-meter i{position:absolute;inset:0 auto 0 0;background:var(--cb-ok)}
.cb-root .cb-mod-meter--warn i{background:var(--cb-warn)}
.cb-root .cb-mod-meter--bad i{background:var(--cb-bad)}
.cb-root .cb-mod-meter--none{border-style:dashed;background:none}
.cb-root .cb-mod-grp td{padding-top:7px;white-space:normal;cursor:pointer;border-bottom-style:solid}
.cb-root .cb-mod-grp:hover td{background:color-mix(in oklab,var(--cb-fg) 5%,transparent)}
.cb-root .cb-mod-grphead{display:flex;gap:8px;align-items:baseline;min-width:0;font-size:12px}
.cb-root .cb-mod-grphead span{flex:none;margin-left:auto}
.cb-root .cb-mod-grpbtn{flex:1 1 auto;font-weight:700}
.cb-root .cb-mod-fd>summary{cursor:pointer;grid-template-columns:14px minmax(0,1fr) 10px}
.cb-root .cb-mod-fd>summary::after{content:'▸';color:var(--cb-fg-dim)}
.cb-root .cb-mod-fd[open]>summary::after{content:'▾'}
.cb-root .cb-mod-fd .cb-mod-note{margin:2px 0 4px 22px}
`)
