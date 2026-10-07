import { Fragment } from 'react'
import { inlineParts } from './inlineMarkdown.ts'

// Texto del modelo con Markdown en línea (PA-334): negrita, cursiva y código como elementos de React.
// Nunca se inserta HTML: una etiqueta que escriba el modelo sale como texto.
// Con `plain` (texto entero de más de INLINE_MAX_TOTAL, PA-347) sale tal cual, sin buscar marcas.
export function InlineMarkdown({ text, plain = false }: { text: string; plain?: boolean }) {
  if (plain) return <>{text}</>
  return (
    <>
      {inlineParts(text).map((part, index) => {
        if (part.kind === 'strong') return <strong key={index}>{part.text}</strong>
        if (part.kind === 'em') return <em key={index}>{part.text}</em>
        if (part.kind === 'code') return <code key={index}>{part.text}</code>
        return <Fragment key={index}>{part.text}</Fragment>
      })}
    </>
  )
}
