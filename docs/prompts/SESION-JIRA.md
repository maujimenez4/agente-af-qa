# SESIÓN JIRA · Ronda 4: corregir los defectos de la prueba cruzada T-34

Tu T-34 ya está fusionada en `PreProduccion` (240 pruebas, 50 `xfail` estrictos, PA-211…PA-224). Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-a switch -C ses-jira origin/PreProduccion
cd .claude/worktrees/area-a
uv sync
uv run pytest -m "not integration"          # en verde, con 50 xfailed
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", en la rama **`ses-jira`**, recién puesta al día desde `PreProduccion`. Tu T-34 ya está fusionada.

**En esta ronda corriges los defectos que encontraste.** El área B ya no tiene responsable de backend: su responsable hace el frontend en React. La principal te autoriza a tocar el código de esas PA.

Hay **otras sesiones trabajando a la vez**:
- **Principal:** `PreProduccion`; contratos, API y composición.
- **Modelos:** `ses-flujo`, con T-54, en `core/graph/`, `core/conversations.py`, `core/qa/` y una migración nueva.
- **UI:** `ses-ui`, con T-28 en `app/` (Streamlit).
- **Ollama:** medición y configuración de modelos (`config/models.yaml`).

## Orden de trabajo (de más a menos impacto en la demo)
**Bloque 1 · datos y flujo de la demo:**
1. **PA-214:** ids de documento duplicados (un documento borra a otro al indexar). Rechaza o desambigua el id, con un error claro.
2. **PA-216:** indexación no atómica y `zip(strict=True)` sin envolver. Que un fallo no deje el documento fuera del índice.
3. **PA-218:** falso positivo de secreto en la memoria, que acaba en error tras publicar una HU.
4. **PA-222:** revisar la calidad.
   - Comprueba el tipo de la incidencia.
   - Valida los IDs que se mencionan en el texto, no solo `target_id`.
5. **PA-223:**
   - la vista previa de fuentes aplica `normalize_excluded_sources`, como el grafo;
   - el tipo «Épica» se reconoce también en NFD.
6. **PA-211:** solapamiento nulo en prosa al trocear. Afecta a la calidad del RAG.
   - Si cambia el troceado, avisa: habrá que reindexar el corpus.

**Bloque 2 · robustez:**
- PA-212 (encabezados y vallas);
- PA-213 (BOM en la ingesta);
- PA-215 (delimitadores en el prompt de clasificación);
- PA-217 (CLI de indexación);
- PA-220 (embeddings: `retry-after` e índices);
- PA-221 (pgvector: vector de consulta y categorías mezcladas);
- PA-224 (prompts: BOM, cuerpo vacío y nombre).

**Fuera de esta ronda:**
- La parte de **PA-219** que pide `min_length` en `schemas/memory.py` (congelado): propónla y la hace la principal. La parte del `CP-99` en `TRACE_ID` sí es tuya.
- No toques `core/qa/` (T-54).

## Cómo
- Por cada PA, quita el `xfail` de sus pruebas (o invierte las de comportamiento fijado, como indicaste en cada PA) y corrige el código hasta que pasen.
- Un commit por PA o por grupo pequeño: `T-34: corrige PA-2XX … [RF-YY]`.
- Cierra cada PA en el Kanban con la fecha.
- Si una corrección necesita cambiar un contrato (`schemas/`, `adapters/base.py`, `adapters/errors.py`, `core/config.py`), **para y escríbelo como propuesta**.

## Reglas
- **Puedes tocar:**
  - `core/rag/`, `core/memory/`, `core/quality.py`, `core/guided_start.py` y `core/context/service.py` (solo para `NOT_STORIES`, PA-223);
  - `adapters/embeddings/` y `adapters/vectorstore/`;
  - `prompts/` (solo PA-215, si hace falta);
  - sus pruebas y `tests/unit/test_cross_b_*.py`.

  No toques `core/graph/`, `core/conversations.py`, `core/qa/`, `api/`, `app/`, `web/`, `config/`, `schemas/` ni los contratos.
- **Kanban:** cambia solo las PA que cierres y añade tu fila al registro. No toques el tablero. **Propuestas en PA-225…PA-249.**
- **Seguridad:** no leas el `.env`; datos ficticios; los logs no llevan contenido.
- **LLM:** solo fakes.
- **Antes de cada commit:**
  - `uv run pytest -m "not integration"`, `uv run ruff check .` y `uv run ruff format --check .` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO al terminar cada bloque.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push origin ses-jira` al terminar cada bloque y avísame.

Empieza por el bloque 1 y preséntame el plan breve antes de tocar código.
