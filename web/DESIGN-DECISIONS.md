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
| 16 | Historial en el carril | **Solo `admin`**, como dice UI.md §3 (PA-62), aunque el lienzo lo muestre a todos. Confirmado por la principal (PA-302): en el carril aparece como **«disponible pronto»**, porque T-45 es Could y no está en el contrato |
| 17 | Anillo de consumo de tokens del carril | Dato de `GET /api/v1/settings/usage` (`tokens_today`, `warning_threshold`, `scope: "global"`, PA-305). Es el consumo **de toda la instalación** en el día, no de la persona: el texto visible y el nombre accesible lo dicen («Consumo de hoy de la instalación»). Aviso desde `warning_threshold`. Con 503 u otro error, o sin dato, el anillo no se pinta |

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
| `review_ready` | Llena el 4.º cuarto y la pantalla pasa a la revisión. Llena la Q entera aunque se haya perdido algún `progress` (por ejemplo, al reconectar el SSE) |
| `error` | Se queda en el último cuarto hecho y aparece la tarjeta de error |

- La lista de procesos usa el `label` de cada `ProgressStep` tal cual.
- Si la conexión SSE se corta, se consulta `GET /conversations/{id}` y se pinta su estado.
- `publish` y `memorize` llegan tras aprobar; su Q es la de la pantalla de Resultado (días 6 a 8), no esta.
- **Reducir movimiento:** la Q muestra los cuartos hechos sin animación (tampoco la de `generate`) y la lista de procesos marca el paso en curso.

**Escritura simulada.** La API no envía el texto por streaming: la respuesta llega completa y el frontend la escribe letra a letra.

- 2 caracteres cada 35 ms, como en el lienzo, con el caret parpadeando. Si la respuesta es larga, se escriben más caracteres por paso para que la escritura no pase de 1,5 s.
- Mientras tanto, la Q de 18 px con «Escribiendo la respuesta».
- **Accesibilidad:** la animación es solo visual (`aria-hidden`). El texto completo está desde el principio en un nodo oculto para lectores de pantalla, y lo anuncia una sola vez el contenedor del chat (`role="log"`, que ya es `aria-live="polite"`) al añadirse el mensaje. «Escribiendo la respuesta» va en un `role="status"`.
- **Reducir movimiento:** el texto aparece completo de inmediato, sin caret.

## 4. Cómo habla con la API (contrato de T-55, `docs/api/openapi.yaml`)

- **Sesión:**
  - La cookie HttpOnly `afqa_session` la gestiona el navegador; el frontend no la ve.
  - El `csrf_token` de `POST /auth/login` se guarda **solo en memoria** y se envía en `X-CSRF-Token` en todo POST, PUT o DELETE.
  - Al recargar, se pide de nuevo con `GET /auth/me`. Nunca en `localStorage` ni `sessionStorage` (ESLint lo impide).
- **Mismo origen:** el frontend llama a rutas relativas `/api/v1/…`.
  - En desarrollo, un proxy de Vite reenvía `/api` a `http://127.0.0.1:8000` **sin `changeOrigin`**: la API compara `Origin` con `Host`. El destino va en una variable del servidor de Vite sin prefijo `VITE_`, así que no llega al navegador.
  - No hace falta CORS.
- **Operaciones largas:** crear, iterar, aprobar y revisar la calidad responden **202**. El avance llega por SSE (`EventSource` en el mismo origen) y, como respaldo, consultando `GET /conversations/{id}`.
  - Mientras hay una operación en curso, otra sobre la misma conversación da 409 `not_in_review`.
  - El cliente **cierra el `EventSource` tras `result`** de una conversación terminada (simulada, publicada o descartada), para que no reconecte.
  - Como mucho 3 flujos abiertos por persona: el cuarto da 429 `too_many_streams`.
- **Errores:**
  - Siempre `{"error": {"code", "message", "retry_after"}}`. `code` es una lista cerrada (`ErrorBody.code`, PA-306).
  - El **título**, el tono y la acción se eligen por `code` (§6). El **mensaje** se muestra tal cual.
  - Los fallos de la generación llegan en `ConversationOut.error` o `QualityReviewOut.error`, no como error HTTP.
  - Un `code` que no esté en la lista (versión futura de la API) usa un título genérico y el mismo mensaje.
- **Aún sin implementar en la API:**
  - `/conversations/{id}/handoff` y `/qa/*` dan 501 `not_implemented` hasta que se cierre T-54. La pantalla los trata como «disponible pronto».
  - El registro de la ejecución (QA 6, `/executions`) llegará más tarde con T-47.
- **Aprobar:** se devuelve la `fingerprint` exacta del último `review`. Una respuesta no válida llega en `review.error`, no como error HTTP. Un 409 se distingue por `error.code` (`approval_rejected` → empezar de nuevo; `not_in_review` → actualizar el estado).
- **API simulada:**
  - **MSW** para desarrollo y pruebas, con un único conjunto de handlers construido con los ejemplos del contrato y un estado en memoria que también simula el SSE.
  - Solo se activa con `VITE_API_MOCK=1` en desarrollo. `mockServiceWorker.js` no entra en el build de producción.
  - **Prism** (`npx @stoplight/prism-cli mock docs/api/openapi.yaml`) solo como comprobación puntual de que las peticiones cumplen el contrato; no se instala.
  - Los tipos se generan desde el contrato con **openapi-typescript**.
  - Se instalan en los días 2 a 4.

## 5. Textos de la lista de conversaciones

Salen de `ConversationSummary` (`mode`, `origin_kind`, `origin_key`, `status`, `version`) con el formato «flujo · estado» del lienzo.

- **Flujo:** `qa` → «Pruebas de DEMO-3»; `functional` con origen `story` → «Evolucionar DEMO-3»; con `need` o `epic` → «Nueva necesidad».
- **Estado:**
  - `in_review` → «Versión N»;
  - `simulated` → «Simulado»;
  - `published` → «Publicado»;
  - los tres que UI.md no nombra: `started` → «En curso», `approved` → «Aprobada» y `discarded` → «Descartada».
- **Grupos:** por día de `updated_at`:
  - «Hoy» y «Ayer»;
  - una fecha de este año, sin el año («30 de septiembre»);
  - una de otro año, con él («30 de septiembre de 2025»).

  Una fecha que no se puede leer no rompe la lista: va al final, en «Sin fecha».
- **Buscador:** local, sin distinguir mayúsculas ni tildes.
- Las revisiones de calidad («Informe listo») no están en la lista hasta que se decida PA-103.

## 6. Tarjetas de error por `code`

El mensaje es siempre el de la API, tal cual y como texto. Lo que decide el frontend, para los 25 valores de `ErrorBody.code` (`docs/api/README.md`, `api/errors.py`):

| Grupo | `code` | Título | Tono | Acción |
|---|---|---|---|---|
| Sesión y permisos | `unauthenticated` | Sesión caducada | Neutro | Iniciar sesión |
| | `invalid_credentials` | No se pudo iniciar sesión | Error | — |
| | `too_many_attempts` | Demasiados intentos | Aviso | Reintentar, tras la cuenta atrás de `retry_after` |
| | `forbidden` | Sin permiso | Neutro | — |
| Petición | `invalid_request` | Petición no válida | Error | — |
| | `payload_too_large` | Contenido demasiado grande | Error | — |
| | `not_found` | No se encuentra | Neutro | — |
| | `project_not_found` | No se encuentra el proyecto | Neutro | — |
| | `method_not_allowed` | Acción no permitida | Error | — |
| | `http_error` | Petición no válida | Error | — |
| Conversación | `not_in_review` | La revisión ya no está abierta | Aviso | Actualizar |
| | `approval_rejected` | Aprobación rechazada | Error | Empezar de nuevo |
| | `operation_failed` | No se pudo completar la operación | Error | Actualizar |
| | `restart` | La conversación no puede continuar | Error | Empezar de nuevo |
| | `too_many_streams` | Demasiadas pestañas abiertas | Aviso | Reintentar |
| Servicios externos | `rate_limited` | Límite de uso alcanzado | Aviso | Reintentar, tras la cuenta atrás de `retry_after` |
| | `service_unavailable` | Servicio no disponible | Error | Reintentar |
| | `provider_timeout` | El modelo no respondió a tiempo | Aviso | Volver a generar |
| Generación | `invalid_model_output` | La respuesta del modelo no es válida | Error | Volver a generar |
| | `citation_failed` | La propuesta no es válida | Error | Volver a generar |
| | `coverage_failed` | La suite no es válida | Error | Volver a generar |
| | `quality_failed` | No se pudo revisar la calidad | Error | Reintentar |
| | `publish_failed` | No se puede publicar | Error | Volver al recibo |
| Otros | `not_implemented` | Disponible pronto | Neutro | — |
| | `unexpected` | Error inesperado | Error | Reintentar |
| Respaldo | Cualquier otro (versión futura de la API) | No se pudo completar la acción | Error | — |

- Los títulos de `citation_failed`, `coverage_failed` y `publish_failed` son los de UI.md §7.
- Una publicación **parcial** no es un error: llega en `result.errors`, con el estado `approved`, y la pinta la pantalla de Resultado (días 6 a 8).

- `retry_after` se acota a 0–600 s en la UI (un valor infinito vale 600). La acción solo aparece si la pantalla le da un manejador.
- La cuenta atrás es solo visual (`aria-hidden`). Dentro de la alerta va una frase fija para lectores de pantalla («Podrás reintentar dentro de N segundos.»), así la alerta no se anuncia cada segundo.
- Solo los códigos propios de la tabla cuentan como conocidos: `toString`, `__proto__` y otros nombres heredados usan el título genérico.

## 6 bis. Accesibilidad de las piezas

- **Tarjeta de flujo:** el nombre accesible es la etiqueta («Preparar pruebas»). La ayuda, o el motivo por el que está desactivada, va como descripción (`aria-describedby`), para que no se lea pegada al nombre.
- **Q de fase:** al bajar de fase (otra conversación con la cabecera montada), anima desde la fase anterior a la nueva, nunca desde una Q más llena.
- **Anillo de consumo:** un valor que no es un número se trata como ausente y el anillo no se pinta.

## 7. Herramientas

- **Versiones exactas** (`.npmrc` con `save-exact`) y `package-lock.json` versionado.
- **TypeScript 6.0**, no 7: `typescript-eslint` 8 solo admite `<6.1`.
- **ESLint 9**, no 10: `eslint-plugin-jsx-a11y` 6 aún no admite ESLint 10. npm marca ESLint 9 como fuera de soporte; se subirá cuando jsx-a11y lo admita.
- **Reglas de seguridad en ESLint** (`eslint.config.js`). Dan error:
  - inserción de HTML: `dangerouslySetInnerHTML`, una asignación a `innerHTML`/`outerHTML` (también con corchetes), `insertAdjacentHTML`, `document.write`/`writeln`;
  - ejecución de código: `eval`, `new Function`, `setTimeout` con cadena;
  - almacenamiento: `localStorage`, `sessionStorage` (también vía `window` y `globalThis`), `indexedDB` y `document.cookie`.
