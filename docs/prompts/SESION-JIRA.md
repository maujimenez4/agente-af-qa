# SESIÓN JIRA · Ronda 3: PA-208 y prueba cruzada T-34 (el área A prueba el área B)

Tu rama `ses-jira` ya está fusionada en `PreProduccion`: `record_execution`, con su prueba real en el sandbox (T-47 sigue 🔄). Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-a switch -C ses-jira origin/PreProduccion
cd .claude/worktrees/area-a
uv sync
uv run pytest -m "not integration"          # debe salir en verde antes de empezar
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", en la rama **`ses-jira`**, recién puesta al día desde `PreProduccion`. Tu parte de T-47 (`JiraNativeTests.record_execution`) ya está fusionada.

**El resto de T-47 lo hace la principal:**
- añadir `record_execution` al protocolo `TestManagement` (`adapters/base.py`, congelado);
- la aprobación humana del resultado;
- la ruta de la API.

Tú no lo tocas.

Hay **otras sesiones trabajando a la vez**:
- **Principal:** `PreProduccion`. Integra; dueña de los contratos y de la API (`api/`).
- **Flujo:** `ses-flujo`, con T-54, en `core/graph/` y `core/conversations.py`.
- **Modelos:** `ses-modelos`, con T-58, en `prompts/`, `core/functional/`, `core/qa/` y `adapters/llm/`.
- **Ollama:** medición de modelos locales.

## 1. PA-208: idempotencia de `record_execution` [RF-28]
Repetir el registro con el mismo resultado y la misma evidencia no debe dejar un segundo comentario. La transición y la etiqueta ya no se duplican.
- Antes de comentar, lee los últimos comentarios de la subtarea y compara el resultado y una huella de la evidencia.
- Pruebas unitarias con `httpx.MockTransport`. La prueba real con `JIRA_WRITE_TESTS=1` ya está autorizada, pero **avísame antes de ejecutarla**.
- Cierra PA-208 en el Kanban.

## 2. `/tarea T-34`: prueba cruzada, el área A prueba el área B [RNF-19]
Con mirada de fuera: **solo pruebas nuevas e informe, sin cambiar código del área B**.

- **Alcance:**
  - `core/rag/` (ingesta, troceado, búsqueda y prioridad de la memoria);
  - `core/memory/` (generador y reindexado sin duplicados, T-33);
  - `adapters/embeddings/` y `adapters/vectorstore/` (con fakes; pgvector, con la marca `integration`);
  - `core/quality.py` (T-48);
  - `core/guided_start.py` (T-53).
- **Fuera del alcance:**
  - `core/functional/`, `core/qa/` y `prompts/`: los está cambiando la sesión Modelos;
  - `app/`: Streamlit es el plan B.
- **Cómo:**
  - usa `test-writer` para las pruebas que falten frente a los RF y CA de cada módulo;
  - usa `spec-checker` para comparar con la SPEC-00 y las especificaciones de las épicas;
  - las pruebas nuevas van en archivos `tests/unit/test_cross_b_*.py`, para no chocar con nadie.
- **Si encuentras un fallo:**
  - marca la prueba con `xfail(strict=True)`, con el archivo y la línea del fallo;
  - anótalo como propuesta.

  No lo corrijas: lo decide la principal.
- **Informe** en tu fila del registro diario: qué cubriste, los fallos encontrados (con su PA) y lo que queda sin cubrir.

## Reglas
- **Solo tus archivos:**
  - `adapters/jira/` y `adapters/testmgmt/` (PA-208);
  - `tests/unit/test_jira_*.py`, `tests/unit/test_testmgmt*.py` y `tests/unit/test_cross_b_*.py`;
  - `tests/integration/test_jira_*`;
  - en `tests/fakes/`, solo añadir.

  No toques el código de `core/`, `api/`, `app/`, `web/`, `schemas/`, `adapters/base.py`, `adapters/errors.py`, `prompts/`, `config/` ni la SPEC.
- **Kanban:**
  - Cambia solo T-34 (a 🔄 y luego ✅) y las PA que cierres.
  - Añade tu fila al registro diario.
  - No toques el tablero resumen.
  - **Propuestas en PA-210…PA-249.**
- **Seguridad:** tokens solo vía `SecretStr`; nunca registres `Authorization` ni cuerpos; no imprimas el `.env`; datos ficticios.
- **LLM:** no lo necesitas. Si una prueba lo pide, usa los fakes.
- **Antes de cada commit:**
  - `uv run pytest -m "not integration"`, `uv run ruff check .` y `uv run ruff format --check .` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Commits:**
  - Formato `T-XX: descripción [RF-YY]` (para PA-208: `T-47: idempotencia del registro de ejecución (PA-208) [RF-28]`).
  - **Sin fusionar.** Haz `git push origin ses-jira` y avísame.

Empieza por PA-208 y preséntame el plan de T-34 antes de escribir pruebas.
