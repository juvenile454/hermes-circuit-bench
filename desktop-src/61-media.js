// Optional: own card for the MEDIA: SVG of bench_schematic in the chat, only when the host has
// TOOL_MEDIA_RENDERER_AREA (typeof === 'string'; v0.22.5 shows its built-in image). The SVG is inlined in bench
// colours (stroke = currentColor); anything unsafe or unreadable falls back to the host's own rendering.

function decodeDataSvg(url) {
  const m = /^data:image\/svg\+xml(;base64)?,(.*)$/s.exec(String(url || ''))
  if (!m) return null
  try {
    if (!m[1]) return decodeURIComponent(m[2])
    const bin = atob(m[2])
    const bytes = Uint8Array.from(bin, c => c.charCodeAt(0))
    return new TextDecoder('utf-8').decode(bytes)
  } catch {
    return null
  }
}

function resultObject(result) {
  if (result && typeof result === 'object') return result
  if (typeof result === 'string') { try { return JSON.parse(result) } catch { return null } }
  return null
}

function SchematicMediaCard(props) {
  const ui = sdk.useValue($ui)
  const [svg, setSvg] = useState(null)
  const [failed, setFailed] = useState(false)
  const file = props?.file
  useEffect(() => {
    let gone = false
    const run = async () => {
      try {
        const url = typeof file?.resolveUrl === 'function' ? await Promise.resolve(file.resolveUrl()) : null
        const text = decodeDataSvg(url)
        const safe = text ? sanitizeSvg(text) : { ok: false }
        if (!gone) { if (safe.ok) setSvg(safe.svg); else setFailed(true) }
      } catch {
        if (!gone) setFailed(true)
      }
    }
    run()
    return () => { gone = true }
  }, [file?.path])
  if (failed) return props?.fallback ?? null
  const res = resultObject(props?.result)
  const env = res?.action === 'schematic.render' ? res : res?.result?.action ? res.result : res
  const summary = env?.summary || (typeof props?.args?.block === 'string' ? props.args.block.replace(/_/g, ' ') : 'schematic')
  return h(Fragment, null, h(Styles, null),
    h('div', { className: 'cb-root cb-dcard cb-bracket cb-media', 'data-cb': 'media-card', 'data-cb-look': ui.look },
      h('div', { className: 'cb-dcard-head' }, h('span', { className: 'cb-brand cb-brand--sm' }, '◢ BENCH'), h(Label, null, '03 // WIRING'),
        h('span', { className: 'cb-dim cb-ellip' }, summary)),
      svg ? h('div', { className: 'cb-svg cb-svg--media', role: 'img', 'aria-label': summary, dangerouslySetInnerHTML: { __html: svg } })
        : h('div', { className: 'cb-loading', style: { padding: '8px 0' } }, 'loading schematic'),
      h('div', { className: 'cb-actions' }, h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'media-open', onClick: () => { goStation('wire'); openBench({ beside: true }) } }, 'Open in Bench ›'))))
}
