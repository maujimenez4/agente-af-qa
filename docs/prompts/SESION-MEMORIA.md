# SESIÓN MODELOS (antes Memoria) · Ronda 3: T-58, ajustes para modelos locales pequeños

Tu T-32 ya está fusionada en `PreProduccion`. En esta ronda la sesión cambia de rama y de tarea. Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-b switch -C ses-modelos origin/PreProduccion
cd .claude/worktrees/area-b
uv sync
uv run pytest -m "not integration"          # debe salir en verde antes de empezar
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-modelos`**, creada desde `PreProduccion`. Tu T-32 ya está fusionada (el registro de uso también lo usa la API de T-55). **En esta ronda haces T-58: ajustes para que los modelos locales pequeños generen artefactos válidos a la primera.**

Hay **otras sesiones trabajando a la vez**:
- **Principal:** `PreProduccion`. Integra; es dueña de los contratos, de la API (`api/`) y de la composición.
- **Ollama:** mide `qwen3:1.7b` sin razonamiento y `phi4-mini` con dos instrucciones nuevas en su script. Sus datos te llegarán por el usuario.
- **Flujo:** `ses-flujo`, con T-54, en `core/graph/` y `core/conversations.py`.
- **Jira:** `ses-jira`, con PA-208 y la prueba cruzada T-34.
- **Responsable del área B:** `web/` (React).

## De dónde sale T-58
La sesión Ollama midió cinco modelos locales con `StoryWriter.generate` (misma necesidad y mismo RAG, CPU). **Ninguno generó una HU válida a la primera.** Causas comunes:
1. **IDs de reglas:** 4 de los 5 modelos copian los identificadores del corpus (`RN-RES-01`), y el esquema exige `^RN-\d+$`. Cada fallo cuesta un reintento de 4–5 min.
2. **`sources` vacío:** los modelos pequeños omiten las citas y salta `CitationError` (phi4-mini falló así en los dos intentos).
3. **Razonamiento de `qwen3:1.7b`:** gasta ~40 % de los tokens de salida. Se desactiva con `reasoning_effort: "none"` o `think: false` en la petición (la sesión Ollama confirmará cuál funciona contra el endpoint OpenAI de Ollama).

Salidas en bruto: `docs/pruebas/salidas/generate_story-<modelo>.json`, en la carpeta principal, aún sin commit; pídeselas al usuario si las necesitas.

## Tareas (con la skill `/tarea T-58`) [RNF-09, RNF-10, RNF-12]
1. **Prompts** (`prompts/generate_story.md`, `evolve_story.md`, `structure_story.md`, `generate_tests.md`, `review_quality.md` y sus `*_retry.md`):
   - IDs: «numera `RN-01`, `RN-02`… y `CA-01`, `CA-02`… (y `CP-01`… en las suites) aunque las fuentes usen otros; el identificador del documento va en la descripción»;
   - citas: `sources` nunca vacío si el contexto trae fuentes;
   - sube la cabecera `version:` de cada prompt que cambies;
   - mide el efecto en tokens: los prompts largos cuestan ~1,5 min solo de lectura en CPU, así que no los alargues de más.
2. **Reparación determinista antes del reintento:** si la salida solo falla por IDs con otro formato (`RN-RES-01`, `CA1`…), se renumeran en orden sin llamar otra vez al LLM. El identificador original se conserva en el texto y, en evoluciones, se respetan los IDs que ya existían (`evolve_story`).
   - Diseña dónde va. Una opción es un registro de reparaciones por esquema en `adapters/llm/`, que importa `schemas/` pero no `core/`.
   - **No cambies `adapters/base.py` ni `schemas/`:** si el diseño lo necesita, para y escríbelo como propuesta.
   - Que la auditoría o el log digan cuándo se reparó.
3. **Razonamiento desactivable por modelo:**
   - **Autorizado por la principal** solo esto:
     - en `core/config.py`, un campo opcional en `ModelRef` (por ejemplo `options` o `reasoning: off`) con validación estricta;
     - en `core/factories.py`, pasarlo en `_openai_factory`.
   - En `adapters/llm/openai_compatible.py`, enviarlo como `extra_body`.
   - Sin el campo, todo sigue igual.
   - **No cambies `config/models.yaml`:** lo hará la sesión Ollama en su fase 2. Documenta el formato en tu informe.
4. **Cita vacía:** si una HU llega con `sources` vacío y el contexto tiene fuentes, el reintento de citas (`citation_retry.md`) debe pedirlo explícitamente. Revisa que ese camino existe y funciona.

Cuando la sesión Ollama entregue sus datos (vía el usuario), ajusta las prioridades.

## Reglas
- **Solo tus archivos:**
  - `prompts/`;
  - `core/functional/` y `core/qa/` (solo lo que T-58 necesite);
  - `adapters/llm/`;
  - en `core/config.py` y `core/factories.py`, **solo** lo autorizado arriba;
  - `tests/unit/` de esos módulos; en `tests/fakes/`, solo añadir.

  No toques `core/graph/` ni `core/conversations.py` (T-54 está ahí), `api/`, `app/`, `web/`, `schemas/`, `adapters/base.py`, `adapters/errors.py`, `config/` ni la SPEC.
- **Kanban:**
  - Cambia solo la fila de T-58 (a 🔄 y luego ✅) y las PA que cierres.
  - Añade tu fila al registro diario.
  - No toques el tablero resumen.
  - **Propuestas en PA-262…PA-299.**
- **Seguridad:** no leas ni muestres el `.env`; los logs no llevan prompts ni contenido.
- **LLM:** pruebas con fakes. **No lances pruebas reales con el LLM sin preguntarme** (minutos por llamada en CPU).
- **Antes de cada commit:**
  - `uv run pytest -m "not integration"`, `uv run ruff check .` y `uv run ruff format --check .` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Commits:**
  - Formato `T-58: descripción [RNF-09, RNF-10, RNF-12]`.
  - **Sin fusionar.** Haz `git push -u origin ses-modelos` y avísame.

Empieza por `/tarea T-58` y preséntame el plan (sobre todo el punto 2) antes de escribir código.
