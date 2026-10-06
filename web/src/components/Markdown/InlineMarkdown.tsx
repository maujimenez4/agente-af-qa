import { Fragment } from 'react'
import { inlineParts } from './inlineMarkdown.ts'

// Texto del modelo con Markdown en línea (PA-334): negrita, cursiva y código como elementos de React.
// Nunca se inserta HTML: una etiqueta que escriba el modelo sale como texto.
export function InlineMarkdown({ text }: { text: string }) {
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
