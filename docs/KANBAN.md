# KANBAN · Agente de IA de AF y QA

**Estados:** ⬜ Backlog · 🔄 En curso · 👀 En revisión · ✅ Hecho · ⛔ Bloqueado
**Sesiones:** P = principal (`main`) · A = worktree `area-a` (Integraciones y núcleo) · B = worktree `area-b` (Conocimiento y UI) · Tú = tarea manual

> Regla: al empezar una tarea, cámbiala a 🔄; al terminarla y pasar `spec-checker` y `security-reviewer`, cámbiala a ✅. Cada día se cierra con su **punto de sincronización**: fusionar A y B en `main`, rebase de los worktrees y verificar el hito.

## Tablero resumen

| ⬜ Backlog | 🔄 En curso | 👀 En revisión | ✅ Hecho | ⛔ Bloqueado |
|---|---|---|---|---|
| T-08, T-10 … T-36, T-39 … T-46 | — | — | T-01, T-02, T-03, T-05, T-06, T-07, T-09 | T-04 (WSL pendiente de instalación por TI), T-37, T-38 (R-01) |

---

## Día 1 · Cimientos (P + Tú; B empieza el corpus)

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-01 | Repo, uv, `pyproject`, ruff, pytest y estructura de carpetas de la SPEC-00 | P | — | RNF-17, RNF-26 | ✅ |
| T-02 | Pre-commit con gitleaks y CI (ruff, pytest sin integración, gitleaks) | P | T-01 | RNF-01, CA-00-05 | ✅ |
| T-03 | `core/config.py` (pydantic-settings, SecretStr) y structlog con enmascarado | P | T-01 | RNF-01, RNF-02, RNF-23 | ✅ |
| T-04 | Docker Compose con pgvector, Alembic y migraciones de las tablas de la SPEC-00 §6 | P | T-01 | RNF-20, CA-00-06 | ⛔ |
| T-05 | `schemas/` y `core/state_machine.py` con pruebas | P | T-01 | SPEC-00 §3, RF-34, CA-00-07 | ✅ |
| T-06 | `adapters/base.py`, `adapters/errors.py` y `tests/fakes/` para todos los protocolos | P | T-05 | SPEC-00 §4, CA-00-03 | ✅ |
| T-07 | Esqueleto del grafo LangGraph con fakes, `interrupt()` y reanudación | P | T-06 | CA-00-04 | ✅ |
| T-08 | Crear sitio Jira Cloud y proyecto de pruebas, verificar el tipo subtarea, token con scopes; crear cuentas gratuitas en Groq y OpenRouter; instalar Ollama y descargar bge-m3 y un modelo pequeño; fijar `config/models.yaml` | Tú | — | D-03, D-14, RNF-04 | ⬜ |
| T-09 | Corpus piloto sintético: dominio ficticio, 15–25 documentos Markdown en las 7 categorías | B | T-01 | D-06 | ✅ |

**🔗 Sincronización:** `CLAUDE.md`, contratos y fakes aprobados → **congelar la SPEC-00** → crear los worktrees `area-a` y `area-b`.

## Día 2 · Proveedores e ingesta

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-10 | `OpenAICompatibleProvider`, `FallbackLLMProvider` (429 → backoff → siguiente), router por tarea desde `models.yaml`, validación y reintento de salidas estructuradas, y registro en `llm_usage` | A | T-06, T-08 | RF-40 a RF-44, RNF-27, RNF-28 | ⬜ |
| T-11 | `JiraCloudTracker` de lectura: `test_connection`, `get_issue` con `adf_to_text` y relaciones | A | T-06, T-08 | RF-01, RF-03 | ⬜ |
| T-12 | Ingesta: carga, extracción con Docling, normalización y clasificación por categoría | B | T-06, T-09 | RF-07, RF-08, RF-12 | ⬜ |
| T-13 | Fragmentación por encabezados + recursiva, con metadatos | B | T-12 | RF-09 | ⬜ |

**🔗 Sincronización:** la clasificación de fuentes de B llama al **LLM real** mediante el `LLMProvider` de A.

## Día 3 · Jira real y RAG real

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-14 | Consultas JQL: épicas, HU hijas, vínculos y búsqueda por texto, con `/search/jql` y `nextPageToken` | A | T-11 | RF-02, RF-14 | ⬜ |
| T-15 | Script de seed de Jira: 3–4 épicas y 10–15 HU sintéticas coherentes con el corpus | A | T-11, T-09 | D-06 | ⬜ |
| T-16 | Embeddings (bge-m3 u OpenAI), `PgVectorStore` híbrido con filtros e indexación del corpus | B | T-13, T-04 | RF-10, RF-11 | ⬜ |
| T-17 | Set de 10 preguntas con las fuentes esperadas y script de evaluación de la recuperación | B | T-16 | RNF-14, RNF-09 | ⬜ |

**🔗 Sincronización:** **Jira real + RAG real sustituyen a los fakes** en `core/container.py`.

## Día 4 · Primera HU real

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-18 | Servicio de contexto (nodo `retrieve_context`): Jira + RAG con presupuesto de tokens | A | T-14, T-16 | RF-11, RF-14 | ⬜ |
| T-19 | Versionado de HU (`artifact_versions`) y cálculo del diff por campo (`StoryDiff`) | A | T-05 | RF-05, RF-19, RNF-16 | ⬜ |
| T-20 | Prompts de HU nueva, de evolución y de revisión: salida estructurada, IDs de CA y RN, y citas | B | T-10, T-16 | RF-15, RF-16, RF-17, RF-18, RF-21 | ⬜ |

**🔗 Sincronización:** **generar la primera HU real** del piloto (por script o CLI) a partir de una necesidad y de una HU sembrada.

## Día 5 · Demo de los pasos 1–5

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-21 | Análisis de impacto: HU afectadas, reglas, dependencias y regresión (`ImpactAnalysis`) | A | T-18, T-19 | RF-19, RF-27 | ⬜ |
| T-22 | `LocalAuthProvider` (argon2), roles y 3 usuarios sintéticos de demo | A | T-04 | RF-45, RF-46, RNF-05 | ⬜ |
| T-23 | **Rediseño de la UI** (D-12): estructura de pestañas, flujo de navegación, estilo y estados vacíos/error, en `docs/specs/UI.md` | B | — | RNF-15 | ⬜ |
| T-24 | UI: login, pestañas **Contexto** e **Historia**, chat, selector de origen y selector de modelo | B | T-23, T-22 | RF-14, RF-20, RF-42 | ⬜ |

**🔗 Sincronización:** **demo interna de los pasos 1–5 de extremo a extremo** desde la UI.

## Día 6 · Control y QA

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-25 | Máquina de estados integrada en el grafo, `audit_log` y nodo `publish` protegido (modo simulación, sin escribir aún) | A | T-07, T-05 | RF-33, RF-34, RF-35 | ⬜ |
| T-26 | Prompts de casos de prueba y escenarios Gherkin, matriz de cobertura, datos sintéticos y riesgos | B | T-20 | RF-22, RF-23, RF-24, RF-25, RF-27 | ⬜ |

**🔗 Sincronización:** validación automática de que **cada CP referencia CA/RN existentes** y todo CA tiene al menos un CP.

## Día 7 · Escritura en Jira

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-27 | `markdown_to_adf`, `create_story`, `update_story` con comentario del diff y `link` | A | T-11, T-19 | RF-04, RF-05, RF-06 | ⬜ |
| T-28 | Estrategia de pruebas y pestaña **QA** | B | T-26, T-24 | RF-26 | ⬜ |
| T-29 | Página **Administración** mínima: probar conexiones, modelos por tarea y carga de documentos | B | T-24, T-12 | RF-01, RF-07, RF-40, RF-41 | ⬜ |

**🔗 Sincronización:** **aprobar un artefacto desde la UI** y publicar una HU real en el sandbox.

## Día 8 · Publicación completa

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-30 | `JiraNativeTests`: subtareas CP con etiquetas, adjuntos de estrategia y matriz, vínculos de impacto y `PublishResult` | A | T-27 | RF-30, RF-06, RNF-13 | ⬜ |
| T-31 | Pestaña **Revisión y publicación**: vista previa, diff visual, edición manual, aprobar/descartar y reintentar fallidos | B | T-25, T-24 | RF-31, RF-32, RNF-16 | ⬜ |

**🔗 Sincronización:** **publicación completa en el sandbox**: HU + subtareas CP + adjuntos + vínculos.

## Día 9 · Memoria y medición

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-32 | Contador de tokens y coste por llamada visible en la UI; endurecimiento: reintentos, mensajes de error y revisión de logs | A | T-10 | RF-43, RNF-12, RNF-02 | ⬜ |
| T-33 | `MemoryGenerator`, nodo `memorize`, reindexado sin duplicados, prioridad de la memoria en la búsqueda y pestaña **Memoria** | B | T-16, T-27 | RF-36, RF-37, RF-38, RF-51, RNF-25 | ⬜ |

**🔗 Sincronización:** **medir tokens** (RNF-11: memoria frente a HU completa) y los tiempos (RNF-09, RNF-10) → **congelar funcionalidades**.

## Día 10 · Cierre del MVP

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-34 | Prueba cruzada: la sesión A prueba el área B (con `test-writer` y `spec-checker`) | A | T-33 | RNF-19 | ⬜ |
| T-35 | Prueba cruzada: la sesión B prueba el área A | B | T-32 | RNF-19 | ⬜ |
| T-36 | README de instalación, ensayo de la demo y etiqueta `v1.0` | P | T-34, T-35 | — | ⬜ |

**🔗 Sincronización:** **demo v1.0** con los dos flujos completos (AF y QA).

---

## Días 11–15 · v1.1 y demo final

| ID | Tarea | Sesión | Trazabilidad | Estado |
|---|---|---|---|---|
| T-37 | Registro de ejecución por CP (transiciones de estado y comentario de evidencia) | A | RF-28 | ⛔ R-01 |
| T-38 | Propuesta de defecto vinculado ante un fallo | A | RF-29 | ⛔ R-01 |
| T-39 | Probar la aceleración iGPU con Vulkan y comparar calidad local frente a nube por tarea (Could) | A | RNF-07 | ⬜ |
| T-40 | Langfuse y panel de métricas por modelo y tarea | A/B | RNF-24 | ⬜ |
| T-41 | Lenguaje natural a JQL (solo lectura, validada) | A | RF-50 | ⬜ |
| T-42 | Ingesta automática desde carpeta | B | RF-49 | ⬜ |
| T-43 | Gestión de documentos: listar, eliminar y reindexar | B | RF-13 | ⬜ |
| T-44 | Evaluación ampliada (conjunto dorado de HU y CP) para fijar los modelos por tarea | B | RF-41, RNF-14 | ⬜ |
| T-45 | Historial de sesiones y artefactos (Could) | B | RF-47 | ⬜ |
| T-46 | Demo final, documentación y roadmap v2.0 (día 15) | P | — | ⬜ |

---

## Decisiones del día 1
| Fecha | Decisión |
|---|---|
| 2026-09-30 | Se ratifican las validaciones extra de `schemas/` (SPEC-00 §11) |
| 2026-09-30 | `Artifact` sigue mutable (sin `frozen`): la garantía está en `core/approvals.py` y `frozen` no impide `model_copy` |
| 2026-09-30 | Las 7 categorías del corpus (`documents.category`): `normativa`, `procesos`, `especificaciones`, `glosario`, `arquitectura`, `manuales`, `actas` (+ `memoria`, reservada al agente). Prompt de T-09 en `docs/prompts/PROMPT-02-corpus-area-b.md` |
| 2026-09-30 | T-04 queda ⛔ hasta que TI instale WSL; se continúa con el resto del plan |
| 2026-09-30 | **SPEC-00 congelada** (v1.2, anexo §11) y creación de los worktrees `area-a` y `area-b` |

## Propuestas adicionales detectadas durante el desarrollo
| ID | Propuesta | Origen (tarea) | Decisión |
|---|---|---|---|
| PA-01 | `Dockerfile` para el servicio `app` de `docker-compose.yml` (perfil `full`), que hoy hace `build: .` sin Dockerfile | T-04 | Pendiente |
| PA-02 | Job de CI con un servicio `pgvector/pgvector:pg16` que ejecute las pruebas `integration` de migraciones | T-04 | Pendiente |
| PA-03 | `audit_log` de solo inserción: trigger que rechace UPDATE/DELETE o `REVOKE` para el rol de la aplicación | T-04 | Pendiente |
| PA-05 | Publicación de QA idempotente: al reintentar tras un fallo parcial, `JiraNativeTests` (T-30) solo publica los CP fallidos y no duplica subtareas ya creadas (el fake actual republica la suite completa) | T-07 (revisión de seguridad) | Pendiente · T-30 |
| PA-06 | Persistir el registro de aprobaciones (`core/approvals.py`) en `audit_log` y tomar la identidad del revisor de la sesión autenticada | T-07 (revisión de seguridad) | Pendiente · T-25, T-22/T-24 |
| PA-04 | Política de conservación y seudonimización de nombres de usuario en `audit_log` (RGPD) | T-04 | Pendiente |
| PA-09 | Enum de categorías de documento en `schemas/` con los 7 slugs del corpus + `memoria`, y CHECK en `documents.category` (hoy texto libre, SPEC-00 §11) | T-09 | Pendiente (P) · T-12 |
| PA-07 | Groq gratuito limita a **8.000 tokens/min** por modelo (30 pet/min · 1.000 pet/día · 200.000 tokens/día con `gpt-oss-120b`): son 1–2 llamadas grandes por minuto. Fijar un presupuesto de contexto por tarea (fragmentos RAG + memoria) y hacer que el backoff ante 429 respete el límite por minuto. Estimación: 30–60k tokens por HU completa, unas 4–6 HU al día con el 120B. Fuente: console.groq.com/docs/rate-limits (sep-2026) | T-08 (investigación) | Pendiente · T-10 |
| PA-08 | Las cuotas de Groq son por modelo y por organización (varias claves no suman cuota). Repartir tareas en `config/models.yaml` para sumar bolsas: alta calidad en `gpt-oss-120b`, tareas medias (memoria `.md`) en `gpt-oss-20b`, tareas ligeras y embeddings (bge-m3) en Ollama. Opción en estudio: alojar Ollama en una VM de Azure (acceso por túnel SSH, sin exponer el puerto 11434), como embeddings y último respaldo de la cadena; si la VM no es gratuita, afecta a la D-14 y RNF-07 | T-08 (investigación) | Pendiente · T-08, T-10 |

## Registro diario
| Día | Fecha | Hecho | Hito de sincronización | Bloqueos | Plan de mañana |
|---|---|---|---|---|---|
| 1 | 2026-09-29 / 30 | T-01, T-02, T-03, T-05, T-06, T-07 ✅; T-04 ⛔ (migración verificada en SQL offline; falta `docker compose up` + `alembic upgrade head`: WSL no instalado). `adapters/errors.py` adelantado a T-05 por acuerdo. Añadidos acordados en T-06: `IssueLink` y protocolos `@runtime_checkable`. T-07: registro de aprobaciones `core/approvals.py` (huella de versión + operación, un solo uso, destino fijo entre iteraciones) tras 5 pasadas de `security-reviewer`; la reanudación con `approve` debe devolver la `fingerprint` del `interrupt`. Alcance adelantado en el esqueleto del grafo, a tener en cuenta: `retrieve_context` ya recorre épica, hermanas y vínculos (T-18 añade presupuesto de tokens); `publish` ya escribe comentario de diff y vínculos (T-25 debe añadir modo simulación y auditoría); `memorize` ya escribe `data/memory/<CLAVE>.md` y reindexa (T-33 lo sustituye por el generador real). Validaciones extra de `schemas/` pendientes de ratificar | SPEC-00 congelada (v1.2) y worktrees `area-a` / `area-b` creados | Elección de proveedores y modelos concretos pendiente (R-07, ligada a T-08): `config/models.yaml` se deja con su contenido actual y solo se valida su estructura; la app y las pruebas funcionan sin ninguna API key (los placeholders `TU_*` cuentan como ausentes). Docker Desktop sin WSL (y revisar licencia en equipo corporativo) | Verificar T-04 con Docker; sincronización del día 1 |
| 2 | 2026-09-30 | T-09 ✅ (B, rama `area-b`): corpus de Villaficticia con 22 documentos (normativa 4, procesos 3, especificaciones 3, glosario 2, arquitectura 3, manuales 3, actas 4), `README.md` con 4 épicas y 15 ideas de HU para T-15, y `tests/unit/test_corpus.py`. Coherente con `tests/fakes/dataset.py`: DEMO-1 épica de préstamo digital, DEMO-2 reservar, DEMO-3 renovar, DEMO-4 historial de 12 meses | — | — | T-12 (ingesta) y T-13 (fragmentación) |
