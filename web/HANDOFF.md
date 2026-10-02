# Traspaso de T-56 (frontend React, área B) · 2026-10-02

**Estado:** T-56 🔄 en la rama `area-b`, con `PreProduccion` fusionada. 1002 pruebas Vitest en verde; lint, build y `npm run api:check` limpios. Origen, Generando e Iterar revisados (test-writer, spec-checker y security-reviewer).
**Arrancar:** `cd web && npm ci && npm run dev:mock` (usuarios `af-demo`, `qa-demo` y `admin-demo`; contraseña ficticia `demo`, solo en MSW). Catálogo: `/?catalogo`.
**Leer antes:** `DESIGN-DECISIONS.md` (todas las decisiones), `README.md`, `docs/api/README.md` y las filas PA-300 en adelante del Kanban.

## Hecho
- **Cimientos:** sistema de diseño (tokens, DM Sans, iconos, la Q), tipos generados del contrato y MSW con SSE paso a paso. Cliente con CSRF en memoria y SSE por `fetch`.
- **Pantallas:** login (PA-311), marco (carril con el consumo global y lista de conversaciones), **Inicio**, **Elegir en Jira**, **Origen y fuentes**, **Generando** e **Iterar** (pedir cambios, versiones, pestañas, descartar y retomar desde la lista).
- **Disponible pronto:** admin, «Revisar la calidad», «Preparar pruebas», *Editar a mano* (aplazado a los días 6 a 8) y *Revisar y aprobar*.
- **Corregido el 2026-10-02:** botón «Ocultar el panel» en la cabecera de la conversación; título «HU nueva en la épica DEMO-1» (PA-317); marcas «Cambiado en vN» contra la versión anterior (`impact.diffs` acumula frente a Jira).

## Decisiones de esta sesión que no están en DESIGN-DECISIONS.md
- **Reglas de trabajo:** actualizar siempre con `git merge origin/PreProduccion` (nunca rebase ni `main`). Push solo cuando lo pida la persona. Kanban: solo mis filas y el registro diario; el tablero resumen es de la principal.
- **Flujo de cada pantalla:** commits pequeños `T-56: … [RNF-15]`; parada para revisión visual; al cerrar un bloque, `test-writer` (Vitest), `spec-checker` y `security-reviewer`.
- **Prioridad hasta T-57:** pulir el recorrido completo antes de añadir *Editar a mano*.
- **Verificación en navegador:** sin Playwright. Se usó Edge sin interfaz con CDP (scripts en el scratchpad, fuera del repo).

## PA pendientes de la principal
PA-102 (presupuesto de tokens), PA-311 (validar el login), PA-314 (cancelar una generación), PA-315 (citas por CA y RN), PA-316 (versión «Jira» en Iterar) y PA-317 (título de la HU nueva en una épica, en `core/conversations.py`). Del área B quedan PA-300, 301, 304, 308, 310 y 312.

## Siguiente
1. **Revisiones hechas** (2026-10-02) sobre Origen, Generando e Iterar; rama subida. Esperar la respuesta de la principal en la PR (PA-311, 314 a 317).
2. **Pulido para T-57:** el recorrido completo con `af-demo`, teclado, foco, reducir movimiento y tamaños de ventana.
3. **Guion de la demo (T-57):** login → Inicio con recientes → Elegir en Jira (DEMO-3) → Origen (fuentes y restricciones) → Generando (la Q por pasos) → Iterar (un cambio → v3 con «Cambiado en v3», pestañas Cambios e Impacto) → descartar o retomar desde la lista. Cerrar con «aprobar y publicar llegan los días 6 a 8».
4. **Días 6 a 8, tras T-57:**
   - recibo de aprobación con la huella exacta (UI.md §5);
   - resultado simulado, real o parcial;
   - Revisar la calidad (Mixta 5);
   - flujo de QA con «Preparar pruebas» (T-54);
   - integración con la API real.
