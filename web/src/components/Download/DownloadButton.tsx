import { useId } from 'react'
import { downloadText, safeFileName, type DownloadType } from '../../security/download.ts'
import { Button, type ButtonSize, type ButtonVariant } from '../Button/index.ts'

export interface DownloadButtonProps {
  /** Texto visible, p. ej. «Descargar la matriz». */
  label: string
  /** Nombre del archivo (`matriz-DEMO-3.md`); si no es seguro, el botón no se pinta. */
  fileName: string
  /** El contenido tal como llega de la API; se descarga como texto, nunca se pinta como HTML. */
  text: string | null | undefined
  type?: DownloadType
  variant?: ButtonVariant
  size?: ButtonSize
}

// Descarga de un texto de la API como archivo (matriz de cobertura, PA-326; después, el .md de una memoria).
// Sin texto o con un nombre no seguro, no se pinta: no se ofrece una descarga vacía.
export function DownloadButton({ label, fileName, text, type = 'text/markdown', variant = 'secondary', size = 'sm' }: DownloadButtonProps) {
  const noteId = useId()
  const name = safeFileName(fileName)
  if (!name || typeof text !== 'string' || text.length === 0) return null
  return (
    <>
      <Button variant={variant} size={size} aria-describedby={noteId} onClick={() => downloadText(name, text, type)}>
        {label}
      </Button>
      <span id={noteId} className="visually-hidden">
        Descarga el archivo {name}.
      </span>
    </>
  )
}
