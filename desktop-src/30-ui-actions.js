// Bench → agent: put a structured prompt into the composer. Never sends; the user presses Enter.

async function composeDraft(text) {
  const host = sdk.host
  const setDraft = host?.composer?.setDraft
  const sleepMs = ms => new Promise(resolve => setTimeout(resolve, ms))
  if (typeof setDraft === 'function') {
    try {
      if (await setDraft(null, text)) return 'draft'
      if (typeof host.newChat === 'function') {
        host.newChat()
        for (let i = 0; i < 20; i++) {
          await sleepMs(150)
          if (await setDraft('new', text)) {
            // the Bench stays visible beside the new chat (only as a tile; the route fallback would hide the chat)
            if (typeof host.openWorkspace === 'function') { await sleepMs(60); if (CB.mounts === 0) openBench({ beside: true }) }
            return 'draft'
          }
        }
      }
    } catch (e) {
      console.warn('[circuit-bench] setDraft failed', e)
    }
  }
  const copied = await CB.ctx?.os?.writeClipboard?.(text).catch?.(() => false)
  host?.notify?.({ kind: copied ? 'info' : 'warning', title: copied ? 'Prompt copied' : 'Could not reach the composer',
    message: copied ? 'Paste it into the chat to ask Hermes.' : 'Open a chat and try again.' })
  return copied ? 'clipboard' : 'failed'
}

function askHermesText(project, station, rows) {
  const s = stationInfo(station)
  const lines = [`Bench question: ${s.title.toLowerCase()} in "${project?.id ?? '?'}"`,  // short first line = session title
    `Circuit Bench — project "${project?.id ?? '?'}", station ${s.n} ${s.title.toUpperCase()}.`]
  if (project) {
    const b = project.board || {}
    lines.push(`Board: ${chipInfo(b.chip)?.label || b.chip || '?'}${b.variant ? ` ${String(b.variant).toUpperCase()}` : ''}${b.devkit ? ` on ${b.devkit}` : ''}, Wi-Fi ${project.options?.wifi === false ? 'off' : 'on'}.`)
  }
  const bad = (rows || []).filter(r => r.verdict === 'blocked' || r.verdict === 'caution')
  if (bad.length) {
    lines.push(`Findings: ${bad.map(findingText).join('; ')}.`)
  }
  lines.push('Use the bench tools (bench_project, bench_pins) to read the project, then help me with the next step. Ask before changing anything.')
  return lines.join('\n')
}

function fixWithHermesText(project, decode) {
  return fixDraftText(project, decode) // lib/crash.js (pure, tested)
}
