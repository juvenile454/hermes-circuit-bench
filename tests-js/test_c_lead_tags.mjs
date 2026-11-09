// On-board tags of the board view are whole words (found on the WT32-ETH01 in the PLAN screenshots).
import test from 'node:test'
import assert from 'node:assert/strict'
import { clipTag } from '../desktop-src/lib/pins.js'

test('on-board tags keep whole words up to 10 characters', () => {
  assert.equal(clipTag('Ethernet REF_CLK input from the 50 MHz oscillator'), 'ETHERNET')
  assert.equal(clipTag('LED3 serial activity LED (RXD2)'), 'LED3')
  assert.equal(clipTag('CFG pin, used for hardware factory reset'), 'CFG PIN')
  assert.equal(clipTag('485_EN, the RS485 enable pin'), '485_EN')
  assert.equal(clipTag('RGB LED'), 'RGB LED')
  assert.equal(clipTag('Boot button'), 'BOOT')
  assert.equal(clipTag('Supercalifragilistic'), 'SUPERCALIF')
})
