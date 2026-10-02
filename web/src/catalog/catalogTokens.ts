// Datos del catálogo. La prueba catalogTokens.test.ts comprueba que coinciden con styles/tokens.css.

export interface ColorToken {
  token: string
  hex: string
  role: string
}

export const COLOR_GROUPS: ReadonlyArray<{ title: string; colors: readonly ColorToken[] }> = [
  {
    title: 'Neutros y marca',
    colors: [
      { token: '--color-text', hex: '#233441', role: 'Texto principal' },
      { token: '--color-text-muted', hex: '#5c6e7c', role: 'Texto secundario e iconos' },
      { token: '--color-surface', hex: '#ffffff', role: 'Superficie' },
      { token: '--color-surface-2', hex: '#fafbfc', role: 'Paneles laterales' },
      { token: '--color-bg', hex: '#f4f6f8', role: 'Fondo, hover y pestaña activa' },
      { token: '--color-border-soft', hex: '#e6eaee', role: 'Divisores y Q vacía' },
      { token: '--color-border', hex: '#c7cfd6', role: 'Chips y paso pendiente' },
      { token: '--color-border-strong', hex: '#93a0ab', role: 'Inputs y botón secundario' },
      { token: '--color-primary', hex: '#ff7932', role: 'Primario, Q llena y foco' },
      { token: '--color-primary-tint', hex: '#fff3ec', role: 'Seleccionado' },
      { token: '--color-primary-text', hex: '#b23e00', role: 'Naranja legible y halo del foco' },
      { token: '--color-flash', hex: '#ffe5d5', role: 'Resalte de un cambio' },
      { token: '--color-navy', hex: '#1e2d3d', role: 'Carril y avatar del asistente' },
      { token: '--color-navy-hover', hex: '#2c3e4d', role: 'Hover y activo del carril' },
      { token: '--color-on-navy', hex: '#c9d2db', role: 'Texto sobre navy' },
      { token: '--color-overlay', hex: '#1e2d3d66', role: 'Velo del modal' },
    ],
  },
  {
    title: 'Aviso y simulación',
    colors: [
      { token: '--color-warn-bg', hex: '#fff8e6', role: 'Fondo' },
      { token: '--color-warn-border', hex: '#f0d48a', role: 'Borde' },
      { token: '--color-warn-text', hex: '#6b4a00', role: 'Texto' },
      { token: '--color-warn', hex: '#b35c00', role: 'Sólido sobre claro' },
      { token: '--color-warn-on-dark', hex: '#ffb48a', role: 'Sólido sobre navy' },
    ],
  },
  {
    title: 'Error',
    colors: [
      { token: '--color-error-bg', hex: '#fdecea', role: 'Fondo' },
      { token: '--color-error-border', hex: '#f1b8b2', role: 'Borde' },
      { token: '--color-error-text', hex: '#8c1d18', role: 'Texto' },
      { token: '--color-error', hex: '#c9453c', role: 'Sólido' },
    ],
  },
  {
    title: 'Éxito',
    colors: [
      { token: '--color-success-bg', hex: '#e7f4ec', role: 'Fondo del chip' },
      { token: '--color-success-row', hex: '#f3faf6', role: 'Fila revisada' },
      { token: '--color-success-border', hex: '#a7d3b8', role: 'Borde' },
      { token: '--color-success-text', hex: '#1e5e38', role: 'Texto' },
      { token: '--color-success', hex: '#1e7a46', role: 'Sólido' },
    ],
  },
  {
    title: 'Informativo',
    colors: [
      { token: '--color-info-bg', hex: '#e8f0fb', role: 'Fondo «Alterno»' },
      { token: '--color-info-text', hex: '#1d4f91', role: 'Texto «Alterno»' },
    ],
  },
]

export const TYPE_SCALE: ReadonlyArray<{ token: string; weight: string; sample: string }> = [
  { token: '--text-hero', weight: '--weight-bold', sample: '¿En qué trabajamos hoy?' },
  { token: '--text-xl', weight: '--weight-bold', sample: 'Versión 2 lista para revisar' },
  { token: '--text-lg', weight: '--weight-semibold', sample: 'Generando la propuesta…' },
  { token: '--text-md', weight: '--weight-bold', sample: 'Evolucionar DEMO-3' },
  { token: '--text-body', weight: '--weight-regular', sample: 'Elige qué hacemos y de qué partimos. Nada se publica en Jira sin tu aprobación.' },
  { token: '--text-sm', weight: '--weight-semibold', sample: 'Revisar y aprobar' },
  { token: '--text-xs', weight: '--weight-regular', sample: 'Fase 2 de 4 · Generar' },
  { token: '--text-2xs', weight: '--weight-bold', sample: 'Cambiado en v2' },
  { token: '--text-3xs', weight: '--weight-bold', sample: 'DEMO' },
]
