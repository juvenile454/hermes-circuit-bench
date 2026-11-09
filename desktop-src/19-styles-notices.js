// Notice styles: the Bench's notice zone (30-ui-bench.js NoticeZone), a grid row under
// the HUD that only exists while a notice is shown (nothing covers the station; without notices the shell is as before).
CB_CSS_PARTS.push(`
.cb-root .cb-shell[data-cb-notes=yes]{grid-template-rows:52px auto minmax(0,1fr) var(--cb-cons-h);
  grid-template-areas:"hud hud hud" "rail note note" "rail main insp" "rail cons cons"}
.cb-root .cb-shell[data-cb-notes=yes][data-cb-insp=none]{grid-template-areas:"hud hud" "rail note" "rail main" "rail cons"}
@container cb (max-width:799px){.cb-root .cb-shell[data-cb-notes=yes]{grid-template-areas:"hud hud" "rail note" "rail main" "rail cons"}}
.cb-root .cb-notes{grid-area:note;display:grid;gap:4px;min-width:0;padding:6px 18px;border-bottom:1px solid var(--cb-stroke);background:var(--cb-bg)}
.cb-root .cb-shell:not([data-cb-notes=yes]) .cb-notes{position:absolute;width:1px;height:1px;padding:0;border:0;overflow:hidden;clip-path:inset(50%)}
.cb-root .cb-notice{display:grid;grid-template-columns:16px 64px minmax(0,1fr) auto;gap:8px;align-items:baseline;min-width:0;padding:4px 6px 4px 8px;
  border:1px solid var(--cb-stroke-strong);background:var(--cb-panel);font-size:12px;line-height:1.45}
.cb-root .cb-notice-sym{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border:1px solid currentColor;border-radius:2px;
  font-size:11px;font-weight:700;line-height:1;align-self:start;margin-top:1px}
.cb-root .cb-notice-w{font-size:10px;letter-spacing:.12em;text-transform:uppercase;font-weight:700}
.cb-root .cb-notice-t{color:var(--cb-fg);min-width:0;overflow-wrap:anywhere}
.cb-root .cb-notice-x{align-self:start;padding:0 4px;font-size:14px;line-height:18px;color:var(--cb-fg-dim)}
.cb-root .cb-notice-x:hover,.cb-root .cb-notice-x:focus-visible{color:var(--cb-fg)}
.cb-root .cb-notice--ok .cb-notice-sym,.cb-root .cb-notice--ok .cb-notice-w{color:var(--cb-ok-text)}
.cb-root .cb-notice--info .cb-notice-sym,.cb-root .cb-notice--info .cb-notice-w{color:var(--cb-fg-dim)}
.cb-root .cb-notice--warn{border-color:color-mix(in oklab,var(--cb-warn) 50%,transparent)}
.cb-root .cb-notice--warn .cb-notice-sym,.cb-root .cb-notice--warn .cb-notice-w{color:var(--cb-warn-text)}
.cb-root .cb-notice--bad{border-color:color-mix(in oklab,var(--cb-bad) 55%,transparent)}
.cb-root .cb-notice--bad .cb-notice-sym,.cb-root .cb-notice--bad .cb-notice-w{color:var(--cb-bad-text)}
.cb-root .cb-notice--bad .cb-notice-sym{background:color-mix(in oklab,var(--cb-bad) 14%,transparent)}
`)
