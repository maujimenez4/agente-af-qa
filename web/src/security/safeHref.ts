// Enlaces construidos con datos (PA-308): solo `http(s)`, rutas del propio sitio o anclas.
// Nunca `javascript:`, `data:`, `vbscript:`, `file:`, URL con usuario o contraseña, ni sin esquema (`//host`), que el navegador
// resolvería como otro sitio. ESLint obliga a pasar por aquí todo `href` o `src` que no sea un literal.

// eslint-disable-next-line no-control-regex -- se buscan justo los caracteres de control para rechazarlos.
const CONTROL_OR_SPACE = /[\u0000-\x20\u007f-\u009f]/
const ALLOWED_PROTOCOLS = new Set(['http:', 'https:'])

/** El enlace si es seguro; si no, `undefined` (el elemento se pinta sin enlace). */
export function safeHref(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const href = value.trim()
  // Espacios, saltos o caracteres de control dentro: el navegador los ignora y «java\nscript:» pasaría.
  if (!href || CONTROL_OR_SPACE.test(href) || href.includes('\\')) return undefined
  if (href.startsWith('#')) return href
  if (href.startsWith('/')) return href.startsWith('//') ? undefined : href
  try {
    const url = new URL(href)
    // Con usuario o contraseña (una URL que lleva «usuario:clave» o un sitio de Jira antes de la «@» del host real)
    // el enlace engaña o expone credenciales.
    if (url.username || url.password) return undefined
    return ALLOWED_PROTOCOLS.has(url.protocol) && url.hostname ? url.href : undefined
  } catch {
    return undefined
  }
}
