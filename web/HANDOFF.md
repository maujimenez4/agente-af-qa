# Traspaso de T-56 (frontend React, área B) · 2026-10-02

**Estado:** T-56 🔄 en la rama `area-b` (subida hasta `3d7e6e8`). 927 pruebas Vitest en verde; lint, build y `npm run api:check` limpios.
**Arrancar:** `cd web && npm ci && npm run dev:mock` (usuarios `af-demo`, `qa-demo` y `admin-demo`; contraseña ficticia `demo`, solo en MSW). Catálogo: `/?catalogo`.
**Leer antes:** `DESIGN-DECISIONS.md` (todas las decisiones), `README.md`, `docs/api/README.md` y las filas PA-300 en adelante del Kanban.

## Hecho
- **Cimientos:** sistema de diseño (tokens, DM Sans, iconos, la Q), tipos generados del contrato y MSW con SSE paso a paso. Cliente con CSRF en memoria y SSE por `fetch`.
- **Pantallas:** login (PA-311), marco (carril con el consumo global y lista de conversaciones), **Inicio**, **Elegir en Jira**, **Origen y fuentes**, **Generando** e **Iterar** (pedir cambios, versiones, pestañas, descartar y retomar desde la lista).
- **Disponible pronto:** admin, «Revisar la calidad», «Preparar pruebas», *Editar a mano* y *Revisar y aprobar*.

## Decisiones de esta sesión que no están en DESIGN-DECISIONS.md
- **Reglas de trabajo:** actualizar siempre con `git merge origin/PreProduccion` (nunca rebase ni `main`). Push solo cuando lo pida la persona. Kanban: solo mis filas y el registro diario; el tablero resumen es de la principal.
- **Flujo de cada pantalla:** commits pequeños `T-56: … [RNF-15]`; parada para revisión visual; al cerrar un bloque, `test-writer` (Vitest), `spec-checker` y `security-reviewer`.
- **Prioridad hasta T-57:** pulir el recorrido completo antes de añadir *Editar a mano*.
- **Verificación en navegador:** sin Playwright. Se usó Edge sin interfaz con CDP (scripts en el scratchpad, fuera del repo).

## PA pendientes de la principal
- **PA-102:** presupuesto de tokens del panel de fuentes.
- **PA-311:** validar el login.
- **PA-314:** cancelar una generación (botón *Detener*).
- **PA-315:** citas por CA y RN («CA sin fuente»).
- **PA-316:** versión «Jira» en Iterar.

Del área B quedan PA-300, PA-301, PA-304, PA-308, PA-310 y PA-312.

## Siguiente
1. **Revisiones pendientes** sobre `b9e8585..HEAD` (Origen, Generando e Iterar): `test-writer`, `spec-checker` y `security-reviewer`. Corregir, añadir la fila al registro diario y hacer push.
2. **Pulido para T-57:**
   - recorrido Inicio → Elegir en Jira → Origen → Generando → Iterar con `af-demo`;
   - teclado, foco y reducir movimiento;
   - tamaños de ventana.
3. **Guion de la demo (T-57):**
   - login;
   - Inicio con recientes;
   - Elegir en Jira (DEMO-3);
   - Origen (fuentes y restricciones);
   - Generando (la Q por pasos);
   - Iterar (pedir un cambio → v3 con «Cambiado en v3», pestañas Cambios e Impacto);
   - descartar o retomar desde la lista.

   Cerrar con: «aprobar y publicar llegan los días 6 a 8».
4. **Días 6 a 8, tras T-57:**
   - recibo de aprobación con la huella exacta (UI.md §5);
   - resultado simulado, real o parcial;
   - Revisar la calidad (Mixta 5);
   - flujo de QA con «Preparar pruebas» (T-54);
   - integración con la API real.
