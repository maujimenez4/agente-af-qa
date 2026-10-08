# SESIÓN UI · Ronda 12: lo que encontró la auditoría en la web (PA-461, PA-460, PA-459 y arreglos pequeños)

> Encargo de la **sesión UI**. Tu ronda 11 (logo, PA-444) ya está fusionada. El responsable de `web/` entregó T-56 y no está tocando `web/`: esta ronda es tuya. Sale de la auditoría completa del 2026-10-08 (`docs/auditorias/AUDITORIA-2026-10-08.md`). Hay otras tres sesiones trabajando a la vez en el backend.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```powershell
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/ses-ui switch -C ses-auditoria-web origin/PreProduccion
cd .claude/worktrees/ses-ui/web
npm ci
npm test
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-auditoria-web`**, creada desde `PreProduccion`. Tu ronda 11 ya está fusionada.

**Contexto:** lee el informe de la auditoría (sección «Frontend») y las filas **PA-459, PA-460 y PA-461** de `docs/KANBAN.md`. Lee también `web/HANDOFF.md`, `web/DESIGN-DECISIONS.md` y `docs/specs/UI.md`.

## Tareas, por prioridad (propón el plan antes de escribir código)
1. **PA-461 · Tras un 403 por CSRF, la web se recupera.** Si se inicia sesión en otra pestaña, la primera se queda con el token antiguo y cada acción da «Sin permiso» sin salida (`web/src/api/client.ts:89`, `:107-111`; `web/src/session/SessionProvider.tsx:12-23`). Ante un 403 en un método que modifica, pide `/auth/me` **una vez**:
   - si es el mismo usuario, actualiza el token y reintenta **solo** si la acción es segura de repetir;
   - si no, avisa y vuelve al login.

   No hagas bucles de reintento.
2. **PA-460 · «Elegir en Jira» con estados de carga.** Distingue «cargando» de «vacío» en cada lista (proyectos, épicas, HU y búsqueda) y lleva **un error por cada carga** (`web/src/screens/ChooseInJira/ChooseInJira.tsx`). Hoy, mientras Jira responde, sale «Este proyecto no tiene épicas.».
3. **PA-459 · La consulta de uso no mantiene viva la sesión.** `useUsage` (`web/src/hooks/useUsage.ts:28-29`) pide `/settings/usage` cada 60 s y renueva la sesión: la caducidad por inactividad no llega nunca. Páusala con la pestaña oculta (`visibilitychange`) y cuando no haya actividad del usuario durante, por ejemplo, 5 minutos. Solo web: el backend no se toca.
4. **Arreglos pequeños** (todos bajos, en este orden; si no da tiempo, quedan como propuestas):
   - `maxLength` en los buscadores según el contrato: 200 en «Elegir en Jira» y 100 en Memoria;
   - «Volver al inicio» en la vista de error de Calidad con `not_found` o `forbidden` (`QualityScreen.tsx:139-149`);
   - «Reintentar» de las fuentes en Origen vuelve a pedirlas (`sourcesReload`), con estado de carga mientras llegan (`OriginScreen.tsx:122-123`, `:344-346`, `:449`);
   - `openError` se borra con «Nueva conversación», y su «Reintentar» vuelve a abrir la conversación (`AppShell.tsx:165-169`, `:187`);
   - `openConversation` descarta respuestas que no son de la última conversación pedida (`AppShell.tsx:128-135`).

## Reglas
- **Solo `web/` y su documentación.** No toques `web/src/api/types.ts` ni el esquema generado, `api/`, `core/` ni `app/`, ni añadas dependencias.
- **Componentes compartidos que toques:** dilo en tu mensaje final con la lista exacta.
- **Pruebas** (Vitest con MSW, deterministas, sin ampliar esperas): una por criterio, positivas y negativas. Incluye:
  - el 403 que se recupera y el que vuelve al login;
  - la carga frente al vacío y los errores independientes;
  - la pausa de la consulta de uso con la pestaña oculta;
  - y cada arreglo pequeño que hagas.
- **Verificación:**
  - `npm run lint`, `npx tsc -b`, `npm test` (dos veces), `npm run build` y `npm run api:check`;
  - Edge sin interfaz con un perfil nuevo para «Elegir en Jira» y Origen, en otro puerto.
  - La web del usuario (5173) y la API (8000) están en uso: no las toques.
- **No mates procesos.** Pídeselo también a los subagentes.
- **Kanban:**
  - cierra las PA hechas con la fecha;
  - tu fila en el registro;
  - propuestas nuevas en **PA-471…PA-473**.
- **Antes del commit:** `spec-checker` CONFORME y `security-reviewer` APTO.
- **Sin fusionar.** Haz `git push -u origin ses-auditoria-web` y avísame.

Empieza presentándome el plan antes de escribir código.
