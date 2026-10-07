import { InlineMarkdown } from './InlineMarkdown.tsx'
import { INLINE_MAX_TOTAL } from './inlineMarkdown.ts'
import styles from './Markdown.module.css'
import { markdownBlocks } from './markdownBlocks.ts'

// Extracto en Markdown de una fuente (PA-428): bloques como elementos de React, nunca HTML. Los títulos del
// extracto no son títulos de la página (no entran en el índice de encabezados): se pintan en negrita.
export function MarkdownBlocks({ text, className }: { text: string; className?: string }) {
  const plain = text.length > INLINE_MAX_TOTAL // PA-347
  return (
    <div className={[styles.blocks, className].filter(Boolean).join(' ')}>
      {markdownBlocks(text).map((block, index) => {
        if (block.kind === 'heading') {
          return (
            <p key={index} className={styles.heading}>
              <strong>
                <InlineMarkdown plain={plain} text={block.text} />
              </strong>
            </p>
          )
        }
        if (block.kind === 'list') {
          const items = block.items.map((item, position) => (
            <li key={position}>
              <InlineMarkdown plain={plain} text={item} />
            </li>
          ))
          return block.ordered ? (
            <ol key={index} className={styles.list}>
              {items}
            </ol>
          ) : (
            <ul key={index} className={styles.list}>
              {items}
            </ul>
          )
        }
        if (block.kind === 'table') {
          return (
            <div key={index} className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    {block.header.map((cell, column) => (
                      <th key={column} scope="col">
                        <InlineMarkdown plain={plain} text={cell} />
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, position) => (
                    <tr key={position}>
                      {row.map((cell, column) => (
                        <td key={column}>
                          <InlineMarkdown plain={plain} text={cell} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
        return (
          <p key={index}>
            <InlineMarkdown plain={plain} text={block.text} />
          </p>
        )
      })}
    </div>
  )
}
