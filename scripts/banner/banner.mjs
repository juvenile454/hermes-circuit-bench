// Circuit Bench catalog banner, 1200×600 (plugin catalog `image`, 2:1). Concept "The messenger":
// Giambologna's Mercury (CC0 photo, figure/ pipeline → mercury@1x/@2x.png) sends one
// signal: fingertip → trace into the I of CIRCUIT → the lettering is the circuit → out of the H of BENCH → pad IO14
// (LASER) of the ESP32-S3-DevKitC-1. The board is the app's board model, drawn here by desktop-src/lib/art-board.js
// with the inputs of the PLAN station (real N16R8 pin map, demo project), never by hand.
//
// buildBanner() returns the page; the screenshot run of the desktop test harness writes it next to the screenshots
// and renders it offline at 1x/2x. The page checks itself and reports through <html data-*>:
// ready, error (overlap, outside the 16 px frame, label rules), font (loaded|fallback), layout (boxes).
// Query: font=<folder URL with JetBrainsMono-Regular.woff2 and -Bold.woff2> (Hermes Desktop's bundled face, read only).
//   node scripts/banner/banner.mjs [out.html]   writes the page for a look by hand (default $TMPDIR/cb-banner.html)
import { readFileSync, writeFileSync } from 'node:fs'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { tmpdir } from 'node:os'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = join(HERE, '..', '..')
export const BANNER_SIZE = [1200, 600]
const f1 = v => Number(v).toFixed(1)

/** The board of 01 PLAN as SVG: S3 DevKitC-1, pin map N16R8 with Wi-Fi, demo project assignments. `body` crops the
 *  pcb (the label columns of the app are DOM, not part of the SVG); pads = centres of the used GPIOs, SVG units. */
export async function bannerBoard(root = REPO) {
  const lib = ['art.js', 'board-geom.js', 'pins.js', 'art-board.js'].map(f => readFileSync(join(root, 'desktop-src', 'lib', f), 'utf8')).join('\n')
  const M = await import(`data:text/javascript;base64,${Buffer.from(lib).toString('base64')}`)
  const readJson = p => JSON.parse(readFileSync(join(root, p), 'utf8'))
  const layout = readJson('desktop-src/fixtures/board.esp32-s3-devkitc-1.json').result
  const pinMap = readJson('tests-js/fixtures/ui1-pins-maps.json')['pins.map/esp32s3/n16r8/wifi-on'].result
  const project = readJson('desktop-src/fixtures/project.laser-trigger.json').result.project
  const rows = M.mergeAssignments(project.assignments || project.pins, pinMap.pins)
  const used = new Map(rows.map(r => [r.pin, r]))
  const model = M.boardArtModel({ layout, chip: M.chipInfo('esp32s3'), variant: M.variantInfo('esp32s3', 'n16r8'), base: M.mapByGpio(pinMap), used, selected: null, suggest: [] })
  const tags = [...model.views.left, ...model.views.right].filter(s => s.view).map(s => M.boardTagW(s.view.tag))
  const g = M.boardGeom({ layout, width: 548, tagWidth: Math.ceil(Math.max(0, ...tags) / 8) * 8, mode: 'full' })
  const svg = M.artBoard(model, g, { prefix: 'bn', mode: 'full' })
  const pads = {}
  for (const side of ['left', 'right']) {
    (model.sides?.[side] || []).forEach((r, i) => {
      if (!r.pin) return
      const gp = layout[side].find(p => p.n === r.pin.n)
      if (gp && used.has(gp.gpio)) pads[gp.gpio] = { side, i, x: M.boardPadX(g, side), y: M.boardSlotY(g, i), state: r.pin.state }
    })
  }
  return { svg, body: [g.gutterL - 8, 0, g.bodyW + 16, g.height], pads, roles: Object.fromEntries(rows.map(r => [r.pin, r.role])) }
}

// trace lettering: polylines on a 4×6 grid, 45° chamfers, vias (drilled pads) at the free ends
const GLYPHS = {
  C: { w: 4, p: [[[4, 0], [1, 0], [0, 1], [0, 5], [1, 6], [4, 6]]], v: [[4, 0], [4, 6]] },
  I: { w: 0, p: [[[0, 0], [0, 6]]], v: [[0, 6]] },
  R: { w: 4, p: [[[0, 6], [0, 0], [3, 0], [4, 1], [4, 2], [3, 3], [0, 3]], [[2, 3], [4, 5], [4, 6]]], v: [[0, 6], [4, 6]] },
  U: { w: 4, p: [[[0, 0], [0, 5], [1, 6], [3, 6], [4, 5], [4, 0]]], v: [[0, 0], [4, 0]] },
  T: { w: 4, p: [[[0, 0], [4, 0]], [[2, 0], [2, 6]]], v: [[0, 0], [4, 0], [2, 6]] },
  B: { w: 4, p: [[[0, 3], [3, 3], [4, 4], [4, 5], [3, 6], [0, 6], [0, 0], [3, 0], [4, 1], [4, 2], [3, 3]]], v: [] },
  E: { w: 4, p: [[[4, 0], [0, 0], [0, 6], [4, 6]], [[0, 3], [3, 3]]], v: [[4, 0], [4, 6], [3, 3]] },
  N: { w: 4, p: [[[0, 6], [0, 0]], [[0, 1], [4, 5]], [[4, 6], [4, 0]]], v: [[0, 6], [4, 0]] },
  H: { w: 4, p: [[[0, 0], [0, 6]], [[4, 0], [4, 6]], [[0, 3], [4, 3]]], v: [[0, 0], [0, 6], [4, 0]] }
}
const U = 14
const GAP = 1.7
const STROKE = 9
function word(text, x0, y0) {
  let x = x0
  let d = ''
  const vias = []
  const at = []
  for (const ch of text) {
    const g = GLYPHS[ch]
    for (const pl of g.p) d += 'M' + pl.map(([gx, gy]) => `${f1(x + gx * U)} ${f1(y0 + gy * U)}`).join('L')
    for (const [gx, gy] of g.v) vias.push([x + gx * U, y0 + gy * U])
    at.push(x)
    x += (g.w + GAP) * U
  }
  return { d, vias, at, w: x - x0 - GAP * U }
}
const viaSvg = (vs, r = 5.8, hole = 2.3) => vs.map(([x, y]) => `<circle cx="${f1(x)}" cy="${f1(y)}" r="${r}" class="via"/><circle cx="${f1(x)}" cy="${f1(y)}" r="${hole}" class="drill"/>`).join('')

// self-check in the page (after fonts and images): no two boxes overlap, all inside the 16 px frame; the pin label
// sits under the trace end next to the board, away from the tools line (not too close to the copy)
const CHECK = `
  async function loadFont() {
    const dir = new URLSearchParams(location.search).get('font')
    if (!dir) return 'fallback'
    for (const [weight, file] of [['400', 'JetBrainsMono-Regular.woff2'], ['700', 'JetBrainsMono-Bold.woff2']]) {
      const face = new FontFace('JetBrains Mono', 'url("' + new URL(file, dir).href + '")', { weight })
      await face.load()
      document.fonts.add(face)
    }
    await document.fonts.ready
    return document.fonts.check('700 14px "JetBrains Mono"') && document.fonts.check('400 20px "JetBrains Mono"') ? 'loaded' : 'fallback'
  }
  ;(async () => {
    const root = document.documentElement
    try {
      root.dataset.font = await loadFont().catch(e => 'error: ' + (e && e.message || e))
      await Promise.all([...document.images].map(i => i.decode()))
      const box = {}
      for (const e of document.querySelectorAll('[data-fit]')) {
        const r = e.getBoundingClientRect()
        box[e.dataset.fit] = { x0: Math.round(r.left), y0: Math.round(r.top), x1: Math.round(r.right), y1: Math.round(r.bottom) }
      }
      const bad = []
      const names = Object.keys(box)
      for (const a of names) for (const b of names) {
        const p = box[a], q = box[b]
        if (a < b && p.x0 < q.x1 && q.x0 < p.x1 && p.y0 < q.y1 && q.y0 < p.y1) bad.push('overlap ' + a + '×' + b)
      }
      for (const n of names) if (box[n].x0 < 16 || box[n].y0 < 16 || box[n].x1 > innerWidth - 16 || box[n].y1 > innerHeight - 16) bad.push('outside frame ' + n)
      const { pin, tools, board } = box
      const pad = JSON.parse(root.dataset.pad)
      if (pin.y0 <= pad[1]) bad.push('pin label not under the trace end')
      if (board.x0 - pin.x1 < 0 || board.x0 - pin.x1 > 12) bad.push('pin label not next to the board (' + (board.x0 - pin.x1) + ' px)')
      if (pin.y0 - tools.y1 < 24) bad.push('pin label too close to the tools line (' + (pin.y0 - tools.y1) + ' px)')
      root.dataset.layout = JSON.stringify(box)
      if (bad.length) root.dataset.error = bad.join('; ')
    } catch (e) {
      root.dataset.error = String(e && e.message || e)
    }
    root.dataset.ready = 'true'
  })()`

/** The banner page. Assets (figure) are file URLs into this checkout; nothing else is loaded. */
export async function buildBanner({ root = REPO } = {}) {
  const [W, H] = BANNER_SIZE
  const fig = JSON.parse(readFileSync(join(HERE, 'mercury.json'), 'utf8'))
  const asset = f => pathToFileURL(join(HERE, f)).href
  const board = await bannerBoard(root)
  const [cx0, cy0, bw, bh] = board.body
  const boardSvg = board.svg.replace(/viewBox="[^"]+"/, `viewBox="${cx0} ${cy0} ${bw} ${bh}"`).replace(/ width="[\d.]+" height="[\d.]+"/, '')
  // the board keeps the app materials (MATERIAL) exactly; the pin states get a banner look, like the Phosphor and
  // Follow themes of the app vary them: free cyan-dim, assigned app cyan, caution app amber, blocked and power muted
  const TOK = await import(`data:text/javascript;base64,${Buffer.from(readFileSync(join(root, 'desktop-src/lib/tokens.js'), 'utf8')).toString('base64')}`)
  const vars = o => Object.entries(o).map(([k, v]) => `--cb-${k}: ${v};`).join(' ')
  const boardLook = `${vars(TOK.MATERIAL)} ${vars(TOK.PHOSPHOR)} --cb-ok: #1f9fc2; --cb-active: #2de2ff; --cb-warn: #ffc23d; --cb-bad: #6e8792; --cb-power: #9ccfe0;`

  // layout (CSS px)
  const FIG = { x: 46, y: 26, w: fig.css_w, h: fig.css_h }
  const tip = [FIG.x + fig.fingertip[0], FIG.y + fig.fingertip[1]]
  const BS = 1.068
  const BOARD = { w: bw * BS, h: bh * BS }
  BOARD.x = W - 50 - BOARD.w
  BOARD.y = Math.round((H - BOARD.h) / 2) + 2
  const P14 = [BOARD.x + (board.pads[14].x - cx0) * BS, BOARD.y + (board.pads[14].y - cy0) * BS]
  const TX = 332
  const TY1 = 78
  const TY2 = 192
  const w1 = word('CIRCUIT', TX, TY1)
  const w2 = word('BENCH', TX, TY2)

  // signal path
  const xI = w1.at[1] // the first I of CIRCUIT: a single vertical trace
  const yIn = tip[1]
  const x0In = tip[0] + 11 // the signal leaves the fingertip with a small gap (spark), not as an extension of it
  const sIn = `M${f1(x0In)} ${f1(yIn)}H${f1(xI - 14)}L${f1(xI)} ${f1(yIn + 14)}V${TY1}`
  const hx = w2.at[4] + 4 * U // right stem of the H
  const hy = TY2 + 6 * U
  const xV = BOARD.x - 30
  const sOut = `M${f1(hx)} ${f1(hy)}H${f1(xV - 14)}L${f1(xV)} ${f1(hy + 14)}V${f1(P14[1] - 14)}L${f1(xV + 14)} ${f1(P14[1])}H${f1(P14[0])}`
  const label = { top: P14[1] + 12, right: W - BOARD.x + 6 } // under the stub into the pad, next to the board

  // glory rays from the fingertip (behind everything, fade out before the board)
  let rays = ''
  const N = 64
  for (let i = 0; i < N; i++) {
    const deg = -14 + (62 * i) / (N - 1)
    const a = deg * Math.PI / 180
    const reach = Math.min((BOARD.x - 40 - tip[0]) / Math.cos(a), (H - 40 - tip[1]) / Math.max(0.01, Math.sin(a)), deg < 0 ? (tip[1] - 16) / Math.sin(-a) : 1e9)
    const len = reach * (0.55 + 0.45 * (((i * 7) % 5) / 4))
    rays += `<line x1="${f1(tip[0])}" y1="${f1(tip[1])}" x2="${f1(tip[0] + len * Math.cos(a))}" y2="${f1(tip[1] + len * Math.sin(a))}"/>`
  }

  const html = `<!doctype html>
<!-- Circuit Bench catalog banner, generated by scripts/banner/banner.mjs; do not edit. -->
<html lang="en" data-pad="${JSON.stringify(P14.map(v => Number(f1(v))))}"><head><meta charset="utf-8"><title>Circuit Bench — banner</title>
<style>
  :root {
    --bg: #04101a; --bg2: #08233a; --cyan: #22b4d8; --cyan-dim: #156d88; --yellow: #f2e634; --text: #dff4fa; --faint: #7898a6;
    /* fallback board tokens in the banner palette; #board below sets the app's own */
    --cb-pcb: #0a2232; --cb-pcb-edge: #24566d; --cb-silk: #b9d3de; --cb-metal: #39505d; --cb-metal-hi: #7f9cab; --cb-metal-ink: #0d1820;
    --cb-tin: #9fb1ba; --cb-plastic: #0a1822; --cb-plastic-edge: #2b4554; --cb-copper: #8d8446; --cb-cavity: #040b11;
    --cb-ok: #1f9fc2; --cb-active: #f2e634; --cb-warn: #3f7d92; --cb-bad: #6e8792; --cb-power: #9ccfe0;
    --cb-fg-dim: #6d8b99; --cb-fg-faint: #3b5361; --cb-ink: #04101a;
  }
  #board { ${boardLook} }
  :root {
    --mono: "JetBrains Mono", "DejaVu Sans Mono", ui-monospace, monospace;
  }
  * { box-sizing: border-box; margin: 0; padding: 0 }
  html, body { width: ${W}px; height: ${H}px; overflow: hidden; background: var(--bg) }
  body { position: relative; font-family: var(--mono); color: var(--text); -webkit-font-smoothing: antialiased }
  .layer { position: absolute; inset: 0 }
  .field { background: radial-gradient(ellipse 60% 80% at 22% 18%, var(--bg2) 0%, var(--bg) 70%), var(--bg) }
  .rule { background: repeating-linear-gradient(180deg, rgba(34,180,216,.03) 0 1px, transparent 1px 3px) }
  svg.art { position: absolute; left: 0; top: 0; width: ${W}px; height: ${H}px; overflow: visible }
  .rays line { stroke: var(--cyan); stroke-width: .7; stroke-opacity: .2 }
  .sig { fill: none; stroke: var(--yellow); stroke-width: ${STROKE}; stroke-linejoin: round; stroke-linecap: round }
  .sig-thin { fill: none; stroke: var(--yellow); stroke-width: 3; stroke-linejoin: round; stroke-linecap: round }
  .glow { fill: none; stroke: var(--yellow); stroke-width: ${STROKE + 12}; stroke-opacity: .09; stroke-linejoin: round; stroke-linecap: round }
  .via { fill: var(--yellow) } .drill { fill: var(--bg) }
  .frame { fill: none; stroke: var(--cyan); stroke-width: 2; stroke-dasharray: 2 4; stroke-opacity: .35 }
  .corner { fill: none; stroke: var(--cyan); stroke-width: 2; stroke-opacity: .8 }
  #fig { position: absolute; left: ${FIG.x}px; top: ${FIG.y}px; width: ${FIG.w}px; height: ${FIG.h}px }
  #board { position: absolute; left: ${f1(BOARD.x)}px; top: ${BOARD.y}px; width: ${f1(BOARD.w)}px; height: ${f1(BOARD.h)}px;
    filter: drop-shadow(0 0 22px rgba(34,180,216,.16)) }
  #board svg { width: 100%; height: 100% }
  /* the bench under the board, as in the app: faint grid and two HUD corners, so it sits instead of floating */
  .bench, .hud { position: absolute }
  .bench { left: ${f1(BOARD.x - 44)}px; top: ${BOARD.y - 30}px; width: ${f1(BOARD.w + 88)}px; height: ${f1(BOARD.h + 60)}px;
    background-image: linear-gradient(rgba(34,180,216,.11) 1px, transparent 1px), linear-gradient(90deg, rgba(34,180,216,.11) 1px, transparent 1px);
    background-size: 12px 12px; background-position: -1px -1px;
    -webkit-mask-image: radial-gradient(ellipse 62% 58% at 50% 50%, #000 62%, transparent 100%) }
  .hud { left: ${f1(BOARD.x - 14)}px; top: ${BOARD.y - 14}px; width: ${f1(BOARD.w + 28)}px; height: ${f1(BOARD.h + 28)}px }
  .hud::before, .hud::after { content: ""; position: absolute; width: 18px; height: 18px; border: 2px solid rgba(34,180,216,.8) }
  .hud::before { left: 0; top: 0; border-right: 0; border-bottom: 0 }
  .hud::after { right: 0; bottom: 0; border-left: 0; border-top: 0 }
  .t { position: absolute; left: ${TX}px; white-space: nowrap }
  .kicker { top: 306px; font-size: 14px; letter-spacing: 4.2px; color: var(--cyan); font-weight: 700 }
  .claim { top: 340px; font-size: 20px; line-height: 31px; color: var(--text) }
  .tools { top: 418px; font-size: 14px; letter-spacing: 1.4px; color: #63d3ee }
  .tools i { color: var(--yellow); font-style: normal }
  .pin { top: ${f1(label.top)}px; left: auto; right: ${f1(label.right)}px; font-size: 14px; letter-spacing: 1.6px; color: var(--yellow); font-weight: 700 }
  .plate { top: 556px; font-size: 9.5px; letter-spacing: 2.2px; color: var(--faint) }
  .scan { background: repeating-linear-gradient(180deg, transparent 0 2px, rgba(0,0,0,.14) 2px 3px); pointer-events: none } /* ground only: lines would comb the figure's fingers and face */
</style></head>
<body>
  <div class="layer field"></div>
  <div class="layer rule"></div>
  <svg class="art" viewBox="0 0 ${W} ${H}" aria-hidden="true">
    <g class="rays">${rays}</g>
    <rect class="frame" x="14" y="14" width="${W - 28}" height="${H - 28}"/>
    <path class="corner" d="M14 38V14H38M${W - 38} 14H${W - 14}V38M${W - 14} ${H - 38}V${H - 14}H${W - 38}M38 ${H - 14}H14V${H - 38}"/>
  </svg>
  <div class="layer scan"></div>
  <img id="fig" src="${asset('mercury@1x.png')}" srcset="${asset('mercury@1x.png')} 1x, ${asset('mercury@2x.png')} 2x" alt="" data-fit="figure">
  <div class="bench"></div>
  <div class="hud"></div>
  <div id="board" data-fit="board">${boardSvg}</div>
  <svg class="art" viewBox="0 0 ${W} ${H}" aria-hidden="true">
    <defs><radialGradient id="spark"><stop offset="0" stop-color="#f2e634" stop-opacity=".55"/><stop offset="1" stop-color="#f2e634" stop-opacity="0"/></radialGradient></defs>
    <path class="glow" d="${w1.d}${w2.d}"/>
    <path class="glow" d="${sIn}${sOut}" style="stroke-width:12"/>
    <path class="sig-thin" d="${sIn}"/>
    <path class="sig-thin" d="${sOut}"/>
    <path class="sig" d="${w1.d}${w2.d}" data-fit="title"/>
    ${viaSvg([...w1.vias, ...w2.vias])}
    ${viaSvg([[x0In, yIn], [xI - 14, yIn], [xV - 14, hy]], 4.5, 1.8)}
    <circle cx="${f1(tip[0] + 1)}" cy="${f1(tip[1] + 1)}" r="9" fill="url(#spark)"/>
    <circle cx="${f1(P14[0])}" cy="${f1(P14[1])}" r="11" fill="none" stroke="var(--yellow)" stroke-width="2"/>
    <circle cx="${f1(P14[0])}" cy="${f1(P14[1])}" r="17" fill="none" stroke="var(--yellow)" stroke-width="1" stroke-opacity=".4"/>
  </svg>
  <div class="t kicker" data-fit="kicker">A HERMES DESKTOP PLUGIN</div>
  <div class="t claim" data-fit="claim">An ESP32 workbench for Hermes:<br>from pin choice to running firmware.</div>
  <div class="t tools" data-fit="tools">pins <i>·</i> parts <i>·</i> solder <i>·</i> flash <i>·</i> debug</div>
  <div class="t pin" data-fit="pin">IO14 · ${board.roles[14]}</div>
  <div class="t plate" data-fit="plate">MERCURY AFTER GIAMBOLOGNA · PHOTO RIJKSMUSEUM, CC0</div>
<script>${CHECK}
</script>
</body></html>
`
  return { html, meta: { board: BOARD, pad14: P14, label, tip, pads: board.pads, roles: board.roles, figure: FIG } }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const out = resolve(process.argv[2] || join(tmpdir(), 'cb-banner.html'))
  const { html, meta } = await buildBanner()
  writeFileSync(out, html)
  console.log(out, JSON.stringify({ board: meta.board, pad14: meta.pad14, label: meta.label }))
}
