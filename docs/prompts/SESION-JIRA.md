# SESIÓN JIRA · Ronda 14: lo que encontró la auditoría en la publicación (PA-450, PA-453, PA-454)

> Encargo de la **sesión Jira**. Sale de la auditoría completa del 2026-10-08 (`docs/auditorias/AUDITORIA-2026-10-08.md`). Hay otras tres sesiones trabajando a la vez (Seguridad, Modelos y UI): respeta tu zona.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-a switch -C ses-auditoria-jira origin/PreProduccion
cd .claude/worktrees/area-a
uv sync
# Windows bloquea las extensiones compiladas de SQLAlchemy (PA-338): usa su versión en Python puro
find .venv/Lib/site-packages/sqlalchemy -name "*.pyd" -exec sh -c 'mv "$1" "$1.bloqueado"' _ {} \;
uv run python -m pytest -m "not integration"   # en verde
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-auditoria-jira`**, creada desde `PreProduccion`.

**Contexto:** la auditoría del 2026-10-08 encontró un hallazgo de gravedad alta y varios medios en la publicación. Lee el informe (secciones «Corrección» y «Propuestas») y las filas **PA-450, PA-453 y PA-454** de `docs/KANBAN.md`. Son de tu zona: `adapters/testmgmt/`, `adapters/jira/`, `core/graph/` (publicar y generar) y `api/service.py`.

## Tareas, por prioridad (propón el plan antes de escribir código)
1. **PA-450 (alta) · Una segunda suite de la misma HU se da por publicada sin llegar a Jira.**
   - **El fallo:** la idempotencia de `publish_suite` (PA-05) solo compara el prefijo `[CP-XX]` de las subtareas de la HU (`adapters/testmgmt/jira_native.py:186-191`, `:214-220`). Una conversación de QA nueva vuelve a numerar desde CP-01: sus casos se toman por existentes, no se crea nada y el artefacto pasa a `PUBLISHED` con las claves antiguas.
   - **Caso real:** AFQP-27 ya tiene AFQP-29 a AFQP-34. Una suite nueva de AFQP-27 caería aquí.
   - **Decide conmigo en el plan qué debe pasar.** Las opciones:
     - **(a)** Limitar la idempotencia al artefacto (una etiqueta o huella con el id del artefacto en la subtarea) y crear casos nuevos, continuando la numeración tras el último CP de la HU.
     - **(b)** Actualizar las subtareas existentes con el mismo CP cuando el contenido cambia, como versión nueva de la suite.
     - **(c)** Rechazar con un mensaje claro, sin publicar nada.

     En cualquier opción, un CP reutilizado con otro contenido **no puede contar como creado**: es un conflicto visible.
   - **Respeta D-09:** casos como subtareas con la etiqueta `caso-prueba`.
2. **PA-453 · Publicación parcial de `update_story`.** Si el PUT va bien y falla el comentario del diff:
   - audita la clave ya escrita en `interrupted`;
   - y que, tras reiniciar la API, la conversación muestre error en lugar de quedarse en «aprobada» sin resultado (`adapters/jira/tracker.py:221-231`, `core/graph/nodes.py:822-836`, `api/service.py:694-703`).
3. **PA-454 · `generate` idempotente ante `/retry`.** Si se guarda la versión N+1 y falla la auditoría, el reintento no debe acabar en `VersionConflictError` sin salida (`core/graph/nodes.py:231-249`, `:514-516`; `core/impact/versions.py:121-126`).
4. **Si queda tiempo · los textos de «descarta la conversación»** (`api/cancel.py:27-29`, `core/graph/nodes.py:579-583`). Una conversación en error no se puede descartar, así que corrige los textos para que no prometan esa acción. El contrato no cambia.

## Reglas
- **Puedes tocar** `adapters/testmgmt/`, `adapters/jira/`, `core/graph/nodes.py` (**solo** publicar y generar: la sesión Seguridad toca `_edit`), `core/graph/execution.py`, `core/impact/versions.py`, `api/service.py`, `api/cancel.py`, `prompts/` si hace falta, y sus pruebas.
- **No toques** `web/`, `schemas/`, `core/functional/`, `core/quality.py`, `adapters/llm/`, `api/app.py` ni `api/sessions.py` (de otras sesiones). El contrato (`docs/api/openapi.yaml`) no cambia; si lo necesitas, avísame antes.
- **Principio 1:** nada nuevo escribe en Jira fuera de `publish`, y todo sigue con aprobación humana.
- **Pruebas con fakes**, una por criterio. Para PA-450, haz el fake de `publish_suite` idempotente como el real (hallazgo de pruebas de la auditoría) y prueba la segunda suite de la misma HU.
- **Prueba real:** solo con permiso del usuario, y en AFQP.
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **gitleaks:** sin `secret`, `password` ni `token` como nombre de variables con literales.
- **Kanban:**
  - cierra las PA hechas con la fecha;
  - tu fila en el registro;
  - propuestas nuevas en **PA-462…PA-464**.
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - el contrato sin cambios (`uv run python -m api.export_openapi`);
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-auditoria-jira` y avísame.

Empieza presentándome el plan, con la opción que recomiendas para PA-450, antes de escribir código.
