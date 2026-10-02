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
| 13 | Q con «reducir movimiento» | El estado final de cada Q va en el **estilo base** y la animación solo recorre «desde → hasta». Al anular las animaciones, la Q queda en su fase (no llena). La Q de carga muestra los cuartos ya hechos, sin movimiento (§3) |
| 14 | Fuentes | Solo DM Sans. IBM Plex Mono no se usa. Cifras con `font-variant-numeric: tabular-nums` |
| 15 | Casillas | Naranja (`accent-color`) para elegir fuentes y tipos de caso. Verde para confirmar operaciones del recibo |
| 16 | Historial en el carril | **Solo `admin`**, como dice UI.md §3 (PA-62), aunque el lienzo lo muestre a todos. Duda abierta para la sesión principal: PA-302 |
| 17 | Anillo de consumo de tokens del carril | **Opcional**: el contrato de T-55 no da el dato (PA-305). Sin dato, el anillo no se pinta |

## 2. Otras decisiones

- **Tipografía:** DM Sans 400/500/600/700 alojada con `@fontsource/dm-sans` (paquete npm), sin `<link>` a Google Fonts: no hay peticiones a terceros con la IP del usuario y funciona sin conexión.
- **Path de la Q:** provisional, copiado literal de `renderVals()` del lienzo (`q: 'M110.806 87.9929H215.094…'`, idéntico en las 15 apariciones; `viewBox="0 0 326 326"`). Está **aislado en `src/design/qPath.ts`**: cuando lleguen la Q y el logo en SVG desde las plantillas del sistema de diseño, solo se cambia ese archivo. El logotipo de la mixta es esa misma Q; la imagen `/_blob/…` del `Sidebar` de la v1 no se usa.
- **Stepper:** el indicador de 3 fases de `TrabajoRevision` (recibo) se maqueta a partir de la captura del lienzo, porque `Stepper.dc.html` no está en la copia.
- **Movimiento:** `cubic-bezier(.2,.7,.2,1)`; 0,22 s (carril), 0,32 s (botones), 0,42 s (el resto, salvo la carga). Todo se desactiva con `prefers-reduced-motion: reduce`.
- **Microinteracciones:** solo color o brillo (botón −6 % al pulsar, borde naranja al pasar el ratón).
- **Espaciado:** escala normalizada de 4, 8, 12, 16, 20, 24 y 32 px (el lienzo usa valores sueltos de 2 a 32).
- **Textos de error:** título según UI.md §7 y mensaje de la excepción **tal cual**. Los textos de proveedor y tiempos del lienzo («menos de 30 s») no se copian: el modelo vendrá de la API (PA-301).
- **Estado vacío:** texto de UI.md §7 («Elige un origen para generar la primera versión de la HU.»), no el del lienzo, que remite a la pestaña Contexto de la v1.

## 3. La Q de carga y la escritura simulada

Acordado con la sesión principal en la PR #2 (PA-303).

**Q de carga** (generación de una HU o de una suite). Avanza con los eventos `progress` de `GET /conversations/{id}/events`:

| Evento | La Q |
|---|---|
| `progress` de `load_origin` en `done` | Llena el 1.er cuarto |
| `progress` de `retrieve_context` en `done` | Llena el 2.º cuarto |
| `progress` de `generate` en `running` | Se anima **dentro del 3.er cuarto** (sube y baja entre el inicio y el final del cuarto, en bucle) para no parecer colgada. Con el modelo local en CPU puede durar minutos |
| `progress` de `generate` en `done` | Llena el 3.er cuarto |
| `review_ready` | Llena el 4.º cuarto y la pantalla pasa a la revisión |
| `error` | Se queda en el último cuarto hecho y aparece la tarjeta de error |

- La lista de procesos usa el `label` de cada `ProgressStep` tal cual.
- Si la conexión SSE se corta, se consulta `GET /conversations/{id}` y se pinta su estado.
- `publish` y `memorize` llegan tras aprobar; su Q es la de la pantalla de Resultado (días 6 a 8), no esta.
- **Reducir movimiento:** la Q muestra los cuartos hechos sin animación (tampoco la de `generate`) y la lista de procesos marca el paso en curso.

**Escritura simulada.** La API no envía el texto por streaming: la respuesta llega completa y el frontend la escribe letra a letra.

- 2 caracteres cada 35 ms, como en el lienzo, con el caret parpadeando. Si la respuesta es larga, se escriben más caracteres por paso para que la escritura no pase de 1,5 s.
- Mientras tanto, la Q de 18 px con «Escribiendo la respuesta».
- **Accesibilidad:** la animación es solo visual (`aria-hidden`). El texto completo se anuncia una sola vez en una región `aria-live="polite"`.
- **Reducir movimiento:** el texto aparece completo de inmediato, sin caret.

## 4. Cómo habla con la API (contrato de T-55, `docs/api/openapi.yaml`)

- **Sesión:**
  - La cookie HttpOnly `afqa_session` la gestiona el navegador; el frontend no la ve.
  - El `csrf_token` de `POST /auth/login` se guarda **solo en memoria** y se envía en `X-CSRF-Token` en todo POST, PUT o DELETE.
  - Al recargar, se pide de nuevo con `GET /auth/me`. Nunca en `localStorage` ni `sessionStorage` (ESLint lo impide).
- **Mismo origen:** el frontend llama a rutas relativas `/api/v1/…`.
  - En desarrollo, un proxy de Vite las reenvía al backend. El destino va en una variable del servidor de Vite sin prefijo `VITE_`, así que no llega al navegador.
  - No hace falta CORS.
- **Operaciones largas:** crear, iterar, aprobar y revisar la calidad responden **202**. El avance llega por SSE (`EventSource` en el mismo origen) y, como respaldo, consultando `GET /conversations/{id}`.
- **Errores:**
  - Siempre `{"error": {"code", "message", "retry_after"}}`.
  - El **título**, el tono y la acción se eligen por `code`. El **mensaje** se muestra tal cual.
  - Un `code` desconocido usa un título genérico y el mismo mensaje.
- **Aprobar:** se devuelve la `fingerprint` exacta del último `review`. Una respuesta no válida llega en `review.error`, no como error HTTP. Un 409 se distingue por `error.code` (`approval_rejected` → empezar de nuevo; `not_in_review` → actualizar el estado).
- **API simulada:**
  - **MSW** para desarrollo y pruebas, con un único conjunto de handlers construido con los ejemplos del contrato y un estado en memoria que también simula el SSE.
  - Solo se activa con `VITE_API_MOCK=1` en desarrollo. `mockServiceWorker.js` no entra en el build de producción.
  - **Prism** (`npx @stoplight/prism-cli mock docs/api/openapi.yaml`) solo como comprobación puntual de que las peticiones cumplen el contrato; no se instala.
  - Los tipos se generan desde el contrato con **openapi-typescript**.
  - Se instalan en los días 2 a 4.

## 5. Herramientas

- **Versiones exactas** (`.npmrc` con `save-exact`) y `package-lock.json` versionado.
- **TypeScript 6.0**, no 7: `typescript-eslint` 8 solo admite `<6.1`.
- **ESLint 9**, no 10: `eslint-plugin-jsx-a11y` 6 aún no admite ESLint 10. npm marca ESLint 9 como fuera de soporte; se subirá cuando jsx-a11y lo admita.
- **Reglas de seguridad en ESLint** (`eslint.config.js`): error si aparece `dangerouslySetInnerHTML`, una asignación a `innerHTML`/`outerHTML`, `insertAdjacentHTML`, `localStorage` o `sessionStorage`.
