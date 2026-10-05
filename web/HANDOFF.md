# Traspaso de T-56 (frontend React, área B) · 2026-10-05

**Estado:** T-56 🔄 en `area-b`, con `PreProduccion` fusionada el 2026-10-05. Bloques A y B cerrados, con test-writer, spec-checker y security-reviewer. Lint, test (Vitest), build y `npm run api:check` en verde.
**Arrancar:** `cd web && npm ci && npm run dev:mock` (usuarios `af-demo`, `qa-demo` y `admin-demo`; contraseña ficticia `demo`, solo en MSW). Catálogo: `/?catalogo`.
**Leer antes:** `DESIGN-DECISIONS.md`, `README.md` (incluye `?simular=`), `docs/api/README.md` («Novedades para el frontend») y las filas PA-300 en adelante del Kanban.

## Hecho
- **Recorrido de la HU contra MSW:** login, Inicio, Elegir en Jira, Origen (con el presupuesto de tokens), Generando e Iterar (versión «Jira», *Detener* y *Reintentar*), Recibo con la huella exacta, y Resultado simulado, publicado o en parte.
- **Contrato:** `src/api/client.contract.ts` hace fallar `tsc` si un método del cliente no devuelve exactamente la respuesta de su ruta (cada método nuevo lleva su línea).
- **Seguridad:** `safeHref` y una regla de ESLint que lo exige en todo `href` o `src` dinámico (PA-308).
- **Revisar casos en el navegador:** `?simular=huella|aprobacion-rechazada|no-en-revision|publicado|parcial` (solo `dev:mock`).
- **Disponible pronto:** admin, Revisar la calidad, QA, *Editar a mano*, auditoría, historial, *Abrir en Jira*, *Ver la memoria* y *Pedir sus pruebas a QA*.

## Reglas de trabajo
- `git merge origin/PreProduccion` (nunca rebase ni `main`). **Push al terminar cada paso** en verde: la principal pide subir a diario.
- Commits `T-56: … [RNF-15]`. Parada para revisión visual en cada pantalla; revisiones al cerrar cada bloque. Kanban: solo mis filas y el registro diario. No tocar `app/`.
- Verificación visual: Edge sin interfaz con CDP (scripts fuera del repo). Usa siempre un **perfil nuevo**: uno viejo conserva el Service Worker de MSW y da «Error inesperado».

## API real: cambio de plan
No se monta en este equipo: se probará **en el equipo de la principal**. `API-LOCAL.md` queda como referencia y no se sigue ampliando.

## Aviso: pruebas lentas con el equipo cargado
Con la CPU ocupada por otros procesos, alguna prueba de Origen o Generando puede agotar su tiempo (`testTimeout` de 15 s y `asyncUtilTimeout` de 3 s). Por separado pasan, y una nueva ejecución completa suele salir en verde. Si se repite, revisar esas pruebas antes de subir los tiempos.

## PA abiertas
- **De la principal:**
  - PA-311 (validar el login), PA-315 (citas por CA y RN), **PA-318 (URL de Jira para *Abrir en Jira*)**, PA-319 (el comentario con los cambios como operación del plan) y PA-324 (estado de una publicación parcial);
  - corregir el ejemplo de `jira_baseline`: incluye el CA-02, que sus diffs dan por nuevo.
- **Del área B:** PA-300 (UI.md, con las dos diferencias del recibo), PA-304, PA-310 y PA-312.

## Siguiente
1. **Pulido para T-57:** 1280×800 primero (el carril se corta y hay scroll de página), después 1024 px (el título se corta); teclado, foco y reducir movimiento.
2. **Guion `web/DEMO-T57.md`:** login → Elegir en Jira (DEMO-3) → Origen → Generando (con *Detener*) → Iterar (v3 y versión «Jira») → Recibo → Resultado.
3. **Guía de prueba para la principal** contra la API real: recorrido, qué mirar y fallos probables.
4. **Si da tiempo:** el flujo de QA (*Pedir sus pruebas a QA*, recoger, la suite y su aprobación).
