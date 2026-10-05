# Traspaso de T-56 (frontend React, área B) · 2026-10-05

**Estado:** T-56 🔄 en `area-b`, con `PreProduccion` fusionada el 2026-10-05 (incluida la ronda 8 de la sesión UI en Origen). Flujo de la HU completo y **flujo de QA por roles completo** (QA 1 a QA 5). Lint, Vitest, build y `npm run api:check` en verde.
**PR:** [#4](https://github.com/maujimenez4/agente-af-qa/pull/4) `area-b → PreProduccion` («T-56 (parte 3): flujo de QA»), ya fusionada. Las anteriores también: la #2 (`3b5dd46`) y la #3 («T-56 (parte 2): frontend React, flujo de QA y pulido»). `gh` no está instalado: las PR, los issues y los comentarios se preparan, se copian al portapapeles y se pegan a mano.
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

## Reglas de trabajo
- `git merge origin/PreProduccion` (nunca rebase ni `main`). **Push al terminar cada paso** en verde.
- Commits `T-56: … [RNF-15]`. Parada para revisión visual en cada pantalla; revisiones al cerrar cada bloque. Kanban: solo mis filas y el registro diario. No tocar `app/`.
- Cada PR, issue o comentario se enseña antes y se copia al portapapeles (UTF-8).
- Verificación visual: Edge sin interfaz con CDP (scripts fuera del repo). Usa siempre un **perfil nuevo**: uno viejo conserva el Service Worker de MSW y da «Error inesperado».

## Coordinación con otras sesiones (2026-10-05)
- **Antes de tocar un componente compartido**, avisar a la persona responsable para que avise a la principal: `Composer`, `AppShell`, el panel y la cabecera (`Workspace`), los estados (`States`), la lista de conversaciones, los botones, y las pantallas que comparten la HU y QA (Inicio, Origen, Generando, Iterar, Recibo y Resultado).
- **`client.ts` y `types.ts`** (y el resto de `web/src/api/`) los coordina **la sesión MCP** (rama `ses-web`). No tocarlos sin avisar antes.

## Cuando la principal avise de que está fusionado (PA-326, PA-327 y PA-118)
- **PA-326:**
  - **`ReviewPayload.coverage_md`**: la matriz, igual que `matriz-CLAVE.md`;
  - **`ReviewPayload.uncovered {criteria, rules}`**: `null` significa «no se sabe» y las listas vacías, «todo cubierto». **No se tratan igual**: con `null`, no se afirma «Todos los CA cubiertos» por esta vía; con listas vacías, sí; con elementos, se muestran como no cubiertos.
  - Cambiar la pestaña Cobertura y el distintivo, y la suite sintética del MSW, para usarlos.
- **Ejemplo de QA en revisión:** `components.examples.ConversationQaInReview`. Con **PA-118**, `tools/api-types/generate.mjs` copiará también `components.examples` a `src/api/examples.json`. Entonces el MSW y las pruebas usarán ese ejemplo en lugar de `mockSuiteConversation`.
- **PA-327:** hoy la API manda 5 pasos con las etiquetas de la HU, también en QA. Cuando se fusione, QA tendrá 4 pasos (sin «Guardar la memoria») con sus etiquetas. El frontend ya pinta los que lleguen, tal cual, y la Q funciona con 4 o 5: solo queda comprobar los textos con la API real.

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
- **De la principal:**
  - PA-311 (validar el login), PA-315 (citas por CA y RN);
  - **PA-326** (ejemplo de revisión de QA, `coverage_md` y `uncovered`);
  - **PA-327** (etiquetas de los pasos por modo);
  - PA-118 (copiar `components.examples` a `examples.json`).
  - Corregir el ejemplo de `jira_baseline`: incluye el CA-02, que sus diffs dan por nuevo.
- **Del área B:** PA-300 (UI.md: *Volver a la propuesta* en el recibo, el aviso de modo de prueba solo en simulación y el flujo unido fuera de la entrega), PA-304 (lienzo: foco, Q con reducir movimiento y la fase de la suite en parte), PA-310, PA-312 y PA-325.

## Siguiente
Cerrar el flujo de QA (revisiones, PR «T-56: flujo de QA por roles, recibo y resultado de la suite») y **esperar la confirmación del responsable antes de empezar Memoria**.
