# CLAUDE.md — Agente de IA de Análisis Funcional y QA

## Qué es este proyecto
MVP de un agente que genera y evoluciona Historias de Usuario (HU) y artefactos de QA a partir de Jira Cloud y de una base de conocimiento RAG. Publica en Jira **solo lo que un humano aprueba**. Tras publicar una HU, genera una memoria sintética `.md` y la reincorpora al RAG.

Lo desarrolla **una sola persona** orquestando sesiones de Claude Code: una sesión principal en `main` y dos worktrees (`area-a`, `area-b`).

Documentación de referencia (léela antes de implementar):
- `docs/specs/SPEC-00-fundacional.md` → arquitectura, contratos e interfaces (**fuente de verdad**).
- `docs/decisiones/01_declaraciones_proyecto.md` → requisitos RF/RNF, decisiones D-XX y revisiones R-XX.
- `docs/decisiones/02_investigacion_tecnologica.md` → justificación del stack.
- `docs/KANBAN.md` → tareas por día y estado.

## Principios NO negociables
1. **Aprobación humana**: nada escribe en Jira salvo el nodo `publish` de `core/graph`, y solo con el artefacto en estado `APPROVED` y confirmación explícita del usuario.
2. **Secretos**: nunca en el código, los tests, los fixtures, los prompts, los logs ni la documentación. Usa `pydantic.SecretStr` y placeholders (`TU_API_KEY`). La configuración se lee solo mediante `core/config.py` (pydantic-settings) desde `.env`.
3. **Datos sintéticos**: nunca uses nombres, emails, DNI ni datos reales. Usa Faker con `es_ES` o valores claramente ficticios.
4. **Trazabilidad**: todo artefacto referencia su origen (clave de Jira, IDs de CA, RN y CP).
5. **Eficiencia**: el LLM devuelve salidas estructuradas (modelos de `schemas/`), no texto libre para parsear.
6. **Sin alcance extra**: si ves una mejora no pedida, anótala en `docs/KANBAN.md` como "Propuesta adicional"; no la implementes.

## Stack
Python 3.12 · uv · LangGraph · SDK de OpenAI para proveedores compatibles (Groq, OpenRouter, Ollama) · PostgreSQL + pgvector · Alembic · Docling · Streamlit · httpx · pydantic v2 · structlog · pytest · ruff · Docker Compose · gitleaks.

**Modelos (D-14):** solo open-weight y gratuitos. Hay que respetar los límites de uso (429 → backoff → siguiente proveedor de la cadena). No añadas SDKs de otros proveedores.

**Jira nativo (D-09):** los casos de prueba son subtareas de la HU con la etiqueta `caso-prueba`; la estrategia y la matriz van como adjuntos `.md`; el impacto, como vínculos "relates to". No hay Xray.

## Comandos
```bash
uv sync                                   # dependencias (lockfile con hashes)
docker compose up -d db                   # PostgreSQL + pgvector
uv run alembic upgrade head               # migraciones
uv run pytest -m "not integration"        # pruebas sin servicios externos
uv run pytest -m integration              # contra Jira/LLM reales (requiere .env)
uv run ruff check . && uv run ruff format .
uv run streamlit run app/main.py
```

## Áreas y propiedad de directorios
| Directorio | Propietario | Nota |
|---|---|---|
| `schemas/`, `adapters/base.py`, `adapters/errors.py`, `core/config.py`, `core/container.py` | **Principal** | CONGELADO tras el día 1. No lo cambies desde un worktree; propón el cambio. |
| `adapters/jira/`, `adapters/testmgmt/`, `adapters/llm/`, `adapters/auth/` | **Área A** · Integraciones y núcleo | |
| `core/graph/`, `core/context/`, `core/state_machine.py`, `core/audit.py`, `core/impact/` | **Área A** | |
| `data/seed/jira/`, `migrations/` | **Área A** | |
| `adapters/embeddings/`, `adapters/vectorstore/`, `core/rag/` | **Área B** · Conocimiento y UI | |
| `prompts/`, `core/functional/`, `core/qa/`, `core/memory/` | **Área B** | |
| `app/`, `data/seed/corpus/`, `eval/` | **Área B** | |
| `tests/fakes/` | Ambas (añadir, no romper) | Dobles de prueba de cada protocolo |

Si tu tarea requiere tocar un directorio de la otra área: **para** y avisa.

## Convenciones de código
- Identificadores en **inglés**; textos de UI, prompts y artefactos generados en **español**.
- Tipado completo; `ruff` sin errores; funciones pequeñas y puras cuando sea posible.
- El núcleo depende solo de los `Protocol` de `adapters/base.py`, nunca de implementaciones concretas. La composición se hace en `core/container.py`.
- Los errores externos se envuelven en las excepciones de `adapters/errors.py`, con mensaje en español para la UI.
- Logs con structlog y campos `user`, `action`, `artifact_id`, `model`, `duration_ms`. Nunca registres secretos, cabeceras `Authorization` ni prompts completos.
- Prompts en `prompts/<tarea>.md` con cabecera `version:`; nunca en línea en el código.
- Jira: la búsqueda usa `/rest/api/3/search/jql` con `nextPageToken`; las descripciones y comentarios usan ADF (`adapters/jira/adf.py`).

## Pruebas
- Cada módulo lleva pruebas unitarias contra los fakes de `tests/fakes/`.
- Las pruebas contra servicios reales llevan `@pytest.mark.integration` y se saltan si faltan credenciales.
- Cada criterio de aceptación de la tarea tiene al menos una prueba.

## Flujo por tarea
1. Lee la tarea en `docs/KANBAN.md` y las secciones de la SPEC-00 que afecta.
2. Cambia su estado a 🔄 en el Kanban.
3. Implementa solo su alcance.
4. Usa el subagente `test-writer` para completar las pruebas; ejecuta pytest y ruff.
5. Pasa `spec-checker` y `security-reviewer`; corrige lo que marquen.
6. Cambia el estado a ✅ y anota lo relevante en el registro diario.
7. Commit: `T-XX: descripción breve [RF-YY]`.

## Definición de terminado
Pruebas en verde · ruff limpio · `security-reviewer` APTO · `spec-checker` CONFORME · Kanban actualizado.
