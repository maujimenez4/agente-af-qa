// Markdown en línea del modelo (PA-334), con un subconjunto seguro: negrita, cursiva y código. Nunca HTML:
// cada trozo se pinta como nodo de texto de React (escapado). Un enlace deja solo su texto (sin URL que
// abrir) y una barra invertida de escape desaparece. Lo que no reconoce se queda como texto tal cual.

export type InlinePart = { kind: 'text' | 'strong' | 'em' | 'code'; text: string }

// Por orden: código, negrita (** o __), cursiva (* o _ sin espacio por dentro), enlace y escape.
const TOKEN =
  /`([^`\n]+)`|\*\*(?=\S)(.+?)\*\*|__(?=\S)(.+?)__|\*(?=[^\s*])([^*\n]+?)\*|(?<![\p{L}\p{N}])_(?=[^\s_])([^_\n]+?)_(?![\p{L}\p{N}])|\[([^\]\n]+)\]\((?:[^()\n]|\([^()\n]*\))*\)|\\([\\`*_{}[\]()#+\-.!|>])/gu

export function inlineParts(text: string): InlinePart[] {
  const parts: InlinePart[] = []
  const push = (kind: InlinePart['kind'], value: string) => {
    if (!value) return
    const last = parts.at(-1)
    if (kind === 'text' && last?.kind === 'text') last.text += value
    else parts.push({ kind, text: value })
  }
  let cursor = 0
  for (const match of text.matchAll(TOKEN)) {
    const index = match.index ?? 0
    push('text', text.slice(cursor, index))
    const [, code, strong, strongAlt, em, emAlt, link, escaped] = match
    if (code !== undefined) push('code', code)
    else if (strong !== undefined || strongAlt !== undefined) push('strong', stripEscapes(strong ?? strongAlt ?? ''))
    else if (em !== undefined || emAlt !== undefined) push('em', stripEscapes(em ?? emAlt ?? ''))
    else if (link !== undefined) push('text', stripEscapes(link))
    else if (escaped !== undefined) push('text', escaped)
    cursor = index + match[0].length
  }
  push('text', text.slice(cursor))
  return parts
}

/** Quita las barras de escape de Markdown dentro de un trozo ya reconocido. */
function stripEscapes(value: string): string {
  return value.replace(/\\([\\`*_{}[\]()#+\-.!|>])/g, '$1')
}

/** El texto sin marcas (para nombres accesibles o comparaciones). */
export function plainText(text: string): string {
  return inlineParts(text)
    .map((part) => part.text)
    .join('')
}
