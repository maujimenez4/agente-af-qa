# Traspaso de T-56 (frontend React, área B) · 2026-10-06

**Estado:** T-56 🔄. **Todo lo del área B está fusionado en `PreProduccion`:** el flujo de la HU, el de QA por roles (PR #6, `area-b`, 2026-10-06), el contrato de QA en la web (Cobertura con PA-326, PA-118 y PA-328) y Memoria. Las dos últimas entraron con la fusión de `ses-web` (la sesión MCP fusionó `t56-memoria` para su prueba contra la API), sin PR propia. `t56-qa-cobertura` y `t56-memoria` están igual que `PreProduccion` (`074443d`). Lint, Vitest (1.846), build y `npm run api:check` en verde. **Bloque en curso: Editar a mano**, en `t56-editar` (desde `origin/PreProduccion`), con el reparto que confirmó la principal (abajo).
**PR abiertas:** ninguna. Fusionadas: la #2, la #3, la #4 y la #6.
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
- **Disponible pronto:** Revisar la calidad, *Editar a mano*, auditoría, historial, *Registrar la ejecución* (QA 6) y *Pedir sus pruebas a QA*.

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

## Ramas y reparto (confirmado por la principal, 2026-10-06)
- **Ya no hay cadena de ramas.** `area-b`, `t56-qa-cobertura` y `t56-memoria` están fusionadas. Cada bloque nuevo: `git switch -c <rama> origin/PreProduccion`.
- **Mío (responsable del área B):**
  - **Editar a mano** (`POST /conversations/{id}/edit`; «Reglas para el frontend» de `docs/api/README.md`), rama `t56-editar`;
  - la **parte web de PA-330** (presupuesto de Origen) cuando llegue la de la API (sesión Modelos);
  - **revisar `ses-web-fixes`** antes de que se fusione;
  - **PA-300** (UI.md al día).
- **Sesión UI** (`ses-web-fixes`): PA-332 a PA-336. **No tocar mientras tanto:** `useGeneration`, `SessionProvider`, `client.ts` (401 y `signal`), `suiteText`/`SuiteViews`, Origen y el CSS de Iterar.
- **Sesión MCP** (`ses-web-admin`): Administración mínima y después Revisar la calidad. **No tocar mientras tanto:** el final de `client.ts`, `types.ts`, `client.contract.ts`, `AppShell`, `screens/Admin/`, `App.test.tsx`, `AppShell.memoria.test.tsx` y `Rail.gaps.test.tsx`.
- **Sesión Modelos** (`ses-qa-iterar`): PA-331 (iterar en QA aplica el cambio pedido) y la parte de la API de PA-330.
- **`IterateScreen`:** no tocarlo hasta que se fusione `ses-web-fixes`, o avisar antes a la principal.

## Reglas de trabajo
- `git merge origin/PreProduccion` (nunca rebase ni `main`). **Push al terminar cada paso** en verde.
- Commits `T-56: … [RNF-15]`. Parada para revisión visual en cada pantalla; revisiones al cerrar cada bloque. Kanban: solo mis filas y el registro diario. No tocar `app/`.
- Cada PR, issue o comentario se enseña antes y se copia al portapapeles (UTF-8).
- Verificación visual: Edge sin interfaz con CDP (scripts fuera del repo). Usa siempre un **perfil nuevo**: uno viejo conserva el Service Worker de MSW y da «Error inesperado».

## Coordinación con otras sesiones (2026-10-05)
- **Antes de tocar un componente compartido**, avisar a la persona responsable para que avise a la principal: `Composer`, `AppShell`, el panel y la cabecera (`Workspace`), los estados (`States`), la lista de conversaciones, los botones, y las pantallas que comparten la HU y QA (Inicio, Origen, Generando, Iterar, Recibo y Resultado).
- **`client.ts` y `types.ts`** (y el resto de `web/src/api/`) los coordina **la sesión MCP**: ahora añade al final de `client.ts` los métodos de Administración y Calidad (`ses-web-admin`), y la sesión UI toca el 401 y `signal` (`ses-web-fixes`). No tocarlos sin avisar antes (ver «Ramas y reparto»).

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
- **PA-329** (diseño de Memoria): pendiente de validar por la principal, con dos notas para ella (el «se ha generado e indexado» del Resultado frente a `indexed: false`, y `docs/api/README.md` que aún cita Memoria como pendiente).
- Detalle en `DESIGN-DECISIONS.md` (§4 bis, Memoria).

## Alcance y orden tras el bloque 5
1. ~~**Memoria**~~ (hecho en `t56-memoria`), para los tres roles:
   - `GET /memories` con `project`, `q` y `limit`;
   - `GET /memories/{key}` pintado por secciones; el `.md` solo para descargar;
   - «indexada» o «no indexada»;
   - en el MSW, los datos de los ejemplos del contrato.
2. **Revisar la calidad:** encargada a la sesión MCP (`ses-web-admin`).
3. ~~**Administración mínima**~~ (hecho por la sesión MCP en `ses-web-admin`, fusionada), solo para admin:
   - probar conexiones con `POST /admin/connections/test`: una cada 10 s, con 429 y `retry_after`, y con CSRF;
   - modelos por tarea en solo lectura (`GET /admin/models`);
   - `publish_mode` de `GET /settings` en solo lectura, con el aviso «Simulación: no se escribe nada en Jira»;
   - usuarios, documentos e historial como «disponible pronto»;
   - diseño de la parte de Ajustes de «Propuesta v2» del lienzo, adaptada al estilo de la «Propuesta mixta».
4. **Editar a mano:** del responsable, en `t56-editar` (en curso).

**Fuera de la entrega:** el flujo unido HU → QA, QA 6 (registrar la ejecución) y el selector de modelo funcional.

## PA abiertas
- **Adoptadas y fusionadas:** PA-326, PA-327 (en la API simulada), PA-118 y PA-328.
- **De la prueba contra la API** (`docs/pruebas/WEB-API-2026-10-05.md`): PA-332 a PA-336 en la sesión UI; PA-331 y PA-330 (API) en la sesión Modelos; PA-330 (web), PA-337 a PA-339 sin asignar al área B.
- **PA-329** (diseño de Memoria): pendiente de validar por la principal (notas enviadas en el issue #5).
- **Del área B:**
  - PA-300 (UI.md: *Volver a la propuesta* en el recibo, el aviso de modo de prueba solo en simulación, el flujo unido fuera de la entrega y el texto de Cobertura sin «Si no fuera así…»);
  - PA-304 (lienzo: foco, Q con reducir movimiento y la fase de la suite en parte);
  - PA-310, PA-312 y PA-325.
- **Cerradas o aplazadas** por la principal (2026-10-05): PA-311 validada (se mantiene el login mínimo), PA-315 aplazada (fuera de la entrega) y el ejemplo de `jira_baseline` corregido (el apaño del MSW ya está quitado).

## Siguiente
1. **Editar a mano** (`t56-editar`), en dos partes:
   - **A, ya:** solo archivos nuevos (editor, validación, textos, handler del MSW y pruebas);
   - **B, cuando se fusione `ses-web-fixes`:** conectarlo a `IterateScreen` y al cliente (`api.edit`, `EditIn`, `client.contract.ts`), registrar `editHandlers` en `createHandlers` con `runFor`, y «Editada a mano» en el historial del recibo.
   - **Parte A hecha** (archivos nuevos): `src/screens/Edit/` (borrador, validación, hook y editor), `src/mocks/editHandler.ts` y `/?catalogo&editor`. PA-340 (diseño y pregunta de la suite) y PA-341 (formato de los diffs) para la principal.
2. Revisar `ses-web-fixes` cuando la sesión UI lo pida; la parte web de PA-330 cuando llegue la de la API; PA-300.

Antes de cada PR: test-writer, spec-checker (CONFORME) y security-reviewer (APTO), y Vitest, lint, build y `api:check` en verde. No empezar ningún bloque sin la confirmación del responsable.
