# Traspaso de T-56 (frontend React, área B) · 2026-10-07

**Estado:** T-56 🔄. En `PreProduccion`: el flujo de la HU, el de QA (QA 1 a QA 5), Cobertura (PA-326), Memoria, los dos nombres de los diffs (PA-341, #7), Administración y Revisar la calidad (sesión MCP), UI.md v2.0 (#8), PA-325/PA-312 (#9), `ses-web-fixes` (PA-332 a PA-336), la prueba de PA-332 (#14), PA-406 (#10), PA-335 (#11), PA-330 web (#13), Editar a mano parte B (#12), PA-127 (#15) y la ronda de `ses-web-pulido` (PA-427 a PA-431). **Bloque en curso: pulido final**, parte 1 en `t56-pulido` (#16) y parte 2 en `t56-pulido-2`.
**PR abiertas:** [#16](https://github.com/maujimenez4/agente-af-qa/pull/16) `t56-pulido → PreProduccion` (pulido final, parte 1: pasos 1 a 5). La parte 2 sigue en `t56-pulido-2` (sale de `t56-pulido`); su PR, cuando se fusione la #16. Fusionadas: de la #2 a la #15.
**Issue de seguimiento:** [#5](https://github.com/maujimenez4/agente-af-qa/issues/5) («T-56 · Frontend React: seguimiento»). `gh` no está instalado: las PR, los issues y los comentarios se preparan, se copian al portapapeles y se pegan a mano.
**Arrancar:** `cd web && npm ci && npm run dev:mock` (usuarios `af-demo`, `qa-demo` y `admin-demo`; contraseña ficticia `demo`, solo en MSW). Catálogo: `/?catalogo`.
**Leer antes:** `DESIGN-DECISIONS.md`, `README.md` (incluye `?simular=`), `docs/api/README.md` («Novedades para el frontend») y las filas PA-300 en adelante del Kanban.

## Novedades de la principal (2026-10-07, tarde)
- **Ronda de la sesión UI (`ses-web-pulido`) en `PreProduccion`:**
  - PA-427: la Q se anima en Revisar la calidad;
  - PA-428: extractos de las fuentes con formato (`MarkdownBlocks`, sin «»);
  - PA-429: el chat empieza abajo y solo baja solo si la persona seguía el final (`useStickToBottom` en `Workspace`);
  - PA-430: «Generando una nueva versión…» al iterar;
  - PA-431: «Disponible pronto» en Documentos y en Usuarios y roles de Ajustes.

  Tocó `components/Markdown/`, `Proposal/ProposalViews.tsx`, `Workspace/` (con `useStickToBottom.ts`), `Chat/Chat.tsx`, `States/LoadingState.tsx` y `QMark/LoadingQ.tsx`.
- **PA-435 decidida:** la regla del backend se mantiene (no hay nota sin cambio); la web lo explica junto a *Guardar*.
- **Un CA sin caso bloquea la aprobación de la suite** (una RN sin caso sigue avisando sin bloquear). El backend lo hace otra sesión y el contrato no cambia. **Web hecha** en `t56-pulido` (aviso «Falta un caso para CA-03» y *Aprobar y publicar* desactivado en el recibo; `?simular=sin-cubrir`). **Pendiente: comprobarlo contra la API real cuando la principal avise** (que el rechazo llega en `review.error` y se ve tal cual). **Cuando lo confirme, actualizar `web/DEMO.md`** para enseñar también el bloqueo por un CA sin caso en la variante B (API real); hoy solo se enseña con la API simulada (§3).
- **Pulido final** en `t56-pulido`, desde `origin/PreProduccion` (`6c15438`). Al empezar: Vitest 2404/2404, lint, build y `api:check` en verde. A `origin/t56-editar` solo le quedaba sin fusionar un commit del HANDOFF ya desfasado (`498e9c5`): se borra al cerrar el pulido.

## Novedades de la principal (2026-10-07)
- **Fusionadas juntas** la #14, la #10, la #11 y la #13, en ese orden. Con las cuatro: lint, `tsc` y `api:check` limpios, y Vitest 2191/2192.
- **PR #12** (`t56-editar`) chocaba en `web/HANDOFF.md` y `docs/KANBAN.md`: hecho el `git merge` de `PreProduccion` conservando ambos lados, Vitest 2375/2375 y push.
- **`ResultScreen.pa325.test.tsx`** (de la #9) era la única que fallaba con todo junto, y a veces en `PreProduccion` (`test_simulated_story_has_no_keys_nor_links` y `test_published_suite_subtasks_are_text_when_browse_url_null`); sola pasaba siempre. Hay que hacerla determinista: entra en **PA-127**.
- **Causa encontrada (PA-127):** con MSW 3 algunas peticiones se saltan la interceptación y salen a la red real (`fetch failed`); si le toca a `/auth/me`, la prueba arranca en el login. No es lentitud. Arreglo y plan en `t56-pruebas` (aviso en el issue #5 antes de tocar `package.json` y el setup de las pruebas).

## Novedades de la principal (2026-10-06)
- **PA-331 hecha en la API:** iterar una suite aplica el cambio pedido y conserva los IDs de los casos que no cambian.
- **PA-330:** la parte de la API está en `PreProduccion` (`SourcePreview.tokens`, `budget.fixed` y `budget.total`; tipos regenerados en `c397c8a`). **La parte web es nuestra** y depende del `signal` de `api.sources` que trae `ses-web-fixes` (PA-336). El número que pinte la web es una **estimación**: al excluir un documento, el RAG rellena su hueco con otro, así que manda la confirmación del servidor (`POST /start/sources`).
- **Guion de la demo:** con `qwen3:1.7b` las RN saldrán **sin caso** (el modelo no rellena `rule_ids`, PA-122). UI.md §6.3 (`t56-uimd`) ya dice que una RN sin caso se avisa en Cobertura pero no bloquea la aprobación.

## Pulido final (2026-10-07)
- **PR 1 · [#16](https://github.com/maujimenez4/agente-af-qa/pull/16)** (`t56-pulido`, pasos 1 a 5): PA-344 y PA-435 (Editar a mano), un CA sin caso bloquea la aprobación de la suite (recibo e Iterar, con `?simular=sin-cubrir` y el recorrido completo en la API simulada), PA-131, la revisión general (accesibilidad y tamaños), el anillo «consumo total», PA-346 y UI.md v2.1. spec-checker CONFORME y security-reviewer APTO.
- **PR 2** (`t56-pulido-2`, sale de `t56-pulido`; se abrirá cuando se fusione la #16, tras traer `origin/PreProduccion`): PA-343, PA-342, PA-347, PA-304 (propuesta en `docs/diseno/CORRECCIONES-LIENZO.md`), el título provisional (se queda), la API simulada con huellas de 64 hexadecimales (editar tras iterar daba 422), el guion de la demo ([DEMO.md](DEMO.md)), este HANDOFF y el README.
- **Componentes compartidos tocados** (avisados en la descripción de la #16): `ChatLog` (`role="log"` en un contenedor), `SidePanel` (`bodyLabel`), la clave de la lista de conversaciones, `.id` de Proposal, Markdown, el anillo del carril; en la PR 2, además, `Button` (acepta `ref`), `useLayer` (`inertBehind`), `Workspace` y la lista de conversaciones (`inert` bajo el velo).
- **Pendiente de la principal:** confirmar el bloqueo por un CA sin caso contra la API real (y entonces actualizar DEMO.md, variante B) y PA-345 (ejemplo `task: functional` del contrato, comentada en el issue #5).
- **PA-310** sigue bloqueada: `eslint-plugin-jsx-a11y` 6.10.2 solo admite ESLint hasta la 9 (comprobado el 2026-10-07).

## T-57: punto de control
**Propuesta, pendiente del punto de control.** La decisión entre React y Streamlit la toma el responsable cuando el flujo de QA funcione contra la API real. Mientras, se sigue con React y Streamlit (`app/`) se mantiene como plan B. El guion de la demo está en [DEMO.md](DEMO.md).

## Hecho
- **Flujo de la HU contra MSW:** login, Inicio, Elegir en Jira, Origen (presupuesto de tokens y conversación de la ronda 8), Generando e Iterar (versión «Jira», *Detener* y *Reintentar*), Recibo con la huella exacta y Resultado simulado, publicado o en parte; *Abrir <clave> en Jira* (PA-318).
- **Flujo de QA por roles** (`DESIGN-DECISIONS.md` §4 bis): QA escribe la clave de la HU.
  - QA 1 · Origen (tipos de caso, «Incluir además» plegado);
  - QA 2 · Generando;
  - QA 3 · Iterar la suite (Casos, Cobertura, Datos y riesgos, Estrategia);
  - QA 4 · Recibo (una casilla: `publish_suite`);
  - QA 5 · Resultado (simulado, publicado o en parte en `approved`).
- **Flujo unido HU → QA** fuera de la entrega: `QA_HANDOFF_ENABLED = false` (`src/app/features.ts`). El cliente, el MSW y los componentes se conservan con sus pruebas.
- **Suite sintética del MSW** (`src/mocks/qaSuite.ts`) mientras el contrato no traiga una revisión de QA (PA-326) ni las etiquetas de los pasos por modo (PA-327). La Q de carga y la lista de pasos funcionan con 4 o 5 pasos.
- **Compositor:** Intro envía, Mayús+Intro hace un salto de línea.
- **Contrato:** `src/api/client.contract.ts` hace fallar `tsc` si un método del cliente no devuelve exactamente la respuesta de su ruta.
- **Seguridad:** `safeHref` y su regla de ESLint (PA-308).
- **Tamaños:** 1024×768, 1280×800 y 1440×900 sin scroll de página ni títulos cortados; lista de conversaciones larga con scroll interno.
- **Pruebas:** no dependen del reloj (SSE de prueba abierto, sondeo disparado por la prueba) y Vitest usa la mitad de los núcleos.
- **Editar a mano** de la HU (PA-340 pendiente de validar por la principal), **Revisar la calidad**, **Memoria** y **Administración**, fusionados.
- **Ventanas estrechas** (PA-335) y **accesibilidad** revisadas en el pulido final a 1024, 1280 y 1440 px al 100, 125 y 150 % (axe WCAG 2.1 A/AA).
- **Disponible pronto:** *Editar a mano* de la suite de QA, auditoría, historial, documentos y usuarios en Ajustes, *Registrar la ejecución* (QA 6) y *Pedir sus pruebas a QA*.

## API real
**Hecha** por la sesión MCP (rama `ses-web`) el 2026-10-05 y 06: la web funciona contra la API real de punta a punta (HU, QA y Memoria). Informe y hallazgos en `docs/pruebas/WEB-API-2026-10-05.md` (PA-330 a PA-339). La guía sigue en [PRUEBA-API-REAL.md](PRUEBA-API-REAL.md). En este equipo no se monta el backend.

## Sistema de entregas (confirmado por la principal, 2026-10-05)
- **Cada bloque nuevo sale de `origin/PreProduccion` en su propia rama** (desde el 2026-10-06; ya no se encadenan ramas). Nunca push a una rama con PR abierta.
- **Una PR pequeña por bloque terminado**, `<rama del bloque> → PreProduccion`. **Antes de abrirla**, todo en verde:
  - test-writer, spec-checker (CONFORME) y security-reviewer (APTO);
  - Vitest (la suite completa, sin otras sesiones cargando el equipo), lint, build y `npm run api:check`.
- **Al cerrar cada bloque:** push y se prepara la PR (se abre la página en el navegador y la descripción va al portapapeles).
- **Lo que no sea de una entrega va al issue #5:** fallos de la prueba con la API real, preguntas sobre PA y avisos de componentes compartidos.
- **Al leer comentarios con la API de GitHub**, revisar el issue #5 y la última PR.

## Ramas
- **Ya no hay cadena de ramas** ni bloqueos de otras sesiones en `web/`: `ses-web-fixes`, `ses-web-admin`, `ses-web-pulido` y las ramas `t56-*` anteriores están fusionadas. Cada bloque nuevo: `git switch -c <rama> origin/PreProduccion` (salvo la PR 2 del pulido, que sale de `t56-pulido`).
- **Limpieza (2026-10-07):** borradas en local y en `origin` las ramas del responsable ya fusionadas en `PreProduccion` (la lista, en el registro diario del Kanban).

## Reglas de trabajo
- **Responder siempre en español** (también los resúmenes, los informes y lo que se prepara para GitHub).
- `git merge origin/PreProduccion` (nunca rebase ni `main`). **Push al terminar cada paso** en verde.
- Commits `T-56: … [RNF-15]`. Parada para revisión visual en cada pantalla; revisiones al cerrar cada bloque. Kanban: solo mis filas y el registro diario. No tocar `app/`.
- Cada PR, issue o comentario se enseña antes y se copia al portapapeles (UTF-8).
- Verificación visual: Edge sin interfaz con CDP (scripts fuera del repo). Usa siempre un **perfil nuevo**: uno viejo conserva el Service Worker de MSW y da «Error inesperado».

## Coordinación con otras sesiones (2026-10-05)
- **Antes de tocar un componente compartido**, avisar a la persona responsable para que avise a la principal: `Composer`, `AppShell`, el panel y la cabecera (`Workspace`), los estados (`States`), la lista de conversaciones, los botones, y las pantallas que comparten la HU y QA (Inicio, Origen, Generando, Iterar, Recibo y Resultado).
- **`web/src/api/`** (`client.ts`, `types.ts`, `client.contract.ts`): avisar antes de tocarlo (al responsable y en el issue #5). En el pulido final no se ha tocado.

## Bloque «contrato de QA en la web» (fusionado en `PreProduccion`)
- **PA-326 en Cobertura:** `uncovered` con `null` (o sin el campo) = «no se sabe»: sin distintivo, sin «Todos los CA cubiertos» y sin «cobertura validada». Listas vacías = «Todos los CA cubiertos». Con elementos = «1 CA y 1 RN sin caso», el aviso «Sin ningún caso: …» y filas «· Sin caso». Solo para la versión en revisión. Detalle en `DESIGN-DECISIONS.md` (QA 3).
- **`coverage_md`:** botón *Descargar la matriz* (`matriz-<CLAVE>.md`); con `null`, no aparece. **Pieza reutilizable para Memoria:** `DownloadButton` (`src/components/Download/`) sobre `downloadText` (`src/security/download.ts`, nombres solo ASCII). ESLint prohíbe `createObjectURL` y asignar `href` fuera de ese archivo.
- **PA-118:** `generate.mjs` copia `components.examples` a `examples.json` (`components.examples.<Nombre>`). El MSW usa `ConversationQaInReview` y los 4 pasos de QA; `qaSuite.ts` solo simula otra clave, iterar y publicar.
- **`mockBaseline` fuera:** la versión «Jira» es la del ejemplo (CA-01, sin CA-02).
- **PA-328:** recuentos con `countLabel` (`src/text/plural.ts`), también «1 fuente» en el modo HU de Iterar (cambio menor, en la descripción de la PR).
- `?simular=sin-cubrir` y `?simular=cobertura-desconocida` en `web/README.md`.
- **Issue #5:** avisado el cambio de `examples.json`.
- Sin PR propia: entró con la fusión de `ses-web`.

## Bloque Memoria (fusionado en `PreProduccion`)
- **Zona Memoria** en el carril para los tres roles (icono nuevo; admin sigue entrando en Ajustes). Lista con proyecto, búsqueda (300 ms) y `limit=200`, sin «Mostrar más»; detalle por secciones como texto, en el orden del `.md`, con *Descargar la memoria* (`DownloadButton`) e «Indexada»/«No indexada». Trabajo sigue montado (oculto) mientras se mira Memoria.
- **Cliente** (`web/src/api/`, solo añadiendo, commits aparte y avisado en el issue #5): `api.memories`, `api.memory` (rechaza «.» y «..»), `MemorySummary`, `MemoryOut`.
- ***Ver la memoria*** en el Resultado de la HU publicada (o en parte) abre Memoria con la clave; un 404 sale como su tarjeta de error.
- **MSW:** ejemplos del contrato (DEMO-9001 y DEMO-9002); publicar una HU deja su memoria indexada; `?simular=memoria-no-encontrada` (404) y `?simular=sin-memorias`.
- **PA-329** (diseño de Memoria): validado por la principal el 2026-10-06 (UI.md §4.9). Quedaban dos notas para ella (el «se ha generado e indexado» del Resultado frente a `indexed: false`, y `docs/api/README.md` que aún cita Memoria como pendiente).
- Detalle en `DESIGN-DECISIONS.md` (§4 bis, Memoria).

## PA abiertas
- **Del área B:** PA-304 (aplicar en el lienzo la propuesta de `docs/diseno/CORRECCIONES-LIENZO.md`) y PA-310 (ESLint 10, bloqueada).
- **De la principal:** PA-340 (validar el diseño de Editar a mano y decidir si la suite de QA se edita a mano), PA-345 (ejemplo del contrato) y la prueba del CA sin caso contra la API real.
- **Cerradas en el pulido final:** PA-131, PA-342, PA-343, PA-344, PA-346, PA-347 y PA-435.

## Siguiente
1. Cuando se fusione la #16: `git merge origin/PreProduccion` en `t56-pulido-2`, Vitest, lint, build y `api:check`, y preparar la PR 2.
2. Cuando la principal confirme el bloqueo por un CA sin caso contra la API real: comprobarlo en la web (el rechazo llega en `review.error`) y actualizar DEMO.md (variante B).
3. T-57: la decisión entre React y Streamlit, con la demo (DEMO.md).

Antes de cada PR: test-writer, spec-checker (CONFORME) y security-reviewer (APTO), y Vitest, lint, build y `api:check` en verde. No empezar ningún bloque sin la confirmación del responsable.
