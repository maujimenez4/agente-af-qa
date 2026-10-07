// Bloques de Markdown de un extracto del RAG (PA-428): títulos, párrafos, citas, listas (con viñetas y
// numeradas) y tablas sencillas. Nunca HTML: el texto de cada bloque lo pinta `InlineMarkdown`.
// Un extracto puede venir cortado a mitad de una tabla o de una marca: lo que no se reconoce es texto.

export type MarkdownBlock =
  | { kind: 'heading'; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] }
  | { kind: 'table'; header: string[]; rows: string[][] }

const HEADING = /^#{1,6}\s+(.*)$/
const BULLET = /^[-*+]\s+(.*)$/
const NUMBERED = /^\d+[.)]\s+(.*)$/
const RULE = /^([-*_])(\s*\1){2,}$/

/** Fila de tabla («| a | b |»): sus celdas, o undefined si la línea no lo es. */
function tableCells(line: string): string[] | undefined {
  if (!line.startsWith('|') || line.length < 2) return undefined
  const inner = line.endsWith('|') ? line.slice(1, -1) : line.slice(1)
  return inner.split('|').map((cell) => cell.trim())
}

/** Línea separadora de una tabla («|---|:---:|»). */
function isSeparator(line: string): boolean {
  return line.includes('|') && line.includes('-') && /^[|\s:-]+$/.test(line)
}

export function markdownBlocks(markdown: string): MarkdownBlock[] {
  // \r y los separadores de línea Unicode también parten líneas: ninguna expresión de línea los cruza.
  const lines = markdown.split(/\r\n|[\n\r\u2028\u2029]/).map((line) => line.trim())
  const blocks: MarkdownBlock[] = []
  let paragraph: string[] = []
  const flush = () => {
    if (paragraph.length > 0) blocks.push({ kind: 'paragraph', text: paragraph.join(' ') })
    paragraph = []
  }

  for (let index = 0; index < lines.length; index += 1) {
    let line = lines[index] ?? ''
    if (line.startsWith('>')) line = line.replace(/^>\s*/, '')
    if (!line || RULE.test(line)) {
      flush()
      continue
    }

    // Tabla: cabecera seguida de su separador; después, las filas mientras sigan siendo filas.
    const header = tableCells(line)
    if (header && isSeparator(lines[index + 1] ?? '')) {
      flush()
      const rows: string[][] = []
      index += 2
      for (; index < lines.length; index += 1) {
        const cells = tableCells(lines[index] ?? '')
        if (!cells || isSeparator(lines[index] ?? '')) break
        rows.push(header.map((_, column) => cells[column] ?? ''))
      }
      index -= 1
      blocks.push({ kind: 'table', header, rows })
      continue
    }
    if (isSeparator(line)) continue // separador suelto de una tabla cortada
    if (header) {
      // Fila suelta (la tabla se cortó antes de la cabecera): como texto.
      flush()
      blocks.push({ kind: 'paragraph', text: header.filter(Boolean).join(' · ') })
      continue
    }

    const heading = HEADING.exec(line)
    if (heading?.[1]) {
      flush()
      blocks.push({ kind: 'heading', text: heading[1] })
      continue
    }

    const bullet = BULLET.exec(line)
    const numbered = bullet ? undefined : NUMBERED.exec(line)
    const item = bullet?.[1] ?? numbered?.[1]
    if (item !== undefined) {
      flush()
      const ordered = Boolean(numbered)
      const last = blocks.at(-1)
      if (last?.kind === 'list' && last.ordered === ordered) last.items.push(item)
      else blocks.push({ kind: 'list', ordered, items: [item] })
      continue
    }

    paragraph.push(line)
  }
  flush()
  return blocks
}
