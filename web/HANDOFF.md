# Traspaso de T-56 (frontend React, área B) · 2026-10-05

**Estado:** T-56 🔄. Flujo de la HU completo y **flujo de QA por roles completo** (QA 1 a QA 5), en la PR #6. **Bloque «contrato de QA en la web» cerrado** en `t56-qa-cobertura` (PA-326 en Cobertura, PA-118, fuera `mockBaseline` y PA-328), con su PR preparada **sin abrir** hasta que se fusione la #6. **Bloque Memoria cerrado** en `t56-memoria` (desde `t56-qa-cobertura`). Lint, Vitest (1.846), build y `npm run api:check` en verde.
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
- **Disponible pronto:** Revisar la calidad, *Editar a mano*, auditoría, historial, *Ver la memoria*, *Registrar la ejecución* (QA 6) y *Pedir sus pruebas a QA*.

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

## Cadena de ramas (mientras la PR #6 siga abierta)
`area-b` (PR #6 → `PreProduccion`) → `t56-qa-cobertura` (contrato de QA, PR preparada) → `t56-memoria` (Memoria, cerrado; su PR se prepara cuando se fusione la de `t56-qa-cobertura`). Cada rama sale de la anterior y solo se hace push de la rama en curso.
- **Al fusionarse una PR:** traer `origin/PreProduccion` a la siguiente rama de la cadena (`git merge`, nunca rebase), comprobar Vitest, lint, build y `api:check`, y preparar su PR (`<rama> → PreProduccion`).
- **Si hay correcciones en una rama anterior** (p. ej. fallos de la #6 que pide la principal, que se corrigen en `area-b`): hacerlas allí y traerlas a las siguientes con `git merge`, por orden (`area-b` → `t56-qa-cobertura` → `t56-memoria`).

## Reglas de trabajo
- `git merge origin/PreProduccion` (nunca rebase ni `main`). **Push al terminar cada paso** en verde.
- Commits `T-56: … [RNF-15]`. Parada para revisión visual en cada pantalla; revisiones al cerrar cada bloque. Kanban: solo mis filas y el registro diario. No tocar `app/`.
- Cada PR, issue o comentario se enseña antes y se copia al portapapeles (UTF-8).
- Verificación visual: Edge sin interfaz con CDP (scripts fuera del repo). Usa siempre un **perfil nuevo**: uno viejo conserva el Service Worker de MSW y da «Error inesperado».

## Coordinación con otras sesiones (2026-10-05)
- **Antes de tocar un componente compartido**, avisar a la persona responsable para que avise a la principal: `Composer`, `AppShell`, el panel y la cabecera (`Workspace`), los estados (`States`), la lista de conversaciones, los botones, y las pantallas que comparten la HU y QA (Inicio, Origen, Generando, Iterar, Recibo y Resultado).
- **`client.ts` y `types.ts`** (y el resto de `web/src/api/`) los coordina **la sesión MCP** (rama `ses-web`). No tocarlos sin avisar antes.

## Bloque «contrato de QA en la web» (hecho, rama `t56-qa-cobertura`)
- **PA-326 en Cobertura:** `uncovered` con `null` (o sin el campo) = «no se sabe»: sin distintivo, sin «Todos los CA cubiertos» y sin «cobertura validada». Listas vacías = «Todos los CA cubiertos». Con elementos = «1 CA y 1 RN sin caso», el aviso «Sin ningún caso: …» y filas «· Sin caso». Solo para la versión en revisión. Detalle en `DESIGN-DECISIONS.md` (QA 3).
- **`coverage_md`:** botón *Descargar la matriz* (`matriz-<CLAVE>.md`); con `null`, no aparece. **Pieza reutilizable para Memoria:** `DownloadButton` (`src/components/Download/`) sobre `downloadText` (`src/security/download.ts`, nombres solo ASCII). ESLint prohíbe `createObjectURL` y asignar `href` fuera de ese archivo.
- **PA-118:** `generate.mjs` copia `components.examples` a `examples.json` (`components.examples.<Nombre>`). El MSW usa `ConversationQaInReview` y los 4 pasos de QA; `qaSuite.ts` solo simula otra clave, iterar y publicar.
- **`mockBaseline` fuera:** la versión «Jira» es la del ejemplo (CA-01, sin CA-02).
- **PA-328:** recuentos con `countLabel` (`src/text/plural.ts`), también «1 fuente» en el modo HU de Iterar (cambio menor, en la descripción de la PR).
- `?simular=sin-cubrir` y `?simular=cobertura-desconocida` en `web/README.md`.
- **Issue #5:** avisado el cambio de `examples.json`.
- **PR preparada** en el scratchpad de la sesión (`pr-descripcion-cobertura.md`): `t56-qa-cobertura → PreProduccion`. Se abre cuando se fusione la #6: antes, `git merge origin/PreProduccion` en `t56-qa-cobertura`, Vitest, lint, build y `api:check`.

## Bloque Memoria (hecho, rama `t56-memoria`)
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
2. **Revisar la calidad.**
3. ~~**Administración mínima**~~ (hecho en `ses-web-admin`), solo para admin:
   - probar conexiones con `POST /admin/connections/test`: una cada 10 s, con 429 y `retry_after`, y con CSRF;
   - modelos por tarea en solo lectura (`GET /admin/models`);
   - `publish_mode` de `GET /settings` en solo lectura, con el aviso «Simulación: no se escribe nada en Jira»;
   - usuarios, documentos e historial como «disponible pronto»;
   - diseño de la parte de Ajustes de «Propuesta v2» del lienzo, adaptada al estilo de la «Propuesta mixta».
4. **Editar a mano.**

**Fuera de la entrega:** el flujo unido HU → QA, QA 6 (registrar la ejecución) y el selector de modelo funcional.

## PA abiertas
- **Adoptadas en `t56-qa-cobertura`:** PA-326, PA-327 (en la API simulada), PA-118 y PA-328.
- **Del área B:**
  - PA-300 (UI.md: *Volver a la propuesta* en el recibo, el aviso de modo de prueba solo en simulación, el flujo unido fuera de la entrega y el texto de Cobertura sin «Si no fuera así…»);
  - PA-304 (lienzo: foco, Q con reducir movimiento y la fase de la suite en parte);
  - PA-310, PA-312 y PA-325.
- **Cerradas o aplazadas** por la principal (2026-10-05): PA-311 validada (se mantiene el login mínimo), PA-315 aplazada (fuera de la entrega) y el ejemplo de `jira_baseline` corregido (el apaño del MSW ya está quitado).

## Siguiente
1. **Cuando se fusione la #6:** traer `origin/PreProduccion` a `t56-qa-cobertura` y abrir su PR con la descripción preparada (se enseña y se copia al portapapeles). Después, lo mismo con `t56-memoria` (su PR, cuando se fusione la de `t56-qa-cobertura`).
2. Después, por este orden: **Revisar la calidad**, **Administración mínima** y **Editar a mano** (detalle en «Alcance y orden tras el bloque 5»), cada bloque en su propia rama mientras haya PR abiertas.

Antes de cada PR: test-writer, spec-checker (CONFORME) y security-reviewer (APTO), y Vitest, lint, build y `api:check` en verde. Esperar la confirmación del responsable antes de empezar Memoria.
