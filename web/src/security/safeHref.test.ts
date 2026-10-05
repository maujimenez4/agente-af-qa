import { describe, expect, it } from 'vitest'
import { safeHref } from './safeHref.ts'

describe('safeHref (PA-308)', () => {
  it.each([
    ['https://sitio-ficticio.atlassian.net/browse/DEMO-3', 'https://sitio-ficticio.atlassian.net/browse/DEMO-3'],
    ['http://localhost:5173/', 'http://localhost:5173/'],
    ['  https://ejemplo.test/a  ', 'https://ejemplo.test/a'],
    ['HTTPS://EJEMPLO.TEST/', 'https://ejemplo.test/'],
    ['/api/v1/memories/DEMO-3', '/api/v1/memories/DEMO-3'],
    ['#seccion', '#seccion'],
  ])('acepta %s', (value, expected) => {
    expect(safeHref(value)).toBe(expected)
  })

  it.each([
    'javascript:alert(1)',
    'JaVaScRiPt:alert(1)',
    ' javascript:alert(1)',
    'java\nscript:alert(1)',
    'java\tscript:alert(1)',
    'javascript\u0000:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'vbscript:msgbox(1)',
    'file:///etc/passwd',
    'ftp://ejemplo.test/',
    '//otro-sitio.test/ruta',
    '/\\otro-sitio.test',
    '\\\\otro-sitio.test',
    'https:\\\\otro-sitio.test',
    'relativa/sin/barra',
    'https://',
    'https://ejemplo.test/a b',
    '',
    '   ',
  ])('rechaza %j', (value) => {
    expect(safeHref(value)).toBeUndefined()
  })

  it.each([undefined, null, 42, {}, ['https://ejemplo.test']])('rechaza lo que no es texto (%j)', (value) => {
    expect(safeHref(value)).toBeUndefined()
  })
})
