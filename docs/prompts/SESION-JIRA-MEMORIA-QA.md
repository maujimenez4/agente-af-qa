# SESIÓN JIRA · Ronda 16: memoria de QA (PA-485, RF-39)

> Encargo de la **sesión Jira**. Tu ronda 15 (PA-479…481) ya está fusionada. El MVP está cerrado con la etiqueta `demo-comite`; esto es **v1.1** y **no se fusiona hasta después de la presentación al comité**.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-a switch -C ses-memoria-qa origin/PreProduccion
cd .claude/worktrees/area-a
uv sync
# Windows bloquea las extensiones compiladas de SQLAlchemy (PA-338): usa su versión en Python puro
find .venv/Lib/site-packages/sqlalchemy -name "*.pyd" -exec sh -c 'mv "$1" "$1.bloqueado"' _ {} \;
uv run python -m pytest -m "not integration" -q -p no:cacheprovider   # en verde
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA" (el asistente se llama **FAQ**), ahora en la rama **`ses-memoria-qa`**, creada desde `PreProduccion`. Tu ronda 15 ya está fusionada.

**Contexto:** el usuario ha **revisado la D-07** (2026-10-14): la memoria .md de los artefactos de QA entra en v1.1 (**RF-39**, fila **PA-485** del Kanban).
- **Qué hay ya:** el generador (`core/memory/generator.py`, `LLMMemoryGenerator`) no distingue el tipo de artefacto y ya admite los CP de una suite (PA-219). El nodo `memorize` de `core/graph` solo lo pide para HU publicadas.
- **Calendario:** mañana se presenta el MVP al comité, así que esta ronda se queda en tu rama hasta después.

Lee:
- la D-07 y RF-36 a RF-39 en `docs/decisiones/01_declaraciones_proyecto.md`;
- la SPEC-00 en lo que dice de la memoria y del nodo `memorize`;
- `core/memory/` (generador, lector, `seed_demo`) y `schemas/memory.py`;
- `core/rag/` (cómo se indexan y priorizan las memorias);
- el `prompts/` de la memoria;
- `api/memories.py`.

## Tareas (propón el plan antes de escribir código)
1. **Generar la memoria al publicar una suite**, con las mismas reglas que la de una HU:
   - **Cuándo:** solo tras una publicación **real** (en simulación no hay memoria, como en las HU) y después de que Jira confirme las subtareas.
   - **Si la memoria falla,** no deshace la publicación: queda registrado, como hoy.
   - **Un solo punto de escritura en Jira:** `publish` (principio 1). La memoria no escribe en Jira.
2. **Contenido de la memoria de QA:**
   - la HU de origen (`jira_key` de la HU) y los CP con su CA o RN;
   - la estrategia, los datos de prueba relevantes y las decisiones de cobertura, como las RN que quedaron sin caso.
   - Si el prompt actual no sirve, crea `prompts/<tarea>.md` con su cabecera `version:`, sin texto en línea en el código.
   - La validación es la de siempre: los IDs existen y están todos, las referencias se filtran contra las fuentes y no hay datos personales ni secretos.
3. **Reindexado sin duplicar (RF-38):** si se vuelve a publicar la suite de la misma HU, la memoria de QA se **sustituye**. Una HU puede tener a la vez su memoria funcional y su memoria de QA: que no se pisen.
4. **Recuperación en el RAG:** decide y justifica en el plan qué tareas usan las memorias de QA.
   - Lo esperable: las de **QA** (generar o iterar una suite) las usan y priorizan; la redacción de HU no debería verlas antes que las memorias funcionales.
   - Sin cambiar el comportamiento actual de las memorias de HU.
5. **API de memorias:** si `GET` de memorias ya expone `artifact_type`, no cambies el contrato. Si para que la web distinga «HU» y «Suite de QA» hace falta algo nuevo, **no lo hagas**: anótalo como propuesta (es de la principal y de la sesión UI).
6. **Documentación:**
   - la SPEC-00, la sección de la memoria;
   - el README, si nombra la memoria;
   - RF-39 a ✅ en las declaraciones cuando termines.

## Reglas
- **Puedes tocar:** `core/graph/` (solo el camino de la memoria tras publicar), `core/memory/`, `core/rag/` (solo el filtro o la prioridad por tipo), `prompts/`, `tests/`, `tests/fakes/` (añadir, no romper) y la documentación anterior.
- **No toques:** `web/`, `api/` (salvo para leer), el contrato, `schemas/` (congelado: si `Memory` no basta, para y proponlo), `core/config.py`, `core/container.py` ni la lógica de aprobación.
- **Principio 1 y PA-450:** no cambies cuándo ni cómo se publica una suite. Nunca una segunda suite de una HU que ya tiene casos.
- **Datos sintéticos** en pruebas y fixtures.
- **Sin pruebas reales** contra Jira ni el LLM. Si quieres una prueba real, márcala `integration` y no la ejecutes.
- **Pruebas con fakes**, al menos una por criterio:
  - publicar en real una suite genera e indexa su memoria; en simulación, no;
  - un fallo de la memoria no deshace la publicación;
  - volver a publicar sustituye la memoria de QA y no toca la funcional de la misma HU;
  - la generación de una suite recupera las memorias de QA con prioridad, y la redacción de una HU no las antepone a las funcionales;
  - la validación rechaza CP inventados y datos personales;
  - la memoria de una HU sigue igual que antes (regresión).
- **Windows:** `uv run python -m pytest -m "not integration" -q -p no:cacheprovider`.
- **gitleaks:** sin `secret`, `password` ni `token` como nombre de variables con literales.
- **Kanban:**
  - cierra PA-485 con la fecha;
  - tu fila en el registro;
  - propuestas nuevas en **PA-492…PA-495**.
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - el contrato sin cambios (`uv run python -m api.export_openapi`);
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-memoria-qa` y avísame.

Empieza presentándome el plan antes de escribir código.
