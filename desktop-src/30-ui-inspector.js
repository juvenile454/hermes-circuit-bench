// Inspector: verdict + stamp, one sentence of reason, the way out (alternatives as chips), pin functions, modes and
// the src › line in the card foot. The audit root
// "inspector" is the station's aside [data-cb=insp] (fallback of the visual audit script), so every card in it counts.

function entrySources(envs, ids) {
  const seen = new Map()
  for (const env of envs) for (const s of env?.sources || []) if (!seen.has(s.id)) seen.set(s.id, s)
  const want = [...new Set(ids.filter(Boolean))] // the rule's source may be the DevKit guide itself
  const list = want.length ? want.map(id => seen.get(id)).filter(Boolean) : []
  return list.length ? list : [...seen.values()].filter(s => /gpio|devkit/i.test(`${s.id} ${s.title}`)).slice(0, 1)
}

function Inspector({ rows, board, layoutState, mapState, checkState, onAssign }) {
  const view = sdk.useValue($view)
  const info = sdk.useValue($info)
  const sug = sdk.useValue($suggest)
  const gpio = view.selected
  const base = mapByGpio(mapState.env?.ok ? mapState.env.result : null)
  if (gpio === null || gpio === undefined) return h(InspectorIdle, { rows, checkState })
  const used = rows.find(r => r.pin === gpio) || null
  const entry = used && used.checked ? used : base.get(gpio) || null
  const infoRes = info.gpio === gpio && info.env?.ok ? info.env.result : null
  const verdict = used ? used.verdict : entry?.verdict ?? null
  const v = verdictMeta(verdict)
  const header = entry?.header || infoRes?.header || null
  const hs = splitHeader(header)
  const reason = mainReason(used && used.checked ? used : entry) || (infoRes?.rules || []).find(r => r.applies) || null
  const functions = infoRes?.functions || entry?.functions || []
  const sources = entrySources([checkState.env, mapState.env, info.env], [reason?.source_id, layoutState.layout?.source_id])
  const alts = used && verdict !== 'ok'
    ? (sug.role === used.role && sug.env?.ok ? suggestionChips(sug.env.result, used.role).map(s => s.gpio) : used.alternatives || [])
    : []
  const stampTone = verdict === 'blocked' ? 'bad' : verdict === 'caution' ? 'warn' : verdict === 'ok' ? (used ? 'active' : 'ok') : 'none'
  const stampText = verdict === 'ok' && !used ? 'FREE' : verdict === 'ok' ? 'ASSIGNED' : v.stamp
  const modes = infoRes?.modes && typeof infoRes.modes === 'object' ? Object.entries(infoRes.modes) : []
  const move = a => assignPin({ role: used.role, mode: used.mode, pin: a, net: used.net }).then(env => { if (env?.ok) selectPin(a) })
  // order: verdict, one sentence of reason, then the way out (alternatives as chips), then the details;
  // the source sits in the card foot
  return h('div', { className: `cb-card cb-insp-card cb-bracket${verdict === 'blocked' ? ' cb-bracket--bad' : ''}`, 'data-cb': 'inspector', 'data-cb-gpio': gpio },
    h('div', { className: 'cb-card-head' }, h(Label, null, `// inspector${hs ? ` · ${/^J\d+$/.test(hs.header) ? hs.header : `${hs.header} header,`} pin ${hs.n}` : ''}`),
      h('span', { className: 'cb-card-tools' },
        used ? [
          h('button', { key: 'e', type: 'button', className: 'cb-iconbtn', 'data-cb': 'edit-assignment', title: `Edit ${used.role}`,
            onClick: () => onAssign({ role: used.role, mode: used.mode, pin: used.pin, net: used.net || '' }) }, 'edit'),
          h('button', { key: 'u', type: 'button', className: 'cb-iconbtn', 'data-cb': 'unassign', title: `Remove ${used.role} from GPIO${gpio}`,
            onClick: () => unassignRole(used.role) }, 'unassign')
        ] : null,
        h('button', { type: 'button', className: 'cb-iconbtn', title: 'Close inspector', 'aria-label': 'Clear selection',
          onClick: () => selectPin(null) }, '✕'))),
    h('div', { className: 'cb-verdict' },
      h('span', { className: `cb-big cb-${verdict === 'ok' && used ? 'active' : v.tone === 'none' ? 'dim' : v.tone}` }, gpioName(gpio)),
      h(Stamp, { tone: stampTone, 'data-cb': 'verdict-stamp' }, `${stampText}${verdict && verdict !== 'ok' ? ` ${v.symbol}` : ''}`)),
    h('p', { className: 'cb-why', 'data-cb': 'inspector-why' },
      used ? [h('span', { key: 'a' }, verdict === 'blocked' ? 'Requested for ' : 'Assigned to '), h('b', { key: 'b' }, used.role), ' ',
        h('span', { key: 'm', className: 'cb-nowrap' }, `(${modeLabel(used.mode)}${used.net ? `, net ${used.net}` : ''}).`), ' ']
        : verdict === null ? 'Not checked yet. ' : verdict === 'ok' ? 'Free pin. ' : 'Free pin, with a finding. ',
      reason ? reason.message : verdict === 'ok' ? 'No findings for this board.' : verdict === null ? 'The pin map is not available.' : ''),
    alts.length ? h('div', { className: 'cb-insp-way', 'data-cb': 'insp-way' },
      h(Label, null, `use instead · ${modeLabel(used.mode)}`),
      h('div', { className: 'cb-alts', 'data-cb': 'alternatives' }, alts.map(a => h('button', { key: a, type: 'button', className: 'cb-chipbtn cb-altchip',
        'data-cb': `alt-${a}`, title: `Move ${used.role} to GPIO${a}`, 'aria-label': `Use GPIO${a} for ${used.role}`, onClick: () => move(a) },
      h(Glyph, { state: 'free', decorative: true }), h('span', null, 'Use '), h('b', null, `GPIO${a}`)))))
      : null,
    used && verdict !== 'ok' && !alts.length ? h('div', { className: 'cb-actions' },
      h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'suggest-one', title: `Find free pins for ${used.role} (pin rules, no hardware)`, onClick: () => suggestPins(rows, used.role) }, 'Suggest pins')) : null,
    used ? null : h('div', { className: 'cb-actions' },
      h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'assign-open', onClick: () => onAssign({ role: '', mode: 'out', pin: gpio, net: '' }) }, 'Assign role')),
    functions.length ? h('div', { className: 'cb-fn', 'data-cb': 'pin-functions' }, functions.map(f => h('span', { key: f, className: 'cb-tag' }, f))) : null,
    modes.length ? h(ModeSummary, { modes }) : null,
    h('div', { className: 'cb-card-foot' }, h(SourceLine, { sources })))
}

/** Modes on this board, compact: one line when every mode has the same verdict, else only the exceptions. */
function ModeSummary({ modes }) {
  const groups = { ok: [], caution: [], blocked: [], other: [] }
  for (const [m, v] of modes) (groups[v] || groups.other).push(m)
  const line = (tone, sym, text, key) => h('div', { key, className: `cb-${tone}` }, `${sym} ${text}`)
  const all = (v, n) => n === modes.length
  const out = []
  if (all('blocked', groups.blocked.length)) out.push(line('bad', '✕', 'blocked in every mode', 'b'))
  else if (all('ok', groups.ok.length)) out.push(line('ok', '✓', 'ok in every mode', 'o'))
  else {
    if (groups.blocked.length) out.push(line('bad', '✕', groups.blocked.map(modeLabel).join(' · '), 'b'))
    if (groups.caution.length) out.push(line('warn', '!', groups.caution.map(modeLabel).join(' · '), 'c'))
    if (groups.ok.length) out.push(line('ok', '✓', groups.ok.length > 6 ? `${groups.ok.length} other modes ok` : groups.ok.map(modeLabel).join(' · '), 'o'))
  }
  return h('div', { className: 'cb-modes-sum', 'data-cb': 'pin-modes' }, h(Label, null, 'modes'), h('div', null, out))
}

function InspectorIdle({ rows, checkState }) {
  const env = checkState.env
  const c = countVerdicts(rows)
  return h('div', { className: 'cb-card cb-insp-card cb-bracket', 'data-cb': 'inspector-idle' },
    h('div', { className: 'cb-card-head' }, h(Label, null, '// inspector')),
    h('p', { className: 'cb-why' }, 'Select a pin on the board to see its verdict, functions and source.'),
    env?.ok ? h('p', { className: 'cb-dim', style: { margin: '8px 0 0', lineHeight: 1.6 } }, env.summary) : null,
    rows.length && !c.blocked && !c.caution ? h('p', { className: 'cb-ok', style: { margin: '8px 0 0' } }, `✓ All ${rows.length} assignments are ok for this board.`) : null,
    env?.ok ? h('div', { className: 'cb-card-foot' }, h(SourceLine, { sources: env.sources?.slice(0, 1) })) : null)
}
