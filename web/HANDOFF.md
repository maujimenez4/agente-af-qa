# Traspaso de T-56 (frontend React, área B) · 2026-10-06

**Estado:** T-56 🔄. En `PreProduccion`: el flujo de la HU, el de QA (QA 1 a QA 5), Cobertura (PA-326), Memoria, los dos nombres de los diffs (PA-341, #7), Administración y Revisar la calidad (sesión MCP). Pendientes de fusionar: `ses-web-fixes` (PA-332 a PA-336), Editar a mano (`t56-editar`, parte A; la B espera a `ses-web-fixes`), UI.md v2.0 (#8) y PA-325/PA-312 (#9).
**PR abiertas:** [#8](https://github.com/maujimenez4/agente-af-qa/pull/8) `t56-uimd → PreProduccion` (UI.md v2.0, PA-300) y [#9](https://github.com/maujimenez4/agente-af-qa/pull/9) `t56-pa325 → PreProduccion` (claves de Jira enlazadas, PA-325, y regla de ESLint del almacenamiento, PA-312). Fusionadas: la #2, la #3, la #4, la #6 y la #7.
**Issue de seguimiento:** [#5](https://github.com/maujimenez4/agente-af-qa/issues/5) («T-56 · Frontend React: seguimiento»). `gh` no está instalado: las PR, los issues y los comentarios se preparan, se copian al portapapeles y se pegan a mano.
**Arrancar:** `cd web && npm ci && npm run dev:mock` (usuarios `af-demo`, `qa-demo` y `admin-demo`; contraseña ficticia `demo`, solo en MSW). Catálogo: `/?catalogo`.
**Leer antes:** `DESIGN-DECISIONS.md`, `README.md` (incluye `?simular=`), `docs/api/README.md` («Novedades para el frontend») y las filas PA-300 en adelante del Kanban.

## Novedades de la principal (2026-10-06)
- **PA-331 hecha en la API:** iterar una suite aplica el cambio pedido y conserva los IDs de los casos que no cambian.
- **PA-330:** la parte de la API está en `PreProduccion` (`SourcePreview.tokens`, `budget.fixed` y `budget.total`; tipos regenerados en `c397c8a`). **La parte web es nuestra** y depende del `signal` de `api.sources` que trae `ses-web-fixes` (PA-336). El número que pinte la web es una **estimación**: al excluir un documento, el RAG rellena su hueco con otro, así que manda la confirmación del servidor (`POST /start/sources`).
- **Guion de la demo:** con `qwen3:1.7b` las RN saldrán **sin caso** (el modelo no rellena `rule_ids`, PA-122). UI.md §6.3 (`t56-uimd`) ya dice que una RN sin caso se avisa en Cobertura pero no bloquea la aprobación.

## Estado de las ramas (2026-10-06)
- **PR #8** (`t56-uimd`, UI.md v2.0) y **PR #9** (`t56-pa325`, PA-325 y PA-312) abiertas. La #9 ya trae `origin/PreProduccion` (conflicto del registro diario resuelto conservando las dos filas).
- **`ses-web-fixes`** (PA-333, PA-336, PA-332, PA-334, PA-407) revisada y comentada en el issue #5: antes de fusionarla hay que arreglar dos fallos (*Generar* aborta la lista de fuentes y Origen se queda sin ellas; un 401 que llega tarde tras volver a entrar).
- **PR #10** (`t56-sondeo`, PA-406: tope del sondeo de Revisar la calidad) abierta.

## T-57: punto de control
**Propuesta, pendiente del punto de control.** La decisión entre React y Streamlit la toma el responsable cuando el flujo de QA funcione contra la API real. Mientras, se sigue con React y Streamlit (`app/`) se mantiene como plan B. El guion de la demo se escribirá al final.

## Pulido final
- **UI.md v2.0** (`docs/specs/UI.md`, PA-300, 2026-10-06) describe la web en React tal como está fusionada (ya con Revisar la calidad y PA-341). Hay que **actualizarla** cuando se fusionen:
  - **`ses-web-fixes`** (PA-332 a PA-336): 401 común (§7), «Aprobando y publicando…», Estrategia con formato (§6.3), alto de la app y `/start/sources` durante la generación;
  - **Editar a mano**: la parte A (`t56-editar`), la parte B y la **validación de PA-340**: §4.5 bis deja de ser «pendiente de validar» (y la pregunta de la suite de QA), y `/edit` en §9;
  - **PA-330** (presupuesto rápido en Origen, §4.3).
- Con la v2.0, alinear también las frases que aún dicen que algo «no está en UI.md» o citan la v1.0: `web/DESIGN-DECISIONS.md` (aviso de modo de prueba del Resultado, «Si no fuera así…» de Cobertura y Memoria) y el comentario de `web/src/screens/Memory/memoryText.ts`.
- Otros textos desfasados por lo ya fusionado: el comentario de `itemId` en `web/src/components/Proposal/proposalText.ts` (el ejemplo del contrato ya usa `acceptance_criteria[CA-02]`) y `web/PRUEBA-API-REAL.md`, que aún da Revisar la calidad y Administración como «disponible pronto».
- **Administración** (Ajustes, solo admin) está completa en `PreProduccion` y es ahora del responsable de `web/`: revisarla en el pulido final (textos, tamaños y las PA abiertas).

## Reparto (2026-10-06)
- **Del responsable de `web/`:** Administración (completa en `PreProduccion`; se revisa en el pulido final), Editar a mano (`t56-editar`), la parte web de PA-330, revisar `ses-web-fixes` antes de fusionarla, el pulido de UI.md y **PA-400** (copiar el archivo del lienzo de Ajustes), **PA-404** (diferencias de Mixta 5 con el lienzo, ya en UI.md §4.8) y **PA-406** (tope del sondeo de Revisar la calidad, en `t56-sondeo`).
- **PA-402 a PA-406** vienen de la sesión MCP (Revisar la calidad); de ellas, PA-402 y PA-405 son de la API (principal) y PA-403 sigue pendiente de decidir.
- **Sesión UI** (`ses-web-fixes`): PA-332 a PA-336, aún sin fusionar.

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
- **Disponible pronto:** *Editar a mano*, auditoría, historial, *Ver la memoria*, *Registrar la ejecución* (QA 6) y *Pedir sus pruebas a QA*.

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
- **Responder siempre en español** (también los resúmenes, los informes y lo que se prepara para GitHub).
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
2. ~~**Revisar la calidad.**~~ (hecho en `ses-web-admin`)
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
  - PA-304 (lienzo: foco, Q con reducir movimiento y la fase de la suite en parte);
  - PA-310, PA-312 y PA-325.
- **Cerradas o aplazadas** por la principal (2026-10-05): PA-311 validada (se mantiene el login mínimo), PA-315 aplazada (fuera de la entrega) y el ejemplo de `jira_baseline` corregido (el apaño del MSW ya está quitado).

## Siguiente
**Tras PA-406 (`t56-sondeo`), el siguiente bloque es PA-335 ampliada:** el panel derecho se corta (con barra horizontal en el área de trabajo) cuando quedan menos de 1024 px útiles: 1024 al 125 %, y 1280 y 1440 al 150 %. Hay que corregir el diseño para que funcione con el escalado habitual de Windows. Medido el 2026-10-06 en Iterar (QA) con la API simulada; el hueco en blanco original no se reprodujo.

1. **Cuando se fusione la #6:** traer `origin/PreProduccion` a `t56-qa-cobertura` y abrir su PR con la descripción preparada (se enseña y se copia al portapapeles). Después, lo mismo con `t56-memoria` (su PR, cuando se fusione la de `t56-qa-cobertura`).
2. Después, por este orden: **Revisar la calidad**, **Administración mínima** y **Editar a mano** (detalle en «Alcance y orden tras el bloque 5»), cada bloque en su propia rama mientras haya PR abiertas.

Antes de cada PR: test-writer, spec-checker (CONFORME) y security-reviewer (APTO), y Vitest, lint, build y `api:check` en verde. Esperar la confirmación del responsable antes de empezar Memoria.
