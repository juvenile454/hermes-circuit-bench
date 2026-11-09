// h(type, props, ...children): small helper over jsx/jsxs (no JSX syntax in disk plugins).
// Falsy children (null, undefined, false, true) are dropped; nested arrays are flattened.
// Give list items an explicit `key`; it is passed to jsx() as the key argument, never spread inside props.
export function h(type, props, ...children) {
  const p = {}
  let key
  if (props) {
    for (const k of Object.keys(props)) {
      if (k === 'key') key = props[k] === undefined || props[k] === null ? undefined : String(props[k])
      else p[k] = props[k]
    }
  }
  const kids = children.flat(Infinity).filter(c => c !== null && c !== undefined && c !== false && c !== true)
  if (kids.length === 1) p.children = kids[0]
  else if (kids.length > 1) p.children = kids
  return kids.length > 1 ? jsxs(type, p, key) : jsx(type, p, key)
}
