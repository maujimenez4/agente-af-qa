// Descarga de un texto que llega de la API como archivo (la matriz de cobertura, PA-326; el .md de una memoria):
// el contenido va a un Blob de texto, nunca se inserta como HTML ni viaja en un href. El único enlace es el blob:
// que crea esta función; ningún valor de la API llega a `href` (la regla de safeHref sigue intacta, PA-308).
// ESLint prohíbe `URL.createObjectURL` y asignar `.href` en el resto del código: esta es la única excepción.

/** Tipos de archivo que se pueden descargar: solo texto. */
export type DownloadType = 'text/markdown' | 'text/plain'

// Letras, cifras, «.», «_» y «-», sin empezar por punto ni pasar de 100 caracteres: ni rutas ni nombres ocultos.
const SAFE_NAME = /^[\p{L}\p{N}][\p{L}\p{N}._-]{0,99}$/u

/** El nombre tal cual si es seguro como nombre de archivo; si no, `undefined`. */
export function safeFileName(name: unknown): string | undefined {
  return typeof name === 'string' && SAFE_NAME.test(name) && !name.includes('..') ? name : undefined
}

/** Descarga `text` como `fileName`. Devuelve `false` (y no descarga) si el nombre no es seguro. */
export function downloadText(fileName: string, text: string, type: DownloadType = 'text/markdown'): boolean {
  const name = safeFileName(fileName)
  if (!name) return false
  const blob = new Blob([text], { type: `${type};charset=utf-8` })
  // eslint-disable-next-line no-restricted-syntax -- única descarga del frontend: un blob: local con el texto, no una URL de la API.
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  // eslint-disable-next-line no-restricted-syntax -- el blob: de la línea anterior; nunca un valor que llegue de la API.
  link.href = url
  link.download = name
  link.rel = 'noopener'
  link.hidden = true
  document.body.append(link)
  try {
    link.click()
  } finally {
    link.remove()
    // Tras el clic el navegador ya tiene el archivo; se libera en la siguiente vuelta del bucle de eventos.
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }
  return true
}
