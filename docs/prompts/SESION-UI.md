# SESIÓN MODELOS · Ronda 15: que la misma HU de Jira salga igual cada vez (PA-432)

> Encargo de la **sesión Modelos**. Tu ronda 14 (PA-426) ya está fusionada.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-b switch -C ses-estructura-estable origin/PreProduccion
cd .claude/worktrees/area-b
uv sync
# Windows bloquea las extensiones compiladas de SQLAlchemy (PA-338): usa su versión en Python puro
find .venv/Lib/site-packages/sqlalchemy -name "*.pyd" -exec sh -c 'mv "$1" "$1.bloqueado"' _ {} \;
uv run python -m pytest -m "not integration"   # en verde
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-estructura-estable`**, creada desde `PreProduccion`. Tu ronda 14 ya está fusionada.

**Objetivo: PA-432** (lee su fila en `docs/KANBAN.md`). Tú mismo viste que AFQP-5 salió una vez con CA-01, CA-02, RN-01 y RN-02, y la siguiente solo con CA-01 y RN-01. **Para la demo importa mucho:** hacer lo mismo dos veces puede dar resultados distintos, y la cobertura de QA se mide frente a HU distintas.

## Tareas (propón el plan; las tres partes son candidatas)
1. **Temperatura 0 al estructurar.** La llamada que convierte la HU de Jira en `UserStory` (`structure_story`) debería ser lo más determinista posible.
   - Mira cómo pasa hoy las opciones el router (`options` por modelo en `config/models.yaml`, `reasoning_effort`) y propón la forma más limpia: una opción por tarea o una temperatura fija para esa llamada.
   - Si hace falta tocar `config/models.yaml` o `adapters/llm/`, dilo en el plan: está autorizado solo para esto.
   - La generación de propuestas (HU nueva, evolución, QA) **no** cambia de temperatura: ahí la variedad es útil.
2. **Reutilizar la estructura de la misma HU entre conversaciones.** PA-339 ya guarda la versión estructurada por conversación, con una huella de la incidencia.
   - Propón guardarla también por **clave de Jira y huella del contenido** (resumen, descripción y fecha de actualización). Así, la misma HU sin cambios en Jira se estructura una sola vez y todas las conversaciones parten de la misma.
   - Si la HU cambia en Jira, se vuelve a estructurar.
   - Ahorra además una llamada al modelo (unos 30 a 100 s con el modelo local) en cada conversación sobre esa HU.
3. **Si la HU de Jira ya trae criterios y reglas con su formato** (`### CA-01 · …` con Gherkin y `- RN-01: …`, como las HU del corpus sintético), valora pasarlos tal cual en lugar de que el modelo los reescriba. Solo si es sencillo y seguro; si no, queda como propuesta.

## Reglas
- **Puedes tocar:**
  - `core/functional/` (la estructuración);
  - lo mínimo de `core/graph/nodes.py` (`_baseline` y el guardado, sin tocar `publish` ni `_publish_approved`);
  - `core/artifact_state.py` (solo para la nueva entrada por clave);
  - `config/models.yaml` y `adapters/llm/` (solo para la temperatura);
  - `prompts/` si hace falta;
  - y sus pruebas.

  No toques `web/`, `api/` (el contrato no cambia), `schemas/` ni `app/`.
- **Pruebas con fakes:**
  - la llamada de estructuración lleva temperatura 0 y las demás no;
  - dos conversaciones sobre la misma HU sin cambios reutilizan la misma estructura sin llamar al modelo;
  - si la HU cambia en Jira (otra huella), se vuelve a estructurar;
  - la reutilización no cruza proyectos ni claves.
- **Prueba real:** con permiso del usuario, estructura AFQP-5 dos veces en dos conversaciones nuevas y comprueba que salen idénticas y que la segunda no llama al modelo. No pases la batería completa mientras dure.
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **gitleaks:** sin `secret`, `password` ni `token` como nombre de variables con literales.
- **Kanban:**
  - cierra PA-432 con la fecha;
  - tu fila en el registro;
  - propuestas en **PA-433, PA-434 y PA-436…PA-439**.
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - el contrato sin cambios (`uv run python -m api.export_openapi`);
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-estructura-estable` y avísame.

Empieza presentándome el plan antes de escribir código.
