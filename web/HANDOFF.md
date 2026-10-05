# Traspaso de T-56 (frontend React, área B) · 2026-10-05

**Estado:** T-56 🔄. Flujo de la HU completo y **flujo de QA por roles completo** (QA 1 a QA 5), en la PR #6. **Rama de trabajo actual: `t56-qa-cobertura`** (creada desde `area-b` el 2026-10-05). Lint, Vitest, build y `npm run api:check` en verde.
**PR abierta:** [#6](https://github.com/maujimenez4/agente-af-qa/pull/6) `area-b → PreProduccion` («T-56: flujo de QA por roles, recibo y resultado de la suite», bloque 5). **Pendiente** de la prueba del flujo de QA contra la API real en el equipo de la principal y de la aprobación de su responsable. Ya fusionadas: la #2, la #3 y la #4.
**Issue de seguimiento:** [#5](https://github.com/maujimenez4/agente-af-qa/issues/5) («T-56 · Frontend React: seguimiento»). `gh` no está instalado: las PR, los issues y los comentarios se preparan, se copian al portapapeles y se pegan a mano.
**Arrancar:** `cd web && npm ci && npm run dev:mock` (usuarios `af-demo`, `qa-demo` y `admin-demo`; contraseña ficticia `demo`, solo en MSW). Catálogo: `/?catalogo`.
**Leer antes:** `DESIGN-DECISIONS.md`, `README.md` (incluye `?simular=`), `docs/api/README.md` («Novedades para el frontend») y las filas PA-300 en adelante del Kanban.

## T-57: punto de control
**Propuesta, pendiente del punto de control.** La decisión entre React y Streamlit la toma el responsable cuando el flujo de QA funcione contra la API real. Mientras, se sigue con React y Streamlit (`app/`) se mantiene como plan B. El guion de la demo se escribirá al final.

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
- **Disponible pronto:** admin, Revisar la calidad, *Editar a mano*, auditoría, historial, *Ver la memoria*, *Registrar la ejecución* (QA 6) y *Pedir sus pruebas a QA*.

## API real
La prueba la hace **la principal en su equipo** con [PRUEBA-API-REAL.md](PRUEBA-API-REAL.md), la guía única (`API-LOCAL.md` solo enlaza a ella). En este equipo no se monta el backend. Quiere probar el flujo de QA contra su API antes de fusionar la PR del bloque 5.

## Sistema de entregas (confirmado por la principal, 2026-10-05)
- **Una rama propia por bloque mientras la PR anterior siga abierta.** No hacer push a `area-b` mientras la #6 esté abierta: cualquier commit se añadiría a ella. El bloque siguiente va en `t56-qa-cobertura`; su PR se abre (`t56-qa-cobertura → PreProduccion`) cuando la #6 esté fusionada, o antes si la principal lo pide.
- **Una PR pequeña por bloque terminado**, `area-b → PreProduccion`. **Antes de abrirla**, todo en verde:
  - test-writer, spec-checker (CONFORME) y security-reviewer (APTO);
  - Vitest (la suite completa, sin otras sesiones cargando el equipo), lint, build y `npm run api:check`.
- **Al cerrar cada bloque:** push y se prepara la PR (se abre la página en el navegador y la descripción va al portapapeles).
- **Lo que no sea de una entrega va al issue #5:** fallos de la prueba con la API real, preguntas sobre PA y avisos de componentes compartidos.
- **Al leer comentarios con la API de GitHub**, revisar el issue #5 y la última PR.

## Reglas de trabajo
- `git merge origin/PreProduccion` (nunca rebase ni `main`). **Push al terminar cada paso** en verde.
- Commits `T-56: … [RNF-15]`. Parada para revisión visual en cada pantalla; revisiones al cerrar cada bloque. Kanban: solo mis filas y el registro diario. No tocar `app/`.
- Cada PR, issue o comentario se enseña antes y se copia al portapapeles (UTF-8).
- Verificación visual: Edge sin interfaz con CDP (scripts fuera del repo). Usa siempre un **perfil nuevo**: uno viejo conserva el Service Worker de MSW y da «Error inesperado».

## Coordinación con otras sesiones (2026-10-05)
- **Antes de tocar un componente compartido**, avisar a la persona responsable para que avise a la principal: `Composer`, `AppShell`, el panel y la cabecera (`Workspace`), los estados (`States`), la lista de conversaciones, los botones, y las pantallas que comparten la HU y QA (Inicio, Origen, Generando, Iterar, Recibo y Resultado).
- **`client.ts` y `types.ts`** (y el resto de `web/src/api/`) los coordina **la sesión MCP** (rama `ses-web`). No tocarlos sin avisar antes.

## Detalle de PA-326, PA-327 y PA-118 (ya en el contrato desde el 2026-10-05)
- **PA-326:**
  - **`ReviewPayload.coverage_md`**: la matriz, igual que `matriz-CLAVE.md`;
  - **`ReviewPayload.uncovered {criteria, rules}`**: `null` significa «no se sabe» y las listas vacías, «todo cubierto». **No se tratan igual**: con `null`, no se afirma «Todos los CA cubiertos» por esta vía; con listas vacías, sí; con elementos, se muestran como no cubiertos.
  - Cambiar la pestaña Cobertura y el distintivo, y la suite sintética del MSW, para usarlos.
- **Ejemplo de QA en revisión:** `components.examples.ConversationQaInReview`. Con **PA-118**, `tools/api-types/generate.mjs` copiará también `components.examples` a `src/api/examples.json`. Entonces el MSW y las pruebas usarán ese ejemplo en lugar de `mockSuiteConversation`.
- **PA-327 (ya fusionada):** QA tiene 4 pasos (sin «Guardar la memoria») con sus etiquetas. El frontend ya pinta los que lleguen, tal cual, y la Q funciona con 4 o 5: falta que la API simulada use las etiquetas de QA (siguiente PR) y comprobar los textos con la API real.

## Siguiente PR: contrato de QA (PA-326, PA-118, `jira_baseline`)
El contrato ya trae PA-326 y PA-327 (fusionado en `area-b` con la PR del bloque 5; `schema.d.ts` y `examples.json` regenerados, sin cambios en la interfaz). Queda:
- **PA-326 en Cobertura:** `ReviewPayload.coverage_md` y `ReviewPayload.uncovered {criteria, rules}`. `null` es «no se sabe» y las listas vacías, «todo cubierto»: **no se tratan igual**. Con elementos, se muestran como no cubiertos. Ajustar el distintivo «Todos los CA cubiertos».
- **PA-118:** `tools/api-types/generate.mjs` copia también `components.examples` a `examples.json`; el MSW y las pruebas usan `ConversationQaInReview` en lugar de `mockSuiteConversation`.
- **Quitar el apaño de `jira_baseline` del MSW** (`mockBaseline`): el ejemplo del contrato ya no trae el CA-02.
- **PA-327 en la API simulada:** que una generación de QA use las etiquetas de QA (4 pasos), como `QA_STEP_LABELS`.

## Alcance y orden tras el bloque 5
1. **Memoria**, para los tres roles:
   - `GET /memories` con `project`, `q` y `limit`;
   - `GET /memories/{key}` pintado por secciones; el `.md` solo para descargar;
   - «indexada» o «no indexada»;
   - en el MSW, los datos de los ejemplos del contrato.
2. **Revisar la calidad.**
3. **Administración mínima**, solo para admin:
   - probar conexiones con `POST /admin/connections/test`: una cada 10 s, con 429 y `retry_after`, y con CSRF;
   - modelos por tarea en solo lectura (`GET /admin/models`);
   - `publish_mode` de `GET /settings` en solo lectura, con el aviso «Simulación: no se escribe nada en Jira»;
   - usuarios, documentos e historial como «disponible pronto»;
   - diseño de la parte de Ajustes de «Propuesta v2» del lienzo, adaptada al estilo de la «Propuesta mixta».
4. **Editar a mano.**

**Fuera de la entrega:** el flujo unido HU → QA, QA 6 (registrar la ejecución) y el selector de modelo funcional.

## PA abiertas
- **Hechas por la principal, pendientes de adoptar en `web/`** (siguiente PR): **PA-326** (`coverage_md` y `uncovered`, ejemplo `ConversationQaInReview`) y **PA-327** (pasos de QA por modo, 4 sin `memorize`; el frontend ya los pinta).
- **Del área B:**
  - **PA-118** (que `generate.mjs` copie `components.examples` a `examples.json`; siguiente PR);
  - PA-300 (UI.md: *Volver a la propuesta* en el recibo, el aviso de modo de prueba solo en simulación y el flujo unido fuera de la entrega);
  - PA-304 (lienzo: foco, Q con reducir movimiento y la fase de la suite en parte);
  - PA-310, PA-312 y PA-325.
- **Cerradas o aplazadas** por la principal (2026-10-05): PA-311 validada (se mantiene el login mínimo), PA-315 aplazada (fuera de la entrega) y el ejemplo de `jira_baseline` corregido (falta quitar el apaño del MSW).

## Siguiente (en `t56-qa-cobertura`)
1. **PA-326 en Cobertura:** `ReviewPayload.coverage_md` y `ReviewPayload.uncovered` (`null` = «no se sabe», listas vacías = «todo cubierto»; no se tratan igual).
2. **PA-118:** que `generate.mjs` copie `components.examples` a `examples.json`; el MSW y las pruebas usan `ConversationQaInReview` (y las etiquetas de QA en la API simulada).
3. **Quitar el apaño de `jira_baseline` del MSW** (`mockBaseline`).
4. Después, por este orden: **Memoria**, **Revisar la calidad**, **Administración mínima** y **Editar a mano** (detalle en «Alcance y orden tras el bloque 5»).

Antes de cada PR: test-writer, spec-checker (CONFORME) y security-reviewer (APTO), y Vitest, lint, build y `api:check` en verde. Esperar la confirmación del responsable antes de empezar Memoria.
