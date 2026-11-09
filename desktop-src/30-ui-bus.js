// Card `// buses`: devices (+N); findings one line (symbol, word, refs; text folded, 3 + "show all");
// passed/not checked folded; rails as bars; required parts; one agent button

const modSym = s => h('span', { className: 'cb-mod-sym', 'aria-hidden': 'true' }, s)
const modCalcLink = (calc, pre, onClick) => h('button', { type: 'button', className: 'cb-mod-link', 'data-cb': `${pre}-calc-${calc}`,
  title: `Open the ${calc.replace(/_/g, ' ')} calculator in CALC`, onClick }, 'calc ›')
const modRailLook = f => (f === null ? null : f > 1 ? ['bad', '⊗', 'over limit'] : f > 0.8 ? ['warn', '◇', 'near limit'] : ['ok', '✓', 'ok'])
// folded row: symbol, word, rest; body on open
const modFold = (tone, sym, word, rest, body) => h('details', { className: 'cb-mod-fd' },
  h('summary', { className: `cb-mod-row cb-mod-row--f cb-mod-row--${tone}` }, modSym(sym),
    h('span', { className: 'cb-mod-ellip', 'data-cb-truncate-ok': 'true', title: rest ? `${word} ${rest}` : word }, h('b', null, word), rest ? h('span', { className: 'cb-mod-dim' }, ` ${rest}`) : null)),
  body)
const modFindingRow = (w, i) => h('li', { key: `${w.code}-${i}`, 'data-cb': 'mod-finding', 'data-cb-code': w.code },
  modFold(w.tone, w.symbol, w.word, (w.refs || []).join(' '), h('p', { className: 'cb-mod-note cb-mod-dim' }, w.message)))

function BusCard({ modules, findings = null }) {
  const buses = Array.isArray(modules?.buses) ? modules.buses : []
  const railsRaw = Array.isArray(modules?.rails) ? modules.rails : []
  if (!modules || (!buses.length && !railsRaw.length)) return null
  const shown = findings?.warnings || []
  const c = modules.counts || {}
  const seen = new Set([...shown.map(w => w.code), ...(c.hidden || []).map(x => String(x).split(' ')[0])])
  const checks = (findings?.checks || []).filter(x => !seen.has(`mod_${String(x.id).slice(8).replace(/\./g, '_')}`))
  const more = (c.findings ?? 0) - (c.shown ?? shown.length)
  const hidden = modHidden(c.hidden)
  const ids = [...new Set(shown.flatMap(w => w.source_ids || []))]
  const rails = modRails({ ok: true, result: { modules } })
  const nf = c.findings ?? shown.length
  return h('section', { className: 'cb-card cb-bracket cb-mod-bus', 'data-cb': 'insp-buses', 'aria-label': 'Buses' },
    h('div', { className: 'cb-card-head cb-mod-head' }, h(Label, null, '// buses'),
      h(Label, { className: 'cb-push' }, `${c.modules ?? '?'} module${c.modules === 1 ? '' : 's'} · ${nf} finding${nf === 1 ? '' : 's'}`)),
    buses.map(b => {
      const segs = (b.segments || []).length ? b.segments : b.more ? [{ id: 'main', devices: [], more: b.more }] : []
      return h('div', { key: b.id, className: 'cb-mod-busbox', 'data-cb': 'mod-bus', 'data-cb-bus': b.id },
        h('div', { className: 'cb-mod-row cb-mod-row--2' }, h('b', null, modInterfaceLabel(b.type)),
          h('span', null, Object.entries(b.gpios || {}).map(([k, v]) => `${k} IO${v}`).join(' · '),
            b.f_max_hz ? h('span', { className: 'cb-mod-dim' }, ` · ≤ ${modSI(b.f_max_hz, 'Hz')}`) : null)),
        segs.map(s => h('div', { key: s.id, className: 'cb-mod-row cb-mod-row--2', 'data-cb': 'mod-seg' },
          h('span', { className: 'cb-mod-k' }, (segs.length > 1 || s.id !== 'main') ? `seg ${s.id}` : 'devices'),
          h('span', { 'data-cb': 'mod-devices' }, [...(s.devices || []).map(d => [d.ref, d.address].filter(Boolean).join(' ')),
            s.more ? `+${s.more} device${s.more === 1 ? '' : 's'}` : ''].filter(Boolean).join(' · ')))))
    }),
    h('ul', { className: 'cb-mod-list', 'data-cb': 'mod-findings' },
      shown.slice(0, 3).map(modFindingRow),
      shown.length > 3 ? h('li', { key: 'all', 'data-cb': 'mod-all' }, modFold('dim', '+', `show all ${shown.length}`, '',
        h('ul', { className: 'cb-mod-list' }, shown.slice(3).map((w, i) => modFindingRow(w, i + 3))))) : null,
      more > 0 ? h('li', { key: 'more', className: 'cb-mod-row cb-mod-row--f cb-mod-row--dim', 'data-cb': 'mod-hidden' }, modSym('+'),
        h('span', null, h('b', null, `${more} more`), hidden.length ? ` hidden: ${hidden.join(' · ')}` : ' not listed')) : null,
      [['ok', '✓', 'passed'], ['dim', '○', 'not checked']].map(([tone, sym, word]) => {
        const list = checks.filter(x => x.tone === tone)
        return list.length ? h('li', { key: tone, 'data-cb': `mod-${tone === 'ok' ? 'passed' : 'open'}` },
          modFold(tone, sym, `${list.length} ${word}`, '', h('p', { className: 'cb-mod-note cb-mod-dim' },
            list.map(x => modWarningWord(x.id)).join(' · ')))) : null
      })),
    rails.length ? h('div', { className: 'cb-mod-rails', 'data-cb': 'mod-rails' }, h(Label, null, '// rails'), rails.map(r => {
      const look = modRailLook(r.frac)
      const miss = railsRaw.find(x => x.net === r.net)?.missing || []
      const ge = miss.length ? '≥\u00a0' : ''
      return h('div', { key: r.net, className: 'cb-mod-rail', 'data-cb': 'mod-rail', 'data-cb-net': r.net },
        h('div', { className: 'cb-mod-railhead' }, h('b', null, r.net), h('span', { className: 'cb-mod-dim' }, r.volts),
          h('span', { className: `cb-mod-push${look ? ` cb-mod-t-${look[0]}` : ' cb-mod-dim'}` },
            look ? `${look[1]} ${Math.round(r.frac * 100)} % · ${look[2]}` : 'no limit known')),
        h('div', { className: `cb-mod-meter${look ? ` cb-mod-meter--${look[0]}` : ' cb-mod-meter--none'}`, role: look ? 'meter' : undefined,
          'aria-label': look ? `${r.net} peak ${r.peak} of ${r.limit}: ${look[2]}` : `${r.net}: no limit known`, 'aria-valuenow': look ? Math.round(r.frac * 100) : undefined },
        look ? h('i', { style: { width: `${Math.min(100, r.frac * 100)}%` } }) : null),
        h('div', { className: 'cb-mod-dim cb-mod-nums' }, modKeep([['typ', r.typ], ['max', r.max], ['peak', r.peak]].filter(([, v]) => v && v !== '—').map(([k, v]) => `${k}\u00a0${ge}${v}`)
          .concat(r.limit ? [`limit ${r.limit}${r.limitSource ? ` (${r.limitSource})` : ''}`] : []).join(' · '))),
        miss.length ? h('div', { className: 'cb-mod-dim cb-mod-nums', 'data-cb': 'mod-rail-missing' }, `? partial: ${miss.join(', ')} ${miss.length === 1 ? 'has' : 'have'} no data`) : null)
    })) : null,
    h(BusRequires, { refs: buses.flatMap(b => (b.segments || []).flatMap(s => (s.devices || []).map(d => d.module))), checks: findings?.checks || [], warns: shown }),
    shown.some(w => w.severity !== 'info') ? h(BusAsk, { shown }) : null,
    ids.length ? h('div', { className: 'cb-card-foot' }, h(SourceLine, { sources: findings?.sources || [], ids })) : null)
}

// required parts; tone of the strongest mod_required_parts warning, else of the check
function BusRequires({ refs, checks, warns = [] }) {
  const project = sdk.useValue($project)
  const ids = [...new Set([...refs, ...moduleInstances(project).map(i => i.module)].filter(Boolean))]
  const infos = useModuleInfos(ids)
  const w = warns.find(x => x.code === 'mod_required_parts')
  const st0 = modStatusMeta(checks.find(x => x.id === 'modules.required_parts')?.status)
  const st = w ? { symbol: w.symbol, word: w.level, tone: w.tone } : st0.tone === 'bad' ? { symbol: '◇', word: 'finding', tone: 'warn' } : st0
  const reqs = []
  for (const id of ids) for (const r of infos[id]?.requires || []) {
    if (!reqs.some(x => x.r.code === r.code && x.id === id)) reqs.push({ id, r, calc: modRequireCalc(r, infos[id]) })
  }
  if (!reqs.length) return null
  // folded by default: the module rows of the table stay in view
  return h('details', { className: 'cb-mod-reqs', 'data-cb': 'mod-requires' },
    h('summary', { className: 'cb-card-head cb-mod-head' }, h(Label, null, `// required parts · ${reqs.length}`), h(Label, { className: `cb-push cb-mod-t-${st.tone}` }, `${st.symbol} ${st.word}`)),
    h('ul', { className: 'cb-mod-list' }, reqs.map(({ id, r, calc }) => h('li', { key: `${id}-${r.code}`, className: 'cb-mod-row cb-mod-row--r', title: modEvidence(r) || undefined },
      modSym('+'),
      h('span', null, h('b', null, id), ` ${modRequireText(r)}`, r.page != null ? h('span', { className: 'cb-mod-page' }, ` p. ${r.page}`) : null),
      calc ? modCalcLink(calc, 'mod', e => openCalc(calc, e.currentTarget)) : h('span')))))
}

// agent action: findings as a composer draft (not sent)
function BusAsk({ shown }) {
  const project = sdk.useValue($project)
  const ask = () => composeDraft(`Bench project ${project?.id}: fix these module findings (bench_project connect/add_module, then bench_pins check):\n${shown.map(w => `- ${w.word}: ${w.message}`).join('\n')}`)
  return h('div', { className: 'cb-actions' }, h(Btn, { kind: 'agent', size: 'sm', 'data-cb': 'mod-ask', title: 'Draft a fix request in the chat (not sent)', onClick: ask }, 'Fix with Hermes'))
}

function BusPanel() {
  const { modules, findings } = useModuleCheck()
  return h(BusCard, { modules, findings })
}
