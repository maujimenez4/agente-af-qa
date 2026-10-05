# Traspaso de T-56 (frontend React, área B) · 2026-10-05

**Estado:** T-56 🔄 en `area-b`, con `PreProduccion` fusionada el 2026-10-05 (incluida la ronda 8 de la sesión UI en Origen). Flujo de la HU completo; flujo de QA hasta QA 3 · Iterar la suite. Lint, Vitest, build y `npm run api:check` en verde.
**PR:** [#4](https://github.com/maujimenez4/agente-af-qa/pull/4) `area-b → PreProduccion` («T-56 (parte 3): flujo de QA»), abierta el 2026-10-05. Las anteriores ya están fusionadas: la #2 (`3b5dd46`) y la #3 («T-56 (parte 2): frontend React, flujo de QA y pulido»). `gh` no está instalado: los comentarios se preparan, se copian al portapapeles y se pegan a mano.
**Arrancar:** `cd web && npm ci && npm run dev:mock` (usuarios `af-demo`, `qa-demo` y `admin-demo`; contraseña ficticia `demo`, solo en MSW). Catálogo: `/?catalogo`.
**Leer antes:** `DESIGN-DECISIONS.md`, `README.md` (incluye `?simular=`), `docs/api/README.md` («Novedades para el frontend») y las filas PA-300 en adelante del Kanban.

## T-57: punto de control
**Propuesta, pendiente del punto de control.** La decisión entre React y Streamlit la toma el responsable cuando el flujo de QA funcione contra la API real. Mientras, se sigue con React y Streamlit (`app/`) se mantiene como plan B. El guion de la demo se escribirá al final.

## Hecho
- **Flujo de la HU contra MSW:** login, Inicio, Elegir en Jira, Origen (presupuesto de tokens y conversación de la ronda 8), Generando e Iterar (versión «Jira», *Detener* y *Reintentar*), Recibo con la huella exacta y Resultado simulado, publicado o en parte; *Abrir <clave> en Jira* (PA-318).
- **Flujo de QA** (`DESIGN-DECISIONS.md` §4 bis):
  - bloque 1: *Pedir sus pruebas a QA* en el Resultado y «Pendientes de pruebas» en Inicio con *Recoger*;
  - QA 1 · Origen (tipos de caso, «Incluir además» plegado);
  - QA 2 · Generando;
  - QA 3 · Iterar la suite (Casos, Cobertura, Datos y riesgos, Estrategia).
- **Suite sintética del MSW** (`src/mocks/qaSuite.ts`) mientras el contrato no traiga una revisión de QA (PA-326) ni las etiquetas de los pasos por modo (PA-327).
- **Compositor:** Intro envía, Mayús+Intro hace un salto de línea.
- **Contrato:** `src/api/client.contract.ts` hace fallar `tsc` si un método del cliente no devuelve exactamente la respuesta de su ruta.
- **Seguridad:** `safeHref` y su regla de ESLint (PA-308).
- **Tamaños:** 1024×768, 1280×800 y 1440×900 sin scroll de página ni títulos cortados; lista de conversaciones larga con scroll interno.
- **Pruebas:** no dependen del reloj (SSE de prueba abierto, sondeo disparado por la prueba) y Vitest usa la mitad de los núcleos.
- **Disponible pronto:** admin, Revisar la calidad, *Editar a mano*, auditoría, historial, *Ver la memoria* y QA 6 (registrar la ejecución).

## API real
La prueba la hace **la principal en su equipo** con [PRUEBA-API-REAL.md](PRUEBA-API-REAL.md), la guía única (`API-LOCAL.md` solo enlaza a ella). En este equipo no se monta el backend. Los fallos llegan como comentarios en la PR #4.

## Reglas de trabajo
- `git merge origin/PreProduccion` (nunca rebase ni `main`). **Push al terminar cada paso** en verde.
- Commits `T-56: … [RNF-15]`. Parada para revisión visual en cada pantalla; revisiones al cerrar cada bloque. Kanban: solo mis filas y el registro diario. No tocar `app/`.
- Cada comentario para la PR se enseña antes y se copia al portapapeles (UTF-8).
- Verificación visual: Edge sin interfaz con CDP (scripts fuera del repo). Usa siempre un **perfil nuevo**: uno viejo conserva el Service Worker de MSW y da «Error inesperado».

## Coordinación con otras sesiones (2026-10-05)
- **Antes de tocar un componente compartido**, avisar a la persona responsable para que avise a la principal: `Composer`, `AppShell`, el panel y la cabecera (`Workspace`), los estados (`States`), la lista de conversaciones, los botones, y las pantallas que comparten la HU y QA (Origen, Generando, Iterar, Recibo y Resultado).
- **La sesión MCP trabaja en `web/src/api/**`** (rama `ses-web`). No tocar `client.ts`, `types.ts` ni el resto de `web/src/api/` sin avisar antes.

## PA abiertas
- **De la principal:**
  - PA-311 (validar el login), PA-315 (citas por CA y RN);
  - **PA-326** (ejemplo de revisión de QA, matriz de cobertura y la lista de CA y RN de la HU);
  - **PA-327** (etiquetas de los pasos por modo).
  - Corregir el ejemplo de `jira_baseline`: incluye el CA-02, que sus diffs dan por nuevo.
- **Del área B:** PA-300 (UI.md: *Volver a la propuesta* en el recibo, el aviso de modo de prueba solo en simulación y *Pedir sus pruebas a QA* también tras una aprobación simulada), PA-304, PA-310, PA-312 y PA-325.

## Siguiente
**Bloque 5 · QA 4 Recibo y QA 5 Resultado** (esperar la confirmación del responsable antes de empezar). Archivos previstos:
- `screens/Receipt/` y `screens/Result/`: compartidos con la HU;
- quizá `app/AppShell.tsx`, para pasar a QA el rol del Resultado;
- `src/mocks/handlers.ts` y `src/mocks/qaSuite.ts`: aprobar una suite, con resultado simulado, publicado o en parte en `approved`.

En `web/src/api/` no hace falta nada: *Aprobar* ya existe en el cliente.
