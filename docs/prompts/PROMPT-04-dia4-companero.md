# PROMPT-04 · Día 4 · T-20 y T-19 (sesión del compañero)

Prepara el repositorio y pega todo lo que hay debajo de la línea como primer mensaje en Claude Code:

```bash
git fetch origin
git switch -c Dia4 origin/PreProduccion   # rama de trabajo, desde la rama de integración
uv sync
docker compose up -d db                   # PostgreSQL + pgvector
uv run alembic upgrade head
```

---

Vamos a trabajar en el proyecto "Agente de IA de Análisis Funcional y QA". Estás en la rama **`Dia4`**, creada desde **`PreProduccion`**, que es la rama de integración: todo el trabajo se fusiona en ella mediante PR, **nunca en `main`**. En paralelo, la sesión principal está haciendo **T-14 → T-18 → T-22** en `PreProduccion`. No toques sus directorios: `adapters/jira/`, `core/context/`, `core/graph/` y `adapters/auth/`.

## Tareas de esta sesión
Hazlas con la skill del proyecto, una detrás de otra o en paralelo con dos agentes, porque no comparten directorios:

1. **`/tarea T-20`**: prompts de HU nueva, de evolución y de revisión, con salida estructurada, IDs de CA y RN y citas [RF-15 a RF-18, RF-21]. Área B: `prompts/` y `core/functional/`.
   - Usa el `LLMProvider` real (`core/factories.build_llm_provider`) y el RAG real (`core/factories.build_embeddings` / `build_vector_store`; el corpus se indexa con `uv run python -m core.rag.indexing`) solo en pruebas marcadas `@pytest.mark.integration`. Las unitarias van contra los fakes de `tests/fakes/`.
   - Los prompts van en `prompts/<tarea>.md` con cabecera `version:` y se cargan con `core/rag/prompts.load_prompt`. Nunca escribas prompts en línea en el código.
   - Las citas (RF-21, RNF-14) solo pueden apuntar a fuentes recibidas en el contexto: una clave de Jira o el `doc_id` (`DOC-NN`) de un fragmento. Valídalo y rechaza las referencias inventadas.
   - Ten en cuenta el hallazgo de T-17 (registro del día 3): cuando un acta cambia una regla, la recuperación puede traer solo uno de los dos documentos.
2. **`/tarea T-19`**: versionado de HU (`artifact_versions`) y cálculo del diff por campo (`StoryDiff`) [RF-05, RF-19, RNF-16]. Área A: `core/impact/`.
   - El diff debe ser puro y determinista sobre dos `UserStory` (`schemas/`), y la persistencia de versiones debe ir contra la tabla `artifact_versions` de la migración `0001`.
   - Las pruebas de base de datos llevan `@pytest.mark.integration` y usan una BD temporal propia, siguiendo el patrón de `tests/unit/test_pgvector_store.py`.

## Reglas para que la fusión sea limpia
- Lee antes `CLAUDE.md`, `docs/specs/SPEC-00-fundacional.md` (congelada, v1.2, **incluido el anexo §11**) y, en `docs/KANBAN.md`, el registro de los días 2 y 3 y las propuestas adicionales.
- **Contratos congelados:** no modifiques `schemas/`, `adapters/base.py`, `adapters/errors.py`, `core/config.py`, `core/container.py` ni `.env.example`. Si necesitas un cambio en alguno, **para** y déjalo propuesto en el PR.
- **Kanban:**
  - Cambia solo el estado de las filas de T-19 y T-20.
  - Añade tu propia fila al registro diario (día 4).
  - **No toques el tablero resumen.**
  - Las propuestas adicionales nuevas, numéralas a partir de **PA-23**.
- **Seguridad:**
  - Nada de secretos, del contenido del `.env` ni de datos personales reales; solo datos sintéticos del dominio ficticio de Villaficticia.
  - Solo se escribe en Jira desde el nodo `publish`, y T-19 y T-20 no escriben en Jira.
- Pasa `spec-checker` y `security-reviewer` hasta obtener CONFORME y APTO, con `uv run pytest -m "not integration"` y `uv run ruff check .` en verde.
- **Commits:** `T-XX: descripción [RF-YY]`. Sube la rama con `git push -u origin Dia4` y abre **un PR por tarea contra `PreProduccion`**. Si solo puedes abrir uno, lista en la descripción las dos tareas y sus commits.

Empieza por `/tarea T-20` y preséntame el plan antes de escribir código.
