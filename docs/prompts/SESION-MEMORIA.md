# SESIÓN UI · Ronda 9: arreglos de la web tras la prueba con la API real (PA-333, PA-336, PA-332, PA-334 y PA-335)

> Encargo de la **sesión UI**. Tu ronda 8 (conversación en Origen) ya está fusionada. El responsable de `web/` está ausente: el usuario ha decidido terminar los pendientes con sesiones. En paralelo, la sesión MCP hace la pantalla de Administración (rama `ses-web-admin`).

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/ses-ui switch -C ses-web-fixes origin/PreProduccion
cd .claude/worktrees/ses-ui/web
npm ci
npm test
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-web-fixes`**, creada desde `PreProduccion`. Tu ronda 8 ya está fusionada.

**Contexto:** la prueba de la web contra la API real (`docs/pruebas/WEB-API-2026-10-05.md`) dejó fallos de la web en las filas **PA-332 a PA-336** de `docs/KANBAN.md`. Léelas, junto con `web/README.md`, `web/DESIGN-DECISIONS.md` y `web/HANDOFF.md`.

## Tareas, por prioridad para la demo
1. **PA-333 (alta, intermitente):** una vez, tras «Aprobar y publicar», la pantalla se quedó en «Aprobando y publicando…» sin abrir el SSE ni consultar el estado, aunque la conversación quedó `simulated`.
   - Busca la carrera en `Publishing` / `useGeneration`, por ejemplo cuando la respuesta de `POST /approve` ya no está `generating`, o cuando el `result` llega antes de abrir el SSE.
   - Que la pantalla consulte siempre el estado si no recibe eventos en unos segundos.
   - Cúbrelo con una prueba que reproduzca la carrera de forma determinista.
2. **PA-336 (media-alta):** `POST /start/sources` se sigue llamando durante la generación y compite por los embeddings: la cancelación tardó 26 s. Deja de pedir fuentes al pasar a Generando y aborta la petición en curso.
3. **PA-332:** tratamiento global del 401. La tarjeta «Sesión caducada» debe llevar al inicio de sesión desde cualquier pantalla (el cliente avisa y `SessionProvider` pasa a anónimo), no solo desde Iterar.
4. **PA-334:** la pestaña Estrategia (QA) muestra el Markdown en bruto. Píntalo con un subconjunto seguro (párrafos, negritas, listas y títulos), **sin HTML ni `dangerouslySetInnerHTML`**, o quita las marcas. Lo mismo donde aparezca otro Markdown del modelo.
5. **PA-335:** el hueco en blanco bajo la app en Iterar (QA). El alto debe ocupar la ventana y los paneles desplazarse hasta abajo, a 1024×768, 1280×800 y 1440×900.

## Reglas
- **Puedes tocar:** `web/` (pantallas, componentes, hooks y `web/src/api/client.ts` solo para el 401 de PA-332) y sus pruebas.
  - **Coordinación con la sesión MCP**, que añade en paralelo los métodos de administración al final de `client.ts` y una zona nueva en el carril y en `AppShell`: tú no tocas el carril, y en `client.ts` y `AppShell` cambia lo mínimo. Así la fusión será sencilla.
  - No toques `api/`, `core/` ni `app/`.
- **Convenciones de `web/`:** componentes existentes, textos en español, enlaces por `safeHref`. Y avisa en tu mensaje final de cada componente compartido que hayas tocado.
- **Pruebas (Vitest con MSW):** una por cada arreglo, **deterministas** (nada que dependa de cuánto dura un estado en pantalla; el SSE de prueba está en `web/src/test/sse.ts`).
- **Verificación:** `npm run lint`, `npx tsc -b`, `npm test` (la suite completa, dos veces) y `npm run api:check` en verde. Los tamaños de ventana de PA-335, con Edge sin interfaz y un perfil nuevo (scripts en el scratchpad).
- **No mates procesos globales.** Pídeselo también a los subagentes.
- **Kanban:**
  - cierra cada PA con la fecha;
  - fila en el registro;
  - propuestas en **PA-127…PA-139**.
- **Antes del commit:** `spec-checker` CONFORME y `security-reviewer` APTO.
- **Sin fusionar.** Haz `git push -u origin ses-web-fixes` y avísame.

Empieza presentándome el plan (sobre todo la causa probable de PA-333 y cómo la reproduces) antes de escribir código.
