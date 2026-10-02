# Decisiones de diseño de `web/` (T-56)

Lo que aquí figura está **decidido** y no se vuelve a discutir salvo que lo cambie la persona responsable del área B. La referencia visual es el lienzo «Propuesta mixta» (`docs/diseno/lienzo/`). Cuando el lienzo se contradice a sí mismo, manda esta tabla. Cuando contradice a `docs/specs/UI.md`, manda UI.md.

Decidido el 2 de octubre de 2026.

## 1. Incoherencias del lienzo resueltas

| # | Tema | Decisión |
|---|---|---|
| 1 | Paleta de aviso o simulación | `#FFF8E6` fondo · `#F0D48A` borde · `#6B4A00` texto. La variante `#FFF3E0`/`#F0C98A`/`#6B3A00` de `Estados.dc.html` se descarta |
| 2 | Aviso de consumo de tokens ≥ 90 % | Dos tokens según el fondo: `--color-warn-on-dark: #FFB48A` (carril navy) y `--color-warn: #B35C00` (fondos claros) |
| 3 | Verdes | `--color-success-text: #1E5E38` para todo texto verde (chips y diff); `--color-success: #1E7A46` solo para sólidos (casillas del recibo, «Pasó», INVEST «Bien», icono Hecho). `#14532D` se descarta |
| 4 | Radio de botón | 10 px |
| 5 | Marcas de paso | 22 px |
| 6 | Icono de enviar y de aviso | Flecha hacia arriba para enviar. Triángulo para aviso |
| 7 | Color de «hecho» | Naranja para el **progreso** (pasos completados, operaciones hechas). Verde solo para **resultados correctos** (operación revisada, «Pasó», «Bien») |
| 8 | Nombre de la fase 2 | «Generar» (UI.md §2) |
| 9 | Avatar | Forma Q, 40 px, peso 700 (el del carril) |
| 10 | Anchos | Panel derecho: `--panel-sm: 420px` (antes de generar), `--panel-md: 480px` (propuesta, informe), `--panel-lg: 540px` (suite de QA). Columna de chat: `--chat-max: 640px`; inicio: `--hero-max: 760px`. Lista de conversaciones: 248 px; carril: 88 px; cabecera: 64 px |
| 11 | Cabecera | Padding horizontal de 20 px, H1 de 16 px y alto de 64 px en todas las pantallas |
| 12 | Foco visible | `:focus-visible` global: contorno de 2 px `#FF7932` con un halo de 2 px `#B23E00` alrededor (opción A). `#FF7932` solo contra blanco da 2,6:1; el halo asegura más de 3:1 (WCAG 1.4.11). El compositor mantiene además su anillo `0 0 0 3px #FFF3EC` |
| 13 | Q con «reducir movimiento» | El estado final de cada Q va en el **estilo base** y la animación solo recorre «desde → hasta». Al anular las animaciones, la Q queda en su fase (no llena). La Q de carga queda fija a la mitad |
| 14 | Fuentes | Solo DM Sans. IBM Plex Mono no se usa. Cifras con `font-variant-numeric: tabular-nums` |
| 15 | Casillas | Naranja (`accent-color`) para elegir fuentes y tipos de caso. Verde para confirmar operaciones del recibo |
| 16 | Historial en el carril | **Solo `admin`**, como dice UI.md §3 (PA-62), aunque el lienzo lo muestre a todos. Duda abierta para la sesión principal: PA-302 |

## 2. Otras decisiones

- **Tipografía:** DM Sans 400/500/600/700 alojada con `@fontsource/dm-sans` (paquete npm), sin `<link>` a Google Fonts: no hay peticiones a terceros con la IP del usuario y funciona sin conexión.
- **Path de la Q:** se copia literal de `renderVals()` del lienzo (`q: 'M110.806 87.9929H215.094…'`, idéntico en las 15 apariciones; `viewBox="0 0 326 326"`). El logotipo de la mixta es esa misma Q; la imagen `/_blob/…` del `Sidebar` de la v1 no se usa.
- **Movimiento:** `cubic-bezier(.2,.7,.2,1)`; 0,22 s (carril), 0,32 s (botones), 0,42 s (el resto, salvo la carga). Todo se desactiva con `prefers-reduced-motion: reduce`.
- **Microinteracciones:** solo color o brillo (botón −6 % al pulsar, borde naranja al pasar el ratón).
- **Espaciado:** escala normalizada de 4, 8, 12, 16, 20, 24 y 32 px (el lienzo usa valores sueltos de 2 a 32).
- **Textos de error:** título según UI.md §7 y mensaje de la excepción **tal cual**. Los textos de proveedor y tiempos del lienzo («menos de 30 s») no se copian: el modelo vendrá de la API (PA-301).
- **Estado vacío:** texto de UI.md §7 («Elige un origen para generar la primera versión de la HU.»), no el del lienzo, que remite a la pestaña Contexto de la v1.

## 3. Herramientas

- **Versiones exactas** (`.npmrc` con `save-exact`) y `package-lock.json` versionado.
- **TypeScript 6.0**, no 7: `typescript-eslint` 8 solo admite `<6.1`.
- **ESLint 9**, no 10: `eslint-plugin-jsx-a11y` 6 aún no admite ESLint 10. npm marca ESLint 9 como fuera de soporte; se subirá cuando jsx-a11y lo admita.
- **Reglas de seguridad en ESLint** (`eslint.config.js`): error si aparece `dangerouslySetInnerHTML`, una asignación a `innerHTML`/`outerHTML`, `insertAdjacentHTML`, `localStorage` o `sessionStorage`.
