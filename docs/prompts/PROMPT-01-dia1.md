# PROMPT-01 · Día 1 · Sesión principal (main)

Copia todo lo que hay debajo de la línea y pégalo como primer mensaje en Claude Code.

---

Vamos a construir la estructura principal del repositorio del proyecto "Agente de IA de Análisis Funcional y QA". Hoy es el día 1 del Kanban.

## Contexto que debes leer primero
Lee completos, en este orden, antes de proponer nada:
1. `CLAUDE.md`
2. `docs/specs/SPEC-00-fundacional.md`
3. `docs/KANBAN.md` (Día 1)
4. `docs/decisiones/01_declaraciones_proyecto.md` (secciones 5, 6.2, 7, 10 y 11)

## Objetivo de esta sesión
Completar las tareas **T-01 a T-07** del Kanban, en orden. T-08 la hago yo en paralelo (Jira y claves) y T-09 irá en otra sesión.

## Forma de trabajar
1. **Primero, planifica sin escribir código.** Preséntame:
   - el árbol de directorios y archivos que vas a crear (según la SPEC-00 y la tabla de áreas de `CLAUDE.md`);
   - la lista de dependencias de `pyproject.toml`, separadas en principales y de desarrollo;
   - cualquier ambigüedad o contradicción que detectes en la documentación.
   Espera mi confirmación antes de continuar.
2. Después, implementa **una tarea cada vez**. Al terminar cada una:
   - ejecuta `uv run pytest -m "not integration"` y `uv run ruff check .`;
   - usa el subagente `security-reviewer` sobre los cambios;
   - actualiza su estado en `docs/KANBAN.md`;
   - haz commit con el formato `T-XX: descripción [RF/RNF]`;
   - dame un resumen de 3–5 líneas y continúa con la siguiente.
3. **Detente y pregúntame** después de T-04 (entorno y base de datos listos) y después de T-07 (grafo con fakes funcionando).

## Detalles por tarea
- **T-01**: Python 3.12 con uv. Crea todos los paquetes de la SPEC-00 con `__init__.py` y un docstring de una línea que diga qué contendrá. Crea `data/memory/.gitkeep`. Añade los marcadores de pytest `integration` en `pyproject.toml`. Añade dependencias con `uv add` (que genera el lockfile) en su última versión estable; no fijes versiones de memoria. **No uses LiteLLM ni SDKs de proveedores concretos**: solo el SDK `openai`, porque Groq, OpenRouter y Ollama son compatibles con él (D-14).
- **T-02**: `.pre-commit-config.yaml` con gitleaks y ruff. CI en `.github/workflows/ci.yml` con ruff, pytest (sin integración) y gitleaks.
- **T-03**: `core/config.py` con pydantic-settings: todos los secretos como `SecretStr`, carga de `config/models.yaml` validada con modelos Pydantic (cada tarea es una lista ordenada de `{provider, model}`), y los proveedores sin clave marcados como no disponibles (sin fallar). `core/logging.py` con structlog en JSON y un procesador que enmascare valores de secretos y patrones de token. Añade pruebas que demuestren que un secreto no aparece en los logs.
- **T-04**: usa el `docker-compose.yml` existente. Inicializa Alembic y crea la migración inicial con **todas** las tablas de la SPEC-00 §6, incluida la extensión `vector` y el índice sobre `chunks.embedding`. La dimensión del vector se lee de la configuración.
- **T-05**: todos los modelos de `schemas/` de la SPEC-00 §3, incluidos `coverage()` y `coverage_md()` de `TestSuite` y `to_markdown()` de `Memory`. `core/state_machine.py` con las transiciones válidas y `InvalidTransitionError`. Pruebas de validación y de todas las transiciones (válidas e inválidas).
- **T-06**: `adapters/base.py` con los protocolos exactamente como en la SPEC-00 §4 (incluye los tipos auxiliares `IssueSummary`, `IssueDetail`, `Message`, `LLMResult`, `StructuredResult`, `Chunk`, `RetrievedChunk`, `PublishResult`, `User` y `TaskType`). `adapters/errors.py`. En `tests/fakes/`, un fake por protocolo con **datos sintéticos** coherentes entre sí (una épica, tres HU y un par de documentos ficticios), más pruebas de que cada fake cumple su protocolo.
- **T-07**: `core/graph/` con el estado y los nodos de la SPEC-00 §5 usando los fakes mediante `core/container.py`. `human_review` usa `interrupt()`. Para las pruebas usa el checkpointer en memoria; el de Postgres se conectará más adelante. Pruebas de los tres caminos: iterar → aprobar → publicar → memorizar; descartar; e intento de publicar sin aprobación, que debe fallar.

## Restricciones
- Respeta al pie de la letra los contratos de la SPEC-00. Si crees que algo debe cambiar, **pregúntame antes**.
- No implementes adaptadores reales (Jira, LLM, pgvector): eso empieza el día 2 en los worktrees.
- Ningún secreto ni dato personal real en ningún archivo. Usa solo placeholders y datos sintéticos.
- No añadas funcionalidades fuera de T-01 a T-07; anota las ideas como "Propuesta adicional" en el Kanban.

Empieza leyendo la documentación y presentándome el plan.
