# Traspaso de T-56 (frontend React, área B) · 2026-10-05

**Estado:** T-56 🔄 en `area-b`, con `PreProduccion` fusionada el 2026-10-05. Bloques A y B cerrados, con test-writer, spec-checker y security-reviewer. Tamaños de ventana pulidos. Lint, test (Vitest), build y `npm run api:check` en verde.
**PR:** [#3](https://github.com/maujimenez4/agente-af-qa/pull/3) `area-b → PreProduccion` («T-56 (parte 2): frontend React, flujo de QA y pulido»), abierta el 2026-10-05. La #2 se cerró al fusionar la principal `area-b` (`3b5dd46`). `gh` no está instalado: los comentarios se preparan y se pegan a mano.
**Arrancar:** `cd web && npm ci && npm run dev:mock` (usuarios `af-demo`, `qa-demo` y `admin-demo`; contraseña ficticia `demo`, solo en MSW). Catálogo: `/?catalogo`.
**Leer antes:** `DESIGN-DECISIONS.md`, `README.md` (incluye `?simular=`), `docs/api/README.md` («Novedades para el frontend») y las filas PA-300 en adelante del Kanban.

## Decisión de T-57 (2026-10-05)
**React es la entrega final**; Streamlit (`app/`) deja de ser el plan B para la demo. El guion `DEMO-T57.md` ya no se hace: al terminar todo se escribirá un guion de la demo final.

## Hecho
- **Recorrido de la HU contra MSW:** login, Inicio, Elegir en Jira, Origen (con el presupuesto de tokens), Generando e Iterar (versión «Jira», *Detener* y *Reintentar*), Recibo con la huella exacta, y Resultado simulado, publicado o en parte.
- **Contrato:** `src/api/client.contract.ts` hace fallar `tsc` si un método del cliente no devuelve exactamente la respuesta de su ruta (cada método nuevo lleva su línea).
- **Seguridad:** `safeHref` y una regla de ESLint que lo exige en todo `href` o `src` dinámico (PA-308).
- **Tamaños:** 1024×768, 1280×800 y 1440×900 sin scroll de página, sin el carril cortado y sin títulos cortados (`DESIGN-DECISIONS.md` §2).
- **Revisar casos en el navegador:** `?simular=huella|aprobacion-rechazada|no-en-revision|publicado|parcial` (solo `dev:mock`).
- **Disponible pronto:** admin, Revisar la calidad, QA, *Editar a mano*, auditoría, historial, *Ver la memoria* y *Pedir sus pruebas a QA*.

## API real
La prueba la hace **la principal en su equipo**, entre el 2026-10-05 y el 2026-10-06, con [PRUEBA-API-REAL.md](PRUEBA-API-REAL.md), la guía única: `API-LOCAL.md` solo enlaza a ella. En este equipo no se monta el backend. Los fallos llegan como comentarios en la PR #3.

## Reglas de trabajo
- `git merge origin/PreProduccion` (nunca rebase ni `main`). **Push al terminar cada paso** en verde: la principal pide subir a diario.
- Commits `T-56: … [RNF-15]`. Parada para revisión visual en cada pantalla; revisiones al cerrar cada bloque. Kanban: solo mis filas y el registro diario. No tocar `app/`.
- Verificación visual: Edge sin interfaz con CDP (scripts fuera del repo). Usa siempre un **perfil nuevo**: uno viejo conserva el Service Worker de MSW y da «Error inesperado».

## Aviso: pruebas lentas con el equipo cargado
Con la CPU ocupada, alguna prueba de Origen o Generando puede agotar su tiempo. Las de «Retomar en error · Reintentar» (`AppShell.blockA.test.tsx` y `AppShell.fixes.test.tsx`) fallan a veces en el equipo de la principal: dependen de que «Generando la propuesta…» siga en pantalla. Se corrigen en el paso 2 del orden de abajo, sin subir tiempos.

## PA abiertas
- **De la principal:**
  - PA-311 (validar el login) y PA-315 (citas por CA y RN);
  - corregir el ejemplo de `jira_baseline`: incluye el CA-02, que sus diffs dan por nuevo.
- **Del área B:** PA-300 (UI.md, con dos diferencias: *Volver a la propuesta* en el recibo y el aviso de modo de prueba solo en simulación), PA-304, PA-310, PA-312 y PA-325 (enlazar también las claves publicadas y las de Impacto).

## Siguiente (orden acordado el 2026-10-05)
1. Fusionar `origin/PreProduccion`, `npm run api:types` y `npm run api:check`.
2. **Pruebas inestables** de «Retomar en error · Reintentar»: que la simulación no termine hasta que la prueba lo decida (SSE controlado en MSW o temporizadores falsos). Ejecutar la suite completa varias veces seguidas.
3. **PA-318** (*Abrir <clave> en Jira* con `SettingsOut.jira_browse_url`, siempre por `safeHref`; si es `null`, sigue «disponible pronto»), **PA-319** (el comentario con los cambios sale del plan: `{"op": "comment"}`; se quita la deducción) y **PA-324** (suite parcial → `approved`, HU con un vínculo fallido → `published`, en los dos casos con `result.errors`). MSW, pruebas y Kanban.
4. Comentario para la PR con lo hecho.
5. **Flujo de QA** (handoff, recoger, la suite y su aprobación): presentar el plan y esperar la confirmación.
