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

export const RADII: ReadonlyArray<{ token: string; value: string; use: string }> = [
  { token: '--radius-xs', value: '4px', use: 'Barras de progreso y diff' },
  { token: '--radius-sm', value: '6px', use: 'Badges, citas y botón de 28 px' },
  { token: '--radius-md', value: '8px', use: 'Inputs y botón solo icono' },
  { token: '--radius-btn', value: '10px', use: 'Botones (decisión 4)' },
  { token: '--radius-lg', value: '12px', use: 'Carril y avisos' },
  { token: '--radius-xl', value: '16px', use: 'Tarjetas, compositor y modal' },
  { token: '--radius-pill', value: '999px', use: 'Chips' },
  { token: '--radius-q', value: '16px 16px 4px 16px', use: 'Geometría Q: burbujas e iconos' },
  { token: '--radius-q-card', value: '14px 14px 4px 14px', use: 'Tarjeta de flujo' },
  { token: '--radius-q-md', value: '12px 12px 4px 12px', use: 'Avatar y tarjetas del chat' },
  { token: '--radius-q-sm', value: '9px 9px 3px 9px', use: 'Avatar pequeño del asistente' },
]

export const SPACES: readonly string[] = ['--space-1', '--space-2', '--space-3', '--space-4', '--space-5', '--space-6', '--space-7']

export const LAYOUT: ReadonlyArray<{ token: string; value: string; use: string }> = [
  { token: '--rail-width', value: '88px', use: 'Carril' },
  { token: '--conversations-width', value: '248px', use: 'Lista de conversaciones' },
  { token: '--conversations-strip', value: '48px', use: 'Lista plegada por debajo de 1024 px (PA-335)' },
  { token: '--header-height', value: '64px', use: 'Cabecera' },
  { token: '--panel-sm', value: '420px', use: 'Panel «Antes de generar»' },
  { token: '--panel-md', value: '480px', use: 'Panel de propuesta e informe' },
  { token: '--panel-lg', value: '540px', use: 'Panel de la suite de QA' },
  { token: '--chat-max', value: '640px', use: 'Columna del chat' },
  { token: '--hero-max', value: '760px', use: 'Inicio' },
  { token: '--control-lg', value: '44px', use: 'Botón y control grandes' },
  { token: '--control-md', value: '36px', use: 'Botón y buscador medianos' },
  { token: '--control-sm', value: '28px', use: 'Botón pequeño' },
  { token: '--step-mark', value: '22px', use: 'Marca de paso (decisión 5)' },
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

// Índice: el id es el del h2 de cada sección.
export const CATALOG_SECTIONS: ReadonlyArray<{ id: string; title: string }> = [
  { id: 'colores', title: 'Colores' },
  { id: 'tipografia', title: 'Tipografía · DM Sans' },
  { id: 'medidas', title: 'Forma y medidas' },
  { id: 'iconos', title: 'Iconos' },
  { id: 'q', title: 'La Q animada' },
  { id: 'marco', title: 'Carril y lista de conversaciones' },
  { id: 'componentes', title: 'Botones, chips, badges y tarjetas' },
  { id: 'estados', title: 'Estados vacío, cargando y error' },
]
