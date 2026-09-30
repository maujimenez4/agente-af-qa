# PROMPT-05 · Día 5 · T-26 y T-23 (sesión del compañero)

Prepara el repositorio y pega todo lo que hay debajo de la línea como primer mensaje en Claude Code:

```bash
git fetch origin
git switch -c Dia5 origin/PreProduccion   # rama de trabajo, desde la rama de integración
uv sync
docker compose up -d db                   # PostgreSQL + pgvector
uv run alembic upgrade head
```

---

Vamos a trabajar en el proyecto "Agente de IA de Análisis Funcional y QA". Estás en la rama **`Dia5`**, creada desde **`PreProduccion`**, que es la rama de integración: todo se fusiona en ella mediante PR, **nunca en `main`**.

En paralelo, la sesión principal está haciendo en `PreProduccion`:
- la conexión de los prompts de HU (T-20) al nodo `generate`;
- la estructuración de la HU de Jira en `UserStory`;
- después **T-21** (impacto) y **T-25** (auditoría y `publish`).

**No toques sus archivos:** `core/graph/`, `core/context/`, `core/impact/`, `core/functional/writer.py`, `adapters/`, `core/approvals.py` ni `core/audit.py`.

## Tareas de esta sesión
Hazlas con la skill del proyecto; no comparten archivos, así que puedes llevarlas en paralelo con dos agentes.

1. **`/tarea T-26`**: prompts de casos de prueba y escenarios Gherkin, matriz de cobertura, datos sintéticos y riesgos [RF-22 a RF-25, RF-27]. Área B: `prompts/` y `core/qa/`.
   - **Entrada: una `UserStory` ya estructurada**, no la incidencia de Jira. La sesión principal está haciendo el conversor de Jira a `UserStory`; tú recibes la HU hecha. En las pruebas usa `tests/fakes/dataset.renewal_story()` y las HU del seed.
   - **Salida estructurada: `TestSuite`** (`schemas/test_case.py`, congelado). Casos positivos, negativos, alternos y de excepción (RF-22). Cada `TestCase` lleva `criterion_ids`, `rule_ids`, tipo, precondiciones, pasos con datos y resultado esperado, Gherkin y prioridad (RF-23). Añade también `synthetic_data`, `risks`, `dependencies` e `impact_areas` (RF-25, RF-27) y `strategy_md` (RF-26, aunque su pestaña de la UI sea T-28).
   - **Validación de cobertura** (sincronización del día 6): cada CP referencia CA y RN **que existen** en la HU, y **todo CA tiene al menos un CP**. Si falla, reintenta una vez con el error y después lanza un error en español para la UI, con el mismo patrón que `core/functional/citations.py` y `citation_retry.md`. Usa `TestSuite.coverage()` y `coverage_md()`, que ya existen.
   - **Contexto y citas:** reutiliza `core/functional/context.py` (`render_context`, `escape_data`) y las citas de `core/functional/citations.py`. El contexto de Jira y del RAG son **datos no confiables**: los prompts deben decir que se ignoren las instrucciones que aparezcan dentro, como en `prompts/generate_story.md`.
   - **Datos sintéticos (RF-25):** coherentes con las RN de la HU y con el dominio ficticio de Villaficticia. Nunca datos personales reales; si hacen falta nombres, que sean claramente inventados.
   - Prompts en `prompts/generate_tests.md` (y un prompt de reintento de cobertura si lo necesitas), con cabecera `version:`. Nunca los escribas en línea en el código.
   - **No** conectes el nodo `generate` del grafo en modo QA: lo hará la sesión principal al fusionar. Tu entrega es `core/qa/` y sus pruebas.
2. **`/tarea T-23`**: rediseño de la UI (D-12) en `docs/specs/UI.md` [RNF-15]. Es solo un documento, sin código. Debe incluir:
   - **Pestañas:** Contexto, Historia, QA, Revisión y publicación, Memoria y Administración; qué ve cada rol según `core/permissions.py` (`can`/`require`).
   - **Flujo:** login → elección del origen (clave, navegación Proyecto → Épica → HU con `list_projects`/`list_epics`/`list_children`, búsqueda simple o necesidad nueva) → generación → chat de iteración (RF-20) → revisión y publicación.
   - **Contrato de aprobación (anexo §11 de la SPEC):** la UI muestra `target` (la operación que se hará en Jira) y devuelve `{"decision": "approve", "fingerprint": …}` con la huella recibida en el `interrupt`. Sin huella no se puede aprobar.
   - Vista previa y diff visual (RF-31, RNF-16, `StoryDiff` de T-19), edición manual antes de aprobar (RF-32), selector de modelo (RF-42) y consumo de tokens (RF-43).
   - Estados vacío, cargando y error, con los mensajes en español de `adapters/errors.py`. Estilo sobrio y accesible, todo en español.
   - Un boceto en texto o ASCII de cada pestaña. Streamlit, sin frontend separado (D-04).

## Reglas para que la fusión sea limpia
- Lee antes `CLAUDE.md`, `docs/specs/SPEC-00-fundacional.md` (congelada, v1.3, **con el anexo §11**) y, en `docs/KANBAN.md`, las decisiones y el registro del día 4.
- **Contratos congelados:** no modifiques `schemas/`, `adapters/base.py`, `adapters/errors.py`, `core/config.py`, `core/container.py` ni `.env.example`. Si necesitas un cambio en alguno, **para** y déjalo propuesto en el PR.
- **Kanban:**
  - Cambia solo el estado de las filas de T-23 y T-26.
  - Añade tu propia fila al registro diario (día 5).
  - **No toques el tablero resumen.**
  - **Numera tus propuestas adicionales desde PA-60** (rango reservado para esta sesión; la principal usa PA-35…PA-59).
- **Seguridad:**
  - Nada de secretos, del contenido del `.env` ni de datos personales reales.
  - Solo se escribe en Jira desde el nodo `publish`, y T-23 y T-26 no escriben en Jira.
  - Los logs no registran prompts ni contenido.
- Pasa `spec-checker` y `security-reviewer` hasta CONFORME y APTO, con `uv run pytest -m "not integration"` y `uv run ruff check .` en verde. Si tienes Docker, Ollama y el `.env`, ejecuta también las pruebas `integration`; si no, déjalas marcadas y lo verificará la sesión principal.
- **Commits:** `T-XX: descripción [RF-YY]`. Sube la rama con `git push -u origin Dia5` y abre un PR por tarea contra `PreProduccion`.

Empieza por `/tarea T-26` y preséntame el plan antes de escribir código.
