// Catalog banner (scripts/banner/banner.mjs): the board is the app's board model drawn by lib/art-board.js with the
// PLAN inputs, the page loads nothing from the network, the figure assets match mercury.json, the IO14 label sits
// under the trace end next to the board, and the build is deterministic. The rendered layout is
// checked in the page itself when the desktop test harness renders it.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildBanner, bannerBoard, BANNER_SIZE } from '../scripts/banner/banner.mjs'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const BANNER = join(ROOT, 'scripts', 'banner')
const pngSize = f => { const b = readFileSync(f); return [b.readUInt32BE(16), b.readUInt32BE(20)] }

const { html, meta } = await buildBanner({ root: ROOT })

test('the board is the art-board.js drawing of the S3 DevKitC-1 with the demo project', async () => {
  const board = await bannerBoard(ROOT)
  assert.match(board.svg, /^<svg /)
  assert.ok(html.includes(board.svg.slice(board.svg.indexOf('>') + 1, board.svg.indexOf('>') + 400)), 'banner embeds the generated board SVG')
  assert.match(html, />ESP32-S3</)
  assert.match(html, /WROOM-1 · N16R8/)
  assert.deepEqual(board.roles, { 14: 'LASER', 2: 'BUTTON', 8: 'SDA', 9: 'SCL', 1: 'VBAT' })
  assert.equal(board.pads[14].side, 'left')
  assert.equal(board.pads[14].state, 'assigned')
  assert.match(html, /data-fit="pin">IO14 · LASER</)
})

test('the page loads nothing from the network and credits the photo', () => {
  assert.doesNotMatch(html, /(?:src|href|srcset)\s*=\s*["'][^"']*https?:/i)
  assert.doesNotMatch(html, /url\(\s*["']?https?:/i)
  assert.doesNotMatch(html, /@import/)
  assert.match(html, /MERCURY AFTER GIAMBOLOGNA · PHOTO RIJKSMUSEUM, CC0/)
  for (const f of ['mercury@1x.png', 'mercury@2x.png']) assert.ok(html.includes(`/scripts/banner/${f}`), f)
})

test('figure assets match mercury.json (1x and a real 2x file) and sit inside the frame', () => {
  const fig = JSON.parse(readFileSync(join(BANNER, 'mercury.json'), 'utf8'))
  assert.deepEqual(pngSize(join(BANNER, 'mercury@1x.png')), [fig.css_w, fig.css_h])
  assert.deepEqual(pngSize(join(BANNER, 'mercury@2x.png')), [fig.css_w * 2, fig.css_h * 2])
  assert.equal(fig.retouched, true)
  const [W, H] = BANNER_SIZE
  assert.ok(meta.figure.x >= 16 && meta.figure.y >= 16 && meta.figure.y + fig.css_h <= H - 16 && meta.figure.x + fig.css_w < W / 2)
  assert.ok(meta.tip[0] > meta.figure.x && meta.tip[1] >= meta.figure.y, 'the signal starts at the fingertip')
})

test('IO14 label: under the trace end, right-aligned next to the board, board inside the frame', () => {
  const [W, H] = BANNER_SIZE
  const { board, pad14, label } = meta
  assert.ok(board.x >= 16 && board.y >= 16 && board.x + board.w <= W - 16 && board.y + board.h <= H - 16)
  assert.ok(pad14[0] > board.x && pad14[0] < board.x + board.w / 3, 'pad on the left header')
  assert.ok(label.top > pad14[1], 'label below the stub into the pad')
  const rightEdge = W - label.right
  assert.ok(rightEdge < board.x && board.x - rightEdge <= 12, `label right edge ${rightEdge} next to the board at ${board.x}`)
})

test('deterministic', async () => {
  assert.equal((await buildBanner({ root: ROOT })).html, html)
})
