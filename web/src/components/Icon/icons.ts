// Iconos del lienzo (Iconos.dc.html y pantallas Mixto*/Qa*), viewBox 24 y trazo de 1,75.
// Decisión 6 de DESIGN-DECISIONS.md: enviar = flecha hacia arriba; aviso = triángulo.

// Baldosa con forma Q: tres esquinas redondas y la de abajo a la derecha recta.
const TILE = 'M3 9a6 6 0 0 1 6-6h6a6 6 0 0 1 6 6v12H9a6 6 0 0 1-6-6z'

export interface IconShape {
  d: string
  /** Relleno sólido en lugar de trazo (solo «detener»). */
  filled?: boolean
}

export const ICONS = {
  work: { d: `${TILE} M8 10h8 M8 14h5` },
  history: { d: `${TILE} M12 8v4l2.5 2` },
  settings: { d: `${TILE} M8 10h8 M8 14h8 M10.5 8.5v3 M13.5 12.5v3` },
  // Memoria (PA-329): no está en el lienzo; la baldosa con un marcapáginas, como Trabajo, Historial y Ajustes.
  memory: { d: `${TILE} M9.5 8h5v8.5l-2.5-1.75-2.5 1.75z` },
  new: { d: `${TILE} M12 8.5v7 M8.5 12h7` },
  model: { d: `${TILE} M9.5 9.5h5v5h-5z` },
  searchSource: { d: `${TILE} M10.5 13.5a2.5 2.5 0 1 0 3-3 M13.5 13.5l2 2` },
  wrong: { d: `${TILE} M9.5 9.5l5 5 M14.5 9.5l-5 5` },
  upload: { d: `${TILE} M12 15.5v-7 M8.5 12l3.5-3.5 3.5 3.5` },
  tests: { d: `${TILE} M6 12.5l4 4 8-9` },
  panelLeft: { d: `${TILE} M10 3v18` },
  panelRight: { d: `${TILE} M14 3v18` },
  done: { d: 'M6 12.5l4 4 8-9' },
  send: { d: 'M12 19V6 M7 11l5-5 5 5' },
  warning: { d: 'M12 8v5 M12 16h.01 M12 3l9 16H3z' },
  logout: { d: 'M12 21H9a6 6 0 0 1-6-6V9a6 6 0 0 1 6-6h3 M16 8l4 4-4 4 M20 12H10' },
  search: { d: 'M10.5 13.5a2.5 2.5 0 1 0 3-3 M13.5 13.5l2 2' },
  lock: { d: 'M7 11V8a5 5 0 0 1 10 0v3 M5 11h14v10H5z' },
  folder: { d: 'M3 7h7l2 2h9v10H3z' },
  chevronDown: { d: 'M7 10l5 5 5-5' },
  back: { d: 'M15 6l-6 6 6 6' },
  close: { d: 'M7 7l10 10 M17 7L7 17' },
  stop: { d: 'M8 5h8a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3V8a3 3 0 0 1 3-3z', filled: true },
} as const satisfies Record<string, IconShape>

export type IconName = keyof typeof ICONS

export const ICON_NAMES = Object.keys(ICONS) as IconName[]
