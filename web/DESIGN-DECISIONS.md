# Decisiones de diseño de `web/` (T-56)

Lo que aquí figura está **decidido** y no se vuelve a discutir salvo que lo cambie la persona responsable del área B. La referencia visual es el lienzo «Propuesta mixta» (`docs/diseno/lienzo/`). Cuando el lienzo se contradice a sí mismo, manda esta tabla. Cuando contradice a `docs/specs/UI.md`, manda UI.md.

Decidido el 2 de octubre de 2026.

## 1. Incoherencias del lienzo resueltas

| # | Tema | Decisión |
|---|---|---|
| 1 | Paleta de aviso o simulación | `#FFF8E6` fondo · `#F0D48A` borde · `#6B4A00` texto. La variante `#FFF3E0`/`#F0C98A`/`#6B3A00` de `Estados.dc.html` se descarta |
| 2 | Color del aviso de consumo de tokens | Cuándo avisa lo fija la decisión 17 (desde `warning_threshold`; el «≥ 90 %» del lienzo ya no aplica). Dos tokens según el fondo: `--color-warn-on-dark: #FFB48A` (carril navy) y `--color-warn: #B35C00` (fondos claros) |
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
| 17 | Anillo de consumo de tokens del carril | Dato de `GET /api/v1/settings/usage` (`tokens_today`, `warning_threshold`, `scope: "global"`, PA-305). Es el consumo **de toda la instalación** en el día, no de la persona: el texto visible («24 %» con «instalación» debajo) y el nombre accesible («Consumo de tokens de hoy de toda la instalación: …») lo dicen (§4 bis). Aviso desde `warning_threshold`. Con 503 u otro error, o sin dato, el anillo no se pinta |

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
- **Operaciones largas:** crear, iterar, aprobar y revisar la calidad responden **202**. El avance llega por SSE y, como respaldo, consultando `GET /conversations/{id}`.
  - **El SSE se lee con `fetch` y un `ReadableStream`, no con `EventSource`** (`src/api/events.ts`). Así se cierra con `AbortController`, no reconecta solo y se prueba con MSW en Vitest (jsdom no tiene `EventSource`). Si el flujo se corta sin `result`, quien escucha consulta `GET /conversations/{id}`.
  - Mientras hay una operación en curso, otra sobre la misma conversación da 409 `not_in_review`.
  - El cliente **cierra el flujo tras `result`** de una conversación terminada (simulada, publicada o descartada) y no entrega nada de lo que llegue después.
  - **Forma de los eventos** (`api/app.py`):
    - `progress` trae un `ProgressStep`;
    - los finales (`review_ready`, `result`, `error`) traen la conversación completa, como `GET /conversations/{id}`;
    - un fallo dentro del flujo llega como `error` con `{"error": ErrorBody}`.

    `onError` recibe siempre un `ApiError`, junto con la conversación si llegó entera, también cuando falla la apertura del flujo.
  - Una cancelación (búsqueda que se sustituye por otra) se reconoce por `name === 'AbortError'` y nunca se pinta como error.
  - Como mucho 3 flujos abiertos por persona: el cuarto da 429 `too_many_streams`.
- **Errores:**
  - Siempre `{"error": {"code", "message", "retry_after"}}`. `code` es una lista cerrada (`ErrorBody.code`, PA-306).
  - El **título**, el tono y la acción se eligen por `code` (§6). El **mensaje** se muestra tal cual.
  - Los fallos de la generación llegan en `ConversationOut.error` o `QualityReviewOut.error`, no como error HTTP.
  - Un `code` que no esté en la lista (versión futura de la API) usa un título genérico y el mismo mensaje.
- **Aún sin implementar en la API:**
  - `/conversations/{id}/handoff`, `/qa/*` (T-54) y `/executions` (T-47) ya están en el contrato, pero el frontend aún no los usa: sus pantallas son «disponible pronto» hasta los días 6 a 8. La API simulada responde 404 `not_found` a lo que no simula (`not_implemented` salió de `ErrorCode`).
- **Aprobar:** se devuelve la `fingerprint` exacta del último `review`. Una respuesta no válida llega en `review.error`, no como error HTTP. Un 409 se distingue por `error.code` (`approval_rejected` → empezar de nuevo; `not_in_review` → actualizar el estado).
- **API simulada:**
  - **MSW** para desarrollo y pruebas, con un único conjunto de handlers construido con los ejemplos del contrato y un estado en memoria que también simula el SSE.
  - Solo se activa con `VITE_API_MOCK=1` en desarrollo. `mockServiceWorker.js` no entra en el build de producción.
  - **Prism** (`npx @stoplight/prism-cli mock docs/api/openapi.yaml`) solo como comprobación puntual de que las peticiones cumplen el contrato; no se instala.
  - Los tipos se generan desde el contrato con **openapi-typescript**.
  - Se instalan en los días 2 a 4.

## 4 bis. Navegación y pantallas (días 2 a 4)

Decidido el 2 de octubre para llegar a la demo de T-57 (Inicio, Elegir en Jira, Origen, Generando e Iterar navegables contra MSW).

- **Navegación por estado**, sin router: los `thread_id` nunca salen de la URL (T-52). El catálogo del sistema de diseño solo existe en desarrollo (`?catalogo`, PA-309).
- **Login mínimo** con las piezas del sistema (PA-311, pendiente de validar por la principal).
- **Admin:** una pantalla simple «Disponible pronto». Ajustes queda para después de T-57.
- **Elegir en Jira:** además de *Usar la épica* y *Usar DEMO-3* (UI.md §4.2), si solo se cambia de proyecto aparece **«Usar el proyecto X»**: el selector de proyecto de Inicio abre este diálogo (UI.md §4.1) y hace falta poder cambiarlo sin fijar un origen. El buscador espera 300 ms entre pulsaciones.
- **Lista de conversaciones con error:** si `GET /conversations` falla, la lista muestra la tarjeta de error con *Reintentar* (UI.md §7), no el estado vacío.
- **Arranque guiado:** el aviso de `project_changed` e `ignored_projects` (T-53, PA-313) se hace en Origen y fuentes, donde se fija la operación. Con `project_changed`, el proyecto se fija una vez con `POST /projects/choose`.
- **Origen y fuentes** (Mixta 2):
  - **Operación según lo elegido:**
    - una opción del arranque guiado trae su `origin` listo;
    - una HU de Jira o de los recientes se evoluciona;
    - una épica crea una HU nueva dentro de ella (flujo `need`, origen `epic`).
  - **Restricciones:**
    - en una necesidad nueva se añaden al texto del origen («Restricciones: …»);
    - al evolucionar van como primer `feedback`;
    - los detalles que se escriben en el compositor van con ellas.
  - **Fuentes:**
    - la de origen es obligatoria (casilla desactivada);
    - la memoria sale como «prioritaria»;
    - una fuente desmarcada indica que no influirá en la propuesta y va en `excluded_sources`.
  - **Presupuesto de tokens** (PA-102): «Contexto · 2.350 de 6.000 tokens» con una barra, debajo de las fuentes, a partir de `budget` de `POST /start/sources`. Aviso (borde y barra ámbar) desde el 90 % o si hay fuentes que no caben, con «N fuentes no caben y no se enviarán al modelo» y «N incidencias se recortan para que quepan».
    - La **lista** sale de la consulta sin exclusiones: con `excluded_sources`, el backend ya no devuelve las desmarcadas y no se podrían volver a marcar.
    - Al cambiar las casillas solo se vuelve a pedir el **presupuesto**, 300 ms después del último clic; si esa consulta falla, el presupuesto deja de pintarse (nunca uno viejo).
    - Los números llevan separador de miles también con cuatro cifras («2.350»), como en el anillo del carril.
- **Generando** (Mixta 2b):
  - **Pasos:** la Q de carga y la lista de pasos siguen los eventos `progress`.
  - **Fin:** con `review_ready`, el titular pasa a «Propuesta lista · Versión N · M cambios frente a Jira» (los cambios son `impact.diffs`, solo al evolucionar) y aparece *Ver la propuesta*.
  - **Si el SSE se corta** sin evento final, se consulta `GET /conversations/{id}` cada 2 s hasta que deja de generar.
  - **Error:** sale su tarjeta. Si la conversación quedó en `state=error` (también tras *Detener*), su acción (*Volver a generar*, *Reintentar*) repite el paso que falló con `POST /retry` (PA-276) y se sigue el SSE de nuevo. Si no hay conversación que reintentar (falló la lectura del estado), vuelve a Origen y fuentes con la misma petición o, al retomar desde la lista, a Inicio. Un `/retry` rechazado (`not_in_error`) muestra su tarjeta con *Actualizar*, que lee el estado y sigue desde ahí.
  - **Detener** (PA-314): como en el lienzo, mientras genera el botón de enviar del compositor pasa a *Detener la generación*. Al pulsarlo (`POST /cancel`) queda desactivado con «Deteniendo la generación…» (en el botón y en el titular), porque la API termina el paso en curso: una llamada al LLM ya empezada no se corta. Acaba en `cancelled` («Generación detenida», con *Reintentar*) o, si el siguiente paso era la revisión, en la propuesta. Un `not_cancellable` no se muestra (ya había terminado); otro error sí, y la generación sigue.
- **Iterar** (Mixta 3):
  - **Mensaje del asistente:** cada versión lleva un resumen compuesto en el frontend con `changes_from_previous` y el impacto («Versión 3 lista. CA-01: … Afecta también a DEMO-2 (…)»), porque el contrato no trae un mensaje. La versión nueva se escribe letra a letra.
  - **Peticiones de cambio** (`POST /iterate`): vuelven a seguir el SSE con «Escribiendo la respuesta». La versión nueva se abre en el panel (y lo vuelve a mostrar si estaba plegado).
  - **Marcas «Cambiado en vN» y «Nueva»:** `impact.diffs` es el diff **acumulado frente a Jira** (`core/impact/analysis.py`), así que no dice qué cambió en cada versión. Desde la v2 las marcas comparan cada CA y RN con los de la versión anterior (`ConversationOut.versions`); en la v1, con los diffs. La pestaña *Cambios* y el recuento «N cambios frente a Jira» sí usan `impact.diffs`. La API simulada también acumula.
  - **HU nueva** (flujo `need`): no hay HU en Jira, así que no se habla de «cambios frente a Jira». La pestaña *Cambios* va sin recuento y lo explica.
  - **Historial:** los cambios pedidos antes de retomar (`ConversationOut.feedback`) se pintan siempre al principio del chat.
  - **Sugerencias:** «Añade un criterio de error», «Aclara el alcance» y «Revisa INVEST». El lienzo trae «Busca la fuente del CA-04» en lugar de «Aclara el alcance», pero el contrato no da la cita de cada CA (PA-315) y no se puede saber qué CA no tiene fuente.
  - **Resumen del asistente:** además de lo que cambió y a qué afecta, «Queda 1 pregunta abierta» o «Quedan N preguntas abiertas» si `open_questions` no está vacío, para que no pasen desapercibidas (no está en el lienzo).
  - **Tarjeta de error:** *Actualizar* vuelve a leer la conversación (si ya no está en revisión, vuelve a Inicio); *Volver a generar* y *Reintentar* repiten **la operación que falló**: si falló `POST /iterate`, el cambio pedido (sin repetirlo en el chat); si falló la iteración ya en marcha o se detuvo, `POST /retry`; o *Descartar*, o la relectura de *Actualizar*. *Detener* funciona igual que en Generando; *Empezar de nuevo* vuelve a Inicio; *Iniciar sesión* cierra la sesión y vuelve a la pantalla de inicio de sesión.
  - **Panel:** versiones v1…vN de `ConversationOut.versions` más la de la revisión; pestañas Propuesta, Cambios, Impacto y Fuentes.
  - **Lo que el contrato no da:**
    - la versión «Jira» del lienzo (la HU tal como está en Jira; PA-316);
    - el aviso «CA sin fuente», porque los CA no traen cita propia (PA-315).
  - **Pie del panel:**
    - *Descartar* pide confirmación y llama a `POST /discard`;
    - *Editar a mano* y *Revisar y aprobar* son «disponible pronto»: se pueden enfocar, llevan su descripción y no hacen nada.
  - **Modelo:** «Generado con local · qwen3:4b-instruct» sale de `Artifact.model_used`. El selector del compositor sigue en solo lectura («Modelo automático»): elegir modelo por petición (RF-42) llega con los ajustes, después de T-57.
  - **Editar a mano:** aplazado a los días 6 a 8 por decisión de la persona responsable del área B (pulir el recorrido de la demo antes). `POST /conversations/{id}/edit` ya está en el contrato.
- **Plegar el panel derecho** (fallo reportado en Origen: costaba encontrarlo):
  - un solo botón con texto, «Ocultar el panel» o «Mostrar el panel», siempre en la cabecera de la conversación, a la derecha de la Q de fase. Ya no hay un icono suelto en la cabecera del panel;
  - plegado, el panel se oculta (`hidden`) sin desmontarse: conserva la pestaña, las casillas y las restricciones;
  - el botón cambia de texto y no lleva `aria-pressed` ni `aria-expanded`, para no anunciar dos veces el estado. `aria-controls` apunta al panel;
  - en ventanas estrechas el panel encoge hasta 320 px antes que la conversación (mínimo 360 px). En la cabecera, la Q y el botón no encogen: se corta el título.
- **Retomar una conversación** de la lista (T-52): se abre según su estado (generando → Generando; en revisión → Iterar; terminada → su aviso). Si terminó en `error`, se muestra `ConversationOut.error` tal cual (UI.md §7), sin acción en la tarjeta, con *Reintentar* (`POST /retry`, abre Generando) y un botón para empezar otra; si `/retry` responde `not_in_error`, se muestra ese mensaje y solo queda empezar otra. Si se retoma generando y falla sin conversación que reintentar, la acción lleva a Inicio: no hay una petición de Origen a la que volver.
- **Flujos fuera de la demo de T-57:** «Revisar la calidad» y «Preparar pruebas» llevan a una pantalla «disponible pronto» después de Inicio.
- **Selector de modelo del compositor:** solo lectura («Modelo automático» o el que fije la sesión) hasta Iterar.
- **Anillo de consumo:**
  - en el carril, «24 %» y debajo «instalación». El porcentaje es `tokens_today / warning_threshold`, acotado a 100;
  - nombre accesible: «Consumo de tokens de hoy de toda la instalación: 12.345 de 50.000, 25 % del umbral de aviso».
  - se vuelve a pedir al cargar y cada 60 s (`USAGE_REFRESH_MS`): el consumo cambia despacio y no hace falta más precisión.

## 5. Textos de la lista de conversaciones

Salen de `ConversationSummary` (`mode`, `origin_kind`, `origin_key`, `status`, `version`) con el formato «flujo · estado» del lienzo.

- **Flujo:** `qa` → «Pruebas de DEMO-3»; `functional` con origen `story` → «Evolucionar DEMO-3»; con `epic` → «HU nueva en la épica DEMO-1»; con `need` → «Nueva necesidad».
- **Título:** el de la API, salvo «Nueva HU en DEMO-1» (`core/conversations.py`), que se muestra como «HU nueva en la épica DEMO-1» en la cabecera, el evento, la lista y el buscador (`conversationTitle`, PA-317).
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

El mensaje es siempre el de la API, tal cual y como texto. Lo que decide el frontend, para los 28 valores de `ErrorBody.code` (`docs/api/README.md`, `api/errors.py`):

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
| | `handoff_unavailable` | La HU ya no está disponible | Aviso | Actualizar |
| | `operation_failed` | No se pudo completar la operación | Error | Actualizar |
| | `not_in_error` | No hay nada que reintentar | Aviso | Actualizar |
| | `cancelled` | Generación detenida | Neutro | Reintentar (`POST /retry`) |
| | `not_cancellable` | No se puede detener | Aviso | Actualizar |
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
| Otros | `unexpected` | Error inesperado | Error | Reintentar |
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
