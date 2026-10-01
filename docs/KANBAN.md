# KANBAN · Agente de IA de AF y QA

**Estados:** ⬜ Backlog · 🔄 En curso · 👀 En revisión · ✅ Hecho · ⛔ Bloqueado
**Sesiones:** P = principal (`main`) · A = worktree `area-a` (Integraciones y núcleo) · B = worktree `area-b` (Conocimiento y UI) · Tú = tarea manual

> Regla: al empezar una tarea, cámbiala a 🔄; al terminarla y pasar `spec-checker` y `security-reviewer`, cámbiala a ✅. Cada día se cierra con su **punto de sincronización**: fusionar A y B en `main`, rebase de los worktrees y verificar el hito.

## Tablero resumen

| ⬜ Backlog | 🔄 En curso | 👀 En revisión | ✅ Hecho | ⛔ Bloqueado |
|---|---|---|---|---|
| T-08, T-24, T-27 … T-36, T-39 … T-48, T-53 | — | — | T-01 … T-26, T-49 … T-52 | T-37, T-38 (R-01) |

---

## Día 1 · Cimientos (P + Tú; B empieza el corpus)

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-01 | Repo, uv, `pyproject`, ruff, pytest y estructura de carpetas de la SPEC-00 | P | — | RNF-17, RNF-26 | ✅ |
| T-02 | Pre-commit con gitleaks y CI (ruff, pytest sin integración, gitleaks) | P | T-01 | RNF-01, CA-00-05 | ✅ |
| T-03 | `core/config.py` (pydantic-settings, SecretStr) y structlog con enmascarado | P | T-01 | RNF-01, RNF-02, RNF-23 | ✅ |
| T-04 | Docker Compose con pgvector, Alembic y migraciones de las tablas de la SPEC-00 §6 | P | T-01 | RNF-20, CA-00-06 | ✅ |
| T-05 | `schemas/` y `core/state_machine.py` con pruebas | P | T-01 | SPEC-00 §3, RF-34, CA-00-07 | ✅ |
| T-06 | `adapters/base.py`, `adapters/errors.py` y `tests/fakes/` para todos los protocolos | P | T-05 | SPEC-00 §4, CA-00-03 | ✅ |
| T-07 | Esqueleto del grafo LangGraph con fakes, `interrupt()` y reanudación | P | T-06 | CA-00-04 | ✅ |
| T-08 | Crear sitio Jira Cloud y proyecto de pruebas, verificar el tipo subtarea, token con scopes; crear cuentas gratuitas en Groq y OpenRouter; instalar Ollama y descargar bge-m3 y un modelo pequeño; fijar `config/models.yaml` | Tú | — | D-03, D-14, RNF-04 | ⬜ |
| T-09 | Corpus piloto sintético: dominio ficticio, 15–25 documentos Markdown en las 7 categorías | B | T-01 | D-06 | ✅ |

**🔗 Sincronización:** `CLAUDE.md`, contratos y fakes aprobados → **congelar la SPEC-00** → crear los worktrees `area-a` y `area-b`.

## Día 2 · Proveedores e ingesta

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-10 | `OpenAICompatibleProvider`, `FallbackLLMProvider` (429 → backoff → siguiente), router por tarea desde `models.yaml`, validación y reintento de salidas estructuradas, y registro en `llm_usage` | A | T-06, T-08 | RF-40 a RF-44, RNF-27, RNF-28 | ✅ |
| T-11 | `JiraCloudTracker` de lectura: `test_connection`, `get_issue` con `adf_to_text` y relaciones | A | T-06, T-08 | RF-01, RF-03 | ✅ |
| T-12 | Ingesta: carga, extracción con Docling, normalización y clasificación por categoría | B | T-06, T-09 | RF-07, RF-08, RF-12 | ✅ |
| T-13 | Fragmentación por encabezados + recursiva, con metadatos | B | T-12 | RF-09 | ✅ |

**🔗 Sincronización:** la clasificación de fuentes de B llama al **LLM real** mediante el `LLMProvider` de A.

## Día 3 · Jira real y RAG real

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-14 | Consultas JQL: épicas, HU hijas, vínculos y búsqueda por texto, con `/search/jql` y `nextPageToken` | A | T-11 | RF-02, RF-14 | ✅ |
| T-15 | Seed de Jira como CSV importable desde la interfaz (decisión del día 1): 3–4 épicas y 10–15 HU sintéticas coherentes con el corpus | A | T-11, T-09 | D-06 | ✅ |
| T-16 | Embeddings (bge-m3 u OpenAI), `PgVectorStore` híbrido con filtros e indexación del corpus | B | T-13, T-04 | RF-10, RF-11 | ✅ |
| T-17 | Set de 10 preguntas con las fuentes esperadas y script de evaluación de la recuperación | B | T-16 | RNF-14, RNF-09 | ✅ |

**🔗 Sincronización:** **Jira real + RAG real sustituyen a los fakes** en `core/container.py`.

## Día 4 · Primera HU real

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-18 | Servicio de contexto (nodo `retrieve_context`): Jira + RAG con presupuesto de tokens | A | T-14, T-16 | RF-11, RF-14 | ✅ |
| T-19 | Versionado de HU (`artifact_versions`) y cálculo del diff por campo (`StoryDiff`) | A | T-05 | RF-05, RF-19, RNF-16 | ✅ |
| T-20 | Prompts de HU nueva, de evolución y de revisión: salida estructurada, IDs de CA y RN, y citas | B | T-10, T-16 | RF-15, RF-16, RF-17, RF-18, RF-21 | ✅ |

**🔗 Sincronización:** **generar la primera HU real** del piloto (por script o CLI) a partir de una necesidad y de una HU sembrada.

## Día 5 · Demo de los pasos 1–5

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-21 | Análisis de impacto: HU afectadas, reglas, dependencias y regresión (`ImpactAnalysis`) | A | T-18, T-19 | RF-19, RF-27 | ✅ |
| T-22 | `LocalAuthProvider` (argon2), roles y 3 usuarios sintéticos de demo | A | T-04 | RF-45, RF-46, RNF-05 | ✅ |
| T-23 | **Rediseño de la UI** (D-12): «Propuesta mixta» (asistente con arranque guiado), pantallas, roles, aprobación, estados y animaciones, en `docs/specs/UI.md` | B | — | RNF-15 | ✅ |
| T-24 | UI «Propuesta mixta» (`docs/specs/UI.md`): login, marco común, Mixta 1 (inicio, selector de proyecto), 1b (elegir en Jira), 2 (origen fijado y fuentes), 2b (generando) y 3 (iterar con chat), y selector de modelo | B | T-23, T-22 | RF-14, RF-20, RF-42 | ⬜ |

**🔗 Sincronización:** **demo interna de los pasos 1–5 de extremo a extremo** desde la UI.

## Día 6 · Control y QA

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-25 | Máquina de estados integrada en el grafo, `audit_log` y nodo `publish` protegido (modo simulación, sin escribir aún) | A | T-07, T-05 | RF-33, RF-34, RF-35 | ✅ |
| T-26 | Prompts de casos de prueba y escenarios Gherkin, matriz de cobertura, datos sintéticos y riesgos | B | T-20 | RF-22, RF-23, RF-24, RF-25, RF-27 | ✅ |

**🔗 Sincronización:** validación automática de que **cada CP referencia CA/RN existentes** y todo CA tiene al menos un CP.

## Día 7 · Escritura en Jira

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-27 | `markdown_to_adf`, `create_story`, `update_story` con comentario del diff y `link` | A | T-11, T-19 | RF-04, RF-05, RF-06 | ⬜ |
| T-28 | Estrategia de pruebas y pantallas **QA 1 … QA 3** (origen, generando, iterar la suite con Casos, Cobertura, Datos y riesgos, y Estrategia) | B | T-26, T-24 | RF-26 | ⬜ |
| T-29 | Página **Administración** mínima: probar conexiones, modelos por tarea y carga de documentos | B | T-24, T-12 | RF-01, RF-07, RF-40, RF-41 | ⬜ |

**🔗 Sincronización:** **aprobar un artefacto desde la UI** y publicar una HU real en el sandbox.

## Día 8 · Publicación completa

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-30 | `JiraNativeTests`: subtareas CP con etiquetas, adjuntos de estrategia y matriz, vínculos de impacto y `PublishResult` | A | T-27 | RF-30, RF-06, RNF-13 | ⬜ |
| T-31 | **Recibo de aprobación y resultado** (Mixta 3 · recibo · Mixta 4 y QA 4 · QA 5): vista previa, diff visual, edición manual, aprobar/descartar y reintentar fallidos | B | T-25, T-24 | RF-31, RF-32, RNF-16 | ⬜ |

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

## Tareas añadidas el día 6

| ID | Tarea | Sesión | Depende | Trazabilidad | Estado |
|---|---|---|---|---|---|
| T-47 | Registro de la ejecución por caso: estado (Pasó, Falló, Bloqueado) y evidencia como comentario en la subtarea CP, con aprobación humana | A | T-30 | RF-28, R-01 (opción A) | ⬜ |
| T-48 | Flujo **Revisar una HU**: análisis de calidad (INVEST, ambigüedades, CA sin fuente) de una HU de Jira con `StoryWriter.review`, sin publicar | A | T-21, T-25 | RF-18 | ⬜ |
| T-49 | Categorías del RAG de la presentación: `CATEGORIES`, prompt de clasificación, metadatos del corpus y reindexado | B | T-12 | RF-12 | ✅ |
| T-50 | Proyecto en la conversación: `project_key` en `Origin` y `PublishTarget` (lo aprobado es lo publicado), validación de claves escritas, último proyecto por usuario y `create_story(story, epic_key, project)` (cambio de contrato, antes de T-27) | P | T-25 | RF-02, RF-04, RF-14 | ✅ |
| T-51 | Contrato de revisión para la UI: fuentes excluidas en el estado inicial, `plan` de operaciones de Jira en el payload de `human_review` y decisión `edit` (contenido editado → versión nueva con su huella) | P | T-25 | RF-21, RF-31, RF-32 | ✅ |
| T-52 | Conversaciones persistentes: checkpointer en PostgreSQL con el serializador de tipos explícitos y listado de conversaciones por usuario (proyecto, flujo, estado) | A | T-25 | RF-20, RF-47 | ✅ |
| T-53 | Arranque guiado sin IA: reconocimiento de claves de Jira en el texto y propuesta de HU parecida por búsqueda de texto (`ContextService`), antes de arrancar el grafo | A | T-50 | RF-14, RF-19 | ⬜ |

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
| 2026-09-30 | T-15 se entrega como CSV importable desde la interfaz de Jira Cloud (`data/seed/jira/seed-villaficticia.csv`); la importación la hace el usuario. Prompt en `docs/prompts/PROMPT-03-seed-jira-csv.md` |
| 2026-09-30 | T-04 queda ⛔ hasta que TI instale WSL; se continúa con el resto del plan |
| 2026-09-30 | T-04 ✅: `docker compose up -d db` + `alembic upgrade head` verificados (pgvector 0.8.6, 7 tablas, `vector(1024)`, índices HNSW y GIN); prueba de integración en verde |
| 2026-09-30 | Rama `Dia2` (T-10…T-13) fusionada en `main`: PA renumeradas (PA-12…PA-18), `.env.example` vuelve a `TU_*`, claves de Jira con `fullmatch` (PA-18) y `test_connection` con `/project/search` (el token solo tiene `read:jira-work`/`write:jira-work`, RNF-04). Verificado en real: Jira (17 incidencias del seed, `get_issue` con padre, vínculos y ADF), LLM (clasificación `classify_source`) y Ollama `bge-m3` en Docker |
| 2026-09-30 | Skill `/tarea` (`.claude/skills/tarea/`) versionada para todas las sesiones |
| 2026-09-30 | **SPEC-00 congelada** (v1.2, anexo §11) y creación de los worktrees `area-a` y `area-b` |

## Decisiones del día 4
| Fecha | Decisión |
|---|---|
| 2026-09-30 | Nueva rama de integración **`PreProduccion`** (desde `main` en `143cc4e`). Todo el trabajo se fusiona en ella por PR; `main` queda como referencia estable hasta nueva decisión |
| 2026-09-30 | Rama `Dia4` (T-19, T-20) fusionada en `PreProduccion`: PA del compañero renumeradas a PA-30…PA-34 (PA-32 ya resuelta en T-18); anexo §11 admite persistencia del núcleo en sus propias tablas (`core/impact/versions.py`); prompts de evolución y revisión v2 con la regla anti-instrucciones; verificado en real (LLM + RAG) |
| 2026-09-30 | **SPEC-00 v1.3**: `IssueTracker.list_projects()` y `ProjectSummary` (RF-02, navegación §6.1), aprobado por el usuario |
| 2026-09-30 | Reparto del día 4: el compañero hace **T-20** y **T-19** en la rama `Dia4` (PR contra `PreProduccion`, prompt en `docs/prompts/PROMPT-04-dia4-companero.md`); la sesión principal hace **T-14 → T-18 → T-22** en `PreProduccion`. Las nuevas propuestas adicionales se numeran desde PA-23 |

## Decisiones del día 5
| Fecha | Decisión |
|---|---|
| 2026-09-30 | **Primera evolución de una HU de Jira (PA-30, opción 2):** la incidencia de Jira se estructura primero como `UserStory` con el LLM, para tener diff por campo desde la primera versión (RF-05, RNF-16) |
| 2026-09-30 | **R-07 cerrada** (decisión del usuario): cadenas de `config/models.yaml` con los modelos gratuitos disponibles — pesadas `groq gpt-oss-120b → groq qwen3.8-27b → openrouter qwen3.8-27b:free`; medias `groq gpt-oss-20b → groq qwen3.8-27b → openrouter gemma-4-31b-it:free`; ligeras `groq gpt-oss-20b → openrouter gemma-4-26b-a4b-it:free`; Ollama solo para embeddings (R-08). Posible cambio futuro a modelos corporativos (Foundry): solo se toca `models.yaml` y el `.env`. Las pruebas usan `tests/fixtures/models.yaml` y no dependen de los modelos reales |
| 2026-09-30 | Reparto del día 5: el compañero hace **T-26** y **T-23** en la rama `Dia5` (PR contra `PreProduccion`, prompt en `docs/prompts/PROMPT-05-dia5-companero.md`); la sesión principal conecta T-20 al grafo (PA-30) y sigue con **T-21 → T-25**. Rangos de propuestas: principal PA-35…PA-59, compañero desde PA-60 |

## Decisiones del día 6
| Fecha | Decisión |
|---|---|
| 2026-10-01 | Revisión de la presentación del proyecto (P1 · Agente AI · QA) frente al alcance: flujo de 8 pasos, plantilla de HU, campos de la memoria y capacidades de QA ya coinciden |
| 2026-10-01 | **R-01 cerrada · opción A:** basta con registrar el resultado de la ejecución por caso (estado y evidencia en la subtarea de Jira). RF-28 entra en el MVP (la presentación lista la ejecución como salida); RF-29 (defectos) queda fuera → **T-47** |
| 2026-10-01 | "Plan de pruebas" = estrategia de pruebas (RF-26); no hay documento aparte |
| 2026-10-01 | **D-07 se mantiene:** sin memoria de los artefactos de QA en el MVP |
| 2026-10-01 | **Categorías del RAG alineadas con la presentación** (diapositiva 4): productos y servicios, procesos de negocio, políticas y reglas operativas, documentación funcional y técnica, glosarios y criterios internos, HU y artefactos previos, estrategias y casos de prueba. Revisar el impacto en el par norma ↔ acta y en el corpus → **T-49** (área B) |
| 2026-10-01 | **Revisar y mejorar una HU es un flujo propio** (sin evolucionarla ni publicarla por defecto) → **T-48** |
| 2026-10-01 | **UI: «Propuesta mixta»** (lienzo de diseño, página «Propuesta mixta»: https://claude.ai/artifact/PK7Mfx3z357t1x7e2hsSbB). Asistente conversacional por fuera con **arranque guiado** por dentro: cuatro flujos (nueva necesidad, evolucionar HU, revisar la calidad, preparar pruebas), el modelo **no** pregunta para recoger datos (búsqueda de HU parecida en Jira por texto, sin IA), la operación queda fijada antes de generar, las fuentes se pueden desmarcar, la conversación sirve para iterar (RF-20), recibo de aprobación por operaciones, resultado simulado o real, flujo de QA con matriz, recibo, publicación parcial y registro de la ejecución. Animaciones de la Q (fase, carga por procesos, escritura y publicación). Sustituye al modelo de pestañas de T-23 → anexo `docs/prompts/PROMPT-05b-anexo-companero.md` |
| 2026-10-01 | **Proyecto de Jira por conversación:** se elige al empezar (todos los proyectos que ve la conexión, `list_projects`), viene preseleccionado el último usado y queda fijo en la conversación; una clave de otro proyecto lo cambia sola. Sin lista de proyectos permitidos en Ajustes → **T-50** |
| 2026-10-01 | Backend necesario para la UI → **T-50 … T-53** (sesión principal); la conversación libre para recoger datos queda como propuesta para v2 (PA-43) |

## Propuestas adicionales detectadas durante el desarrollo
| ID | Propuesta | Origen (tarea) | Decisión |
|---|---|---|---|
| PA-01 | `Dockerfile` para el servicio `app` de `docker-compose.yml` (perfil `full`), que hoy hace `build: .` sin Dockerfile | T-04 | Pendiente |
| PA-02 | Job de CI con un servicio `pgvector/pgvector:pg16` que ejecute las pruebas `integration` de migraciones | T-04 | Pendiente |
| PA-03 | `audit_log` de solo inserción: trigger que rechace UPDATE/DELETE o `REVOKE` para el rol de la aplicación | T-04 | Pendiente |
| PA-05 | Publicación de QA idempotente: al reintentar tras un fallo parcial, `JiraNativeTests` (T-30) solo publica los CP fallidos y no duplica subtareas ya creadas (el fake actual republica la suite completa) | T-07 (revisión de seguridad) | Pendiente · T-30 |
| PA-06 | Persistir el registro de aprobaciones (`core/approvals.py`) en `audit_log` y tomar la identidad del revisor de la sesión autenticada | T-07 (revisión de seguridad) | Parcial: persistido en `artifact_state` (T-25); falta la identidad del revisor desde la sesión (T-31) |
| PA-04 | Política de conservación y seudonimización de nombres de usuario en `audit_log` (RGPD) | T-04 | Pendiente |
| PA-09 | Enum de categorías de documento en `schemas/` con los 7 slugs del corpus + `memoria`, y CHECK en `documents.category` (hoy texto libre, SPEC-00 §11) | T-09 | Pendiente (P) · T-12 |
| PA-07 | Groq gratuito limita a **8.000 tokens/min** por modelo (30 pet/min · 1.000 pet/día · 200.000 tokens/día con `gpt-oss-120b`): son 1–2 llamadas grandes por minuto. Fijar un presupuesto de contexto por tarea (fragmentos RAG + memoria) y hacer que el backoff ante 429 respete el límite por minuto. Estimación: 30–60k tokens por HU completa, unas 4–6 HU al día con el 120B. Fuente: console.groq.com/docs/rate-limits (sep-2026) | T-08 (investigación) | ✅ Resuelta en T-18 (`core/context/budget.py`, 6000 tokens por petición) |
| PA-08 | Las cuotas de Groq son por modelo y por organización (varias claves no suman cuota). Repartir tareas en `config/models.yaml` para sumar bolsas: alta calidad en `gpt-oss-120b`, tareas medias (memoria `.md`) en `gpt-oss-20b`, tareas ligeras y embeddings (bge-m3) en Ollama. Opción en estudio: alojar Ollama en una VM de Azure (acceso por túnel SSH, sin exponer el puerto 11434), como embeddings y último respaldo de la cadena; si la VM no es gratuita, afecta a la D-14 y RNF-07 | T-08 (investigación) | Pendiente · T-08, T-10 |
| PA-10 | Excluir `data/seed/jira/` de la ingesta del RAG (T-12): su README revela la calidad prevista de cada HU del seed y daría pistas al agente en la revisión (RF-18). (La alineación con el corpus de T-09 ya se verificó al integrar.) | T-15 | ✅ Resuelta: el indexador solo recorre `data/seed/corpus` y excluye `README.md` |
| PA-11 | `PgVectorStore.upsert`: si un `chunk.id` ya existente llega con otro `(document_id, ordinal)`, choca con la clave primaria (sale como `ExternalServiceError`). Decidir si se mueve el fragmento o se rechaza con un error claro | T-16 | Pendiente · T-13 |
| PA-12 | Mover a `schemas/` la salida estructurada `SourceClassification` y las 7 categorías (hoy provisionales en `core/rag/documents.py`), junto con el enum de PA-09 | T-12 | Pendiente (P) · sincronización |
| PA-13 | Fusionar con la siguiente las secciones que solo tienen el título (29 de 248 chunks del corpus bajan de 15 tokens) para reducir ruido en la recuperación | T-13 (spec-checker) | Pendiente · T-16/T-17 |
| PA-14 | Excluir `integration` por defecto en `addopts` de `pyproject.toml` (hoy `uv run pytest` sin `-m` ejecuta la prueba de PDF, que descarga modelos de Docling; ahora exige `RUN_DOCLING_MODELS=1`) | T-12 (revisión de seguridad) | Pendiente (P) |
| PA-15 | Añadir `StructuredOutputError` a `adapters/errors.py` (hoy en `adapters/llm/openai_compatible.py`) para que `core/` pueda capturarla sin importar una implementación | T-10 (spec-checker) | Pendiente (P) |
| PA-16 | Desactivar JSON Schema solo ante un 400 debido a `response_format`, no ante cualquier 400 (p. ej. contexto demasiado largo) | T-10 (spec-checker) | Pendiente · T-32 |
| PA-17 | Recoger en el anexo §11 de la SPEC-00 `core/factories.py` (composición de adaptadores reales a partir de la configuración; `adapters/` no importa `core/`) | T-10/T-11 | ✅ Hecha al integrar el día 2 (anexo §11) |
| PA-18 | Validar las claves de Jira con `fullmatch` en `core/graph/nodes.py` (hoy `.match`: acepta una clave con un salto de línea final, que se usa en la ruta de la memoria) | T-11 (test-writer) | ✅ Hecha al integrar el día 2 |
| PA-19 | Mover el cargador de prompts (`core/rag/prompts.load_prompt`) a un módulo compartido (`core/prompts.py`, principal): hoy `core/factories.py` depende de un módulo del área B | Integración día 2 (spec-checker) | Pendiente (P) |
| PA-20 | Exigir `https://` en los proveedores LLM con clave (hoy solo Ollama local usa `http`) | Integración día 2 (security-reviewer) | Pendiente (P) |
| PA-21 | Ingesta: `ingest(path)` sin raíz ni control de symlinks, delimitadores `<documento>`/`<titulo>` sin neutralizar, `source_path` absoluto (puede llevar el usuario del equipo) y sin límite de páginas/tiempo en Docling; revisar antes de la carga desde la UI | Integración día 2 (security-reviewer) | Pendiente · T-29 |
| PA-22 | RGPD: `adf_to_text` pasa al LLM el texto de las menciones `@Nombre`; sustituirlas por un marcador cuando haya datos reales | Integración día 2 (spec-checker) | Pendiente · v2.0 |
| PA-23 | RF-02 «listar proyectos»: el protocolo congelado `IssueTracker` no tiene `list_projects`; el MVP trabaja con un único proyecto (`JIRA_PROJECT_KEY`). Decidir si se añade al contrato (navegación Proyecto → Épica → HU de §6.1) | T-14 | ✅ Hecha: `list_projects` añadido al contrato (SPEC-00 v1.3) |
| PA-24 | Contexto: `list_children` pagina hasta 1000 hermanas/hijas antes de aplicar el presupuesto; acotar con una búsqueda limitada si los proyectos crecen | T-18 (security-reviewer) | Pendiente |
| PA-25 | Que el nodo `publish` y la UI exijan también `require(user, PUBLISH_STORY/PUBLISH_TESTS)` además de la aprobación registrada (el permiso complementa la aprobación humana) | T-22 (security-reviewer) | Pendiente · T-31 (el grafo no conoce el rol del usuario) |
| PA-26 | Limitar los intentos de login por usuario/IP con backoff progresivo | T-22 (security-reviewer) | Pendiente · T-24 |
| PA-27 | Auditar logins correctos y fallidos en `audit_log` (sin contraseña ni hash) | T-22 (security-reviewer) | Pendiente · T-24/T-31 (requiere cambio de contrato: `audit_log.artifact_id` y `AuditAction`) |
| PA-28 | `AuthorizationError` (403) en `adapters/errors.py` para `require`, distinto de `AuthenticationError` | T-22 (security-reviewer) | Pendiente (P) |
| PA-29 | Impedir `core.seed_users` fuera de `APP_ENV=development` (reinicia las contraseñas demo) | T-22 (security-reviewer) | Pendiente |
| PA-30 | Conectar `core/functional/writer.StoryWriter` (con `StoryContext` construido desde el estado) al nodo `generate` de `core/graph/nodes.py`, sustituyendo `_context_json`, y guardar `prompt_version` en el `Artifact` | T-20 | ✅ Hecha: `generate` usa `StoryWriter` (decisión del día 5, opción 2) |
| PA-31 | RGPD: minimizar lo que se envía al LLM desde Jira (hoy `_jira_source` incluye descripción y todos los comentarios); filtrar o seudonimizar comentarios cuando haya datos reales | T-20 (security-reviewer) | Pendiente · antes de usar datos reales (T-24/v2.0) |
| PA-32 | Hallazgo de T-17: cuando un acta cambia una regla, asegurar en la recuperación que llegan ambos documentos (p. ej. ampliar con los `related` del fragmento) para que el prompt pueda aplicar la regla de la fecha más reciente | T-20 (spec-checker) | ✅ Resuelta en T-18 (`ContextService` añade la norma ↔ acta por `metadata[\"related\"]`) |
| PA-33 | Usar `core/impact/diff.diff_stories` para rellenar `ImpactAnalysis.diffs` en el nodo `generate` (hoy los genera el LLM) y guardar cada versión con `StoryVersionStore.save` | T-19 | ✅ Hecha: `diffs` de `diff_stories` y cada versión guardada con `versions.save` (T-25) |
| PA-34 | `StoryVersionStore.save`: rechazar que un id existente cambie de `type` (hoy la fila se actualiza y las versiones anteriores se leerían con otro modelo); y una excepción específica para «diff no disponible» (hoy `NotFoundError`), que requiere tocar `adapters/errors.py` | T-19 (spec-checker) | Pendiente (P) |
| PA-35 | `TaskType.STRUCTURE_STORY` en la próxima revisión del contrato (hoy `structure` reutiliza `EVOLVE_STORY`) | PA-30 (spec-checker) | Pendiente (P) |
| PA-36 | Contrastar la versión estructurada de Jira con el `summary`/`description` reales y avisar en la UI de que el diff es frente a la «versión estructurada de Jira» (un texto malicioso en Jira podría disimular cambios) | PA-30 (security-reviewer) | Pendiente · T-31 (la parte de T-21 no aplica: el diff ya es determinista) |
| PA-37 | Persistir la versión de partida (hoy en memoria en `GraphNodes`) junto con las versiones (`artifact_versions`) | PA-30 | ✅ Hecha en T-25: en `artifact_state.state["baseline"]` |
| PA-38 | En la publicación de una evolución, excluir también la épica de los vínculos de impacto (hoy solo se excluye de las candidatas si la HU de origen está en `jira_context`) | T-21 (security-reviewer) | ✅ Hecha en T-25 |
| PA-39 | Limitar la longitud de `ImpactItem.reason` (se publica como comentario del vínculo) | T-21 (security-reviewer) | Pendiente (P) · revisión del contrato |
| PA-40 | Firmar (HMAC con clave del `.env`) el registro de aprobaciones de `artifact_state`: hoy quien pueda escribir en la tabla puede fabricar una aprobación | T-25 (security-reviewer) | Pendiente (P) |
| PA-41 | Caducidad de la aprobación que queda vigente tras una publicación simulada (hoy no caduca al pasar a `live`) | T-25 (security-reviewer) | Pendiente (P) |
| PA-42 | Que `tests/pg_temp.py` solo cree bases temporales en un host local (evitar un servidor compartido) | T-25 (security-reviewer) | Pendiente (P) |
| PA-43 | Conversación libre para recoger los datos (el asistente pregunta con el LLM, variante «Asistente 2» del lienzo) | Día 6 (UI) | Pendiente · v2 |
| PA-44 | Las animaciones de la UI (Q de fase, de carga y de escritura) se hacen en Streamlit con SVG y CSS en `st.html`/componentes; si alguna no es viable, se sustituye por un estado estático equivalente | Día 6 (UI) | Pendiente · T-24 |
| PA-45 | Una sola fuente para los patrones de clave de proyecto e incidencia: hoy están en `core/projects.py`, `core/context/jql.py` y `adapters/jira/jql.py` (el adaptador no puede importar `core/`; candidato a `schemas/` o `adapters/base.py`) | T-50 (security-reviewer) | Pendiente (P) |
| PA-46 | En `JiraCloudTracker.create_story` (T-27), comprobar que la clave devuelta por Jira pertenece al `project` pedido y, si no, fallar con `PublishError` | T-50 (security-reviewer) | Pendiente · T-27 |
| PA-47 | Cuando una clave de otro proyecto cambia el proyecto de la conversación, avisarlo en la UI y recordarlo como último usado (`ProjectService.choose`) | T-50 (spec-checker) | Pendiente · T-23, T-53 |
| PA-48 | Añadir `core/projects.py` a la tabla de propiedad de directorios de `CLAUDE.md` | T-50 (spec-checker) | Pendiente (P) |
| PA-49 | Escapar el contenido editado a mano al generar Markdown/ADF para Jira: `\|` y saltos de línea en la tabla del diff, y enlaces solo `http(s)` en `markdown_to_adf` | T-51 (security-reviewer) | Pendiente · T-27 |
| PA-50 | Auditar qué campos cambió una edición manual y avisar en la UI de que `synthetic_data` de una suite debe ser ficticio | T-51 (security-reviewer) | Pendiente · T-23 |
| PA-51 | Idempotencia de la auditoría de una edición si el proceso cae antes de guardar el checkpoint (hoy se repetiría `iterate` con `edited=true`) | T-51 (security-reviewer) | Pendiente · T-52 |
| PA-52 | Si el plan de la revisión no se puede calcular (operación incoherente), mostrar el error y permitir solo `discard` en vez de fallar antes de la pausa | T-51 (security-reviewer) | Pendiente |
| PA-53 | Estrechar el par norma ↔ acta a las actas (p. ej. `doc_type: acta` en la cabecera, llevado a `metadata`): con `politicas ↔ documentacion`, un documento técnico recuperado también trae las normas de su `related` (máx. 4 extra; el presupuesto recorta). Medido con el índice real: la consulta de renovaciones pasa de 6 a 10 fuentes antes del presupuesto | PA-69 | Pendiente (A) |
| PA-54 | Retención y borrado de conversaciones (derecho de supresión, RGPD): los checkpoints guardan en claro el texto de la necesidad y el contexto de Jira; política de conservación, borrado por usuario de `conversations` y `checkpoint*` y, si hace falta, `EncryptedSerializer` | T-52 (security-reviewer) | Pendiente (P) |
| PA-60 | Mover `fill_placeholders` y `PromptLoader` de `core/functional/writer.py` a un módulo común de prompts (junto a PA-19): hoy `core/qa/writer.py` los importa y un cambio de firma en la sesión principal lo rompería | T-26 (spec-checker) | Pendiente (P) |
| PA-61 | Conectar `core/qa/writer.TestWriter` al nodo `generate` en modo QA y guardar `prompt_version`; mostrar la matriz (`SuiteDraft.coverage_md`) y la estrategia en la pestaña QA (T-28) | T-26 | ✅ Hecha (P): QA del grafo con `TestWriter`; mostrar la matriz (`suite.coverage_md()`) y la estrategia pasa a T-28 |
| PA-62 | Permiso para el **Historial** en `core/permissions.py` (hoy no existe ninguno; la UI mixta lo muestra al administrador). Decidir si el analista y QA ven también su propio historial | T-23 | Pendiente (P) · T-45 |
| PA-63 | Acción «Pedir sus pruebas a QA» en el resultado real de una HU (Mixta 4): no hay backend de avisos ni asignación entre roles | T-23 | Pendiente · v2 |
| PA-64 | «Descargar informe» de Revisar la calidad (Mixta 5) como `.md` con `st.download_button` | T-23 | Pendiente · T-48 |
| PA-65 | «Guardar borrador» del registro de la ejecución (QA 6): persistir el borrador antes de aprobar | T-23 | Pendiente · T-47 |
| PA-66 | Eventos de progreso dentro del nodo `generate` (escribir, validar citas y diff, impacto) para que la Q de carga avance un cuarto por proceso real; hoy `graph.stream` solo distingue nodos | T-23 (spec-checker) | Pendiente (A) · T-24 |
| PA-67 | Exponer el motivo del cambio de proveedor en la cadena (p. ej. límite de Groq → respaldo) para el aviso de la UI; hoy solo se conoce el proveedor y el modelo usados | T-23 (spec-checker) | Pendiente (A) · T-32 |
| PA-68 | Actualizar las descripciones de T-23 y T-24 en el Kanban: siguen hablando de «pestañas» y la UI decidida es la «Propuesta mixta» (`docs/specs/UI.md`) | T-23 (spec-checker) | ✅ Hecha al fusionar `Dia5` (también T-28 y T-31) |
| PA-69 | **Par norma ↔ acta con las categorías de T-49:** cambiar `RELATED_PAIRS` en `core/context/service.py:25` a `{"politicas": "documentacion", "documentacion": "politicas"}` (las normas están en `politicas` y las actas en `documentacion`) y sus pruebas. Hasta aplicarlo, en real `ContextService` **no añade** el acta de una norma recuperada (ni al revés). Alternativa más estrecha: marcar las actas con `metadata["doc_type"] = "acta"` en la cabecera y filtrar por ese campo | T-49 | ✅ Hecha al fusionar `Dia5` (P): `RELATED_PAIRS = {politicas ↔ documentacion}` |
| PA-70 | Preguntas de evaluación de recuperación para las categorías nuevas `productos`, `historias` y `pruebas` (DOC-23 … DOC-28); hoy el conjunto solo cubre 4 de las 7. Cambia la línea base (Recall@6 0,90 · MRR 0,95) | T-49 (test-writer) | Pendiente (B) · T-44 |
| PA-71 | Alinear `tests/fakes/dataset.py` con las categorías de T-49 (usa `normativa` y `glosario`): un filtro por categoría con los slugs nuevos no encontraría esos documentos | T-49 (test-writer) | ✅ Hecha al fusionar `Dia5` (P): `politicas` y `glosarios` en el dataset y en las pruebas del par |

## Registro diario
| Día | Fecha | Hecho | Hito de sincronización | Bloqueos | Plan de mañana |
|---|---|---|---|---|---|
| 1 | 2026-09-29 / 30 | T-01, T-02, T-03, T-05, T-06, T-07 ✅; T-04 ⛔ (migración verificada en SQL offline; falta `docker compose up` + `alembic upgrade head`: WSL no instalado). `adapters/errors.py` adelantado a T-05 por acuerdo. Añadidos acordados en T-06: `IssueLink` y protocolos `@runtime_checkable`. T-07: registro de aprobaciones `core/approvals.py` (huella de versión + operación, un solo uso, destino fijo entre iteraciones) tras 5 pasadas de `security-reviewer`; la reanudación con `approve` debe devolver la `fingerprint` del `interrupt`. Alcance adelantado en el esqueleto del grafo, a tener en cuenta: `retrieve_context` ya recorre épica, hermanas y vínculos (T-18 añade presupuesto de tokens); `publish` ya escribe comentario de diff y vínculos (T-25 debe añadir modo simulación y auditoría); `memorize` ya escribe `data/memory/<CLAVE>.md` y reindexa (T-33 lo sustituye por el generador real). Validaciones extra de `schemas/` pendientes de ratificar | SPEC-00 congelada (v1.2) y worktrees `area-a` / `area-b` creados | Elección de proveedores y modelos concretos pendiente (R-07, ligada a T-08): `config/models.yaml` se deja con su contenido actual y solo se valida su estructura; la app y las pruebas funcionan sin ninguna API key (los placeholders `TU_*` cuentan como ausentes). Docker Desktop sin WSL (y revisar licencia en equipo corporativo) | Verificar T-04 con Docker; sincronización del día 1 |
| 2 | 2026-09-30 | T-09 ✅ (B, rama `area-b`): corpus de Villaficticia con 22 documentos (normativa 4, procesos 3, especificaciones 3, glosario 2, arquitectura 3, manuales 3, actas 4), `README.md` con 4 épicas y 15 ideas de HU para T-15, y `tests/unit/test_corpus.py`. Coherente con `tests/fakes/dataset.py`: DEMO-1 épica de préstamo digital, DEMO-2 reservar, DEMO-3 renovar, DEMO-4 historial de 12 meses | — | — | T-12 (ingesta) y T-13 (fragmentación) |
| 2 | 2026-09-30 | T-12 👀 y T-13 ✅ (B, rama `area-b`): ingesta de PDF/DOCX/MD/TXT con Docling, normalización y clasificación (cabecera YAML o LLM con `SourceClassification`, provisional en `core/rag`, PA-12), prompt `prompts/classify_source.md`; fragmentación por encabezados + recursiva con solapamiento, tokens estimados como ceil(caracteres/4). El corpus da 22 documentos y 248 chunks (máx. 418 tokens). La prueba real de PDF es `integration` y exige `RUN_DOCLING_MODELS=1` | — | T-12: clasificación con el LLM real pendiente de T-08/T-10. `Ingestor` rechaza `memoria`: las memorias (RF-38) necesitarán su propio camino de indexado. gitleaks bloqueado en este equipo por una directiva de Windows | T-16 (embeddings e indexación), T-17 |
| 2 | 2026-09-30 | T-10 👀 y T-11 👀 (A, rama `area-a`): `OpenAICompatibleProvider` (429 con retry-after y umbral, JSON Schema o modo JSON, validación y un reintento), `FallbackLLMProvider` con registro en `llm_usage` (`SqlUsageRecorder`; est_cost 0, D-14), `ModelRouter` con override de sesión (RF-42); `JiraCloudTracker` de lectura (`/project/search`, `get_issue` con ADF → texto y relaciones, https obligatorio, reintentos solo en lecturas). Decisión: `adapters/` no importa `core/`; la composición desde la configuración está en `core/factories.py` (PA-17). Los textos de apoyo a la salida estructurada están en `prompts/structured_*.md` | Día 2: fusión de `area-b` y `area-a` en `Dia2` | Ambas en 👀 hasta probarlas con credenciales reales (T-08). `llm_usage` probado con SQLite; PostgreSQL pendiente de T-04 | Cablear `core/factories.py` en `core/container.py` (día 3) |
| 3 (adelantado) | 2026-09-30 | T-15 ✅ (área A): `data/seed/jira/seed-villaficticia.csv` con 4 épicas y 13 HU (7 completas, 3 incompletas y 3 ambiguas a propósito) y 6 vínculos «relates to»; README con la importación y el mapeo; `tests/unit/test_seed_jira_csv.py`. Sin subtareas CP (D-09). Temas de épica y reglas añadidas (aviso 3 días antes, 1 día de suspensión por día de retraso, edad mínima de 14 años) verificados contra el corpus de T-09 al integrar en `main`; CA-03 de HU-01 alineado con RN-RES-05 (48 h desde que el ejemplar queda bloqueado). **La importación real en Jira la hace el usuario desde el navegador**; el agente no llama a la API | — | Importación pendiente de T-08 (sitio y proyecto de pruebas) | Importar el CSV en el sandbox cuando exista y verificar claves `DEMO-1`…`DEMO-4` |
| 3 | 2026-09-30 | T-04 ✅ (Docker + migraciones verificados), T-09 y T-15 integrados en `main`. **T-16 🔄 (parcial, hecha desde P por decisión del usuario):** `adapters/embeddings/ollama.py` (`OllamaEmbeddings`, SDK openai contra Ollama; sin `OpenAIEmbeddings` por D-14) y `adapters/vectorstore/pgvector.py` (`PgVectorStore`: híbrida vector + `tsvector` con RRF k=60, filtros `metadata @>`, `memory_boost`, una colección por `embedding_model`). Contrato para la ingesta (T-12/T-13): cada `Chunk` lleva en `metadata` `category` (obligatoria), `title`, `source_path`, `related_key`, `content_hash`, `doc_id` (`DOC-NN`, lo usa T-17) y `date` (RF-10, pendiente de definir en T-13); los ids de texto se convierten a UUID con `uuid5` y `upsert` crea la fila de `documents`; claves `_chunk_id` y `_document_id` reservadas. Reindexar = `delete_by_document` + `upsert`. **T-17 🔄:** `eval/retrieval_questions.yaml` (10 preguntas, 7 categorías, 3 con acta que cambia una regla) y `eval/retrieval_eval.py` (recall@k, MRR, latencia máx. frente a RNF-09). Falta para cerrar ambas: indexar el corpus (T-13), ejecutar T-17 contra `PgVectorStore` y la prueba real de bge-m3 | — | Ollama no instalado (T-08) · rama del día 2 pendiente | Fusionar día 2; indexar corpus; cerrar T-16/T-17; T-14 |
| 3 | 2026-09-30 | **T-16 ✅ y T-17 ✅** (desde P por decisión del usuario): `core/rag/indexing.py` (`CorpusIndexer` + CLI `uv run python -m core.rag.indexing`) une T-12/T-13 con `OllamaEmbeddings` y `PgVectorStore`; completa la metadata (`source_path` y `source` relativos, `content_hash`, `doc_id`, `classified_by`, `ingested_at`; `date` es la de la cabecera) y vectoriza título · sección + contenido. Indexación real: **22 documentos, 248 fragmentos**, 7 categorías (≈3 min con bge-m3 en CPU, Ollama en Docker, perfil `local-llm`). Evaluación real (`uv run python -m eval.retrieval_eval`, k=6): **Recall@6 0,90, MRR 0,95, latencia máx. ≈0,5 s** (RNF-09 ✅). Fallos: preguntas cuya regla cambió un acta (Q-01 no recupera DOC-19; Q-02 no recupera DOC-03) → tenerlo en cuenta en T-18. Fábricas `build_embeddings`/`build_vector_store` en `core/factories.py` | Día 3 cerrado salvo T-14 | — | T-14 (JQL), luego día 4 (T-18, T-19, T-20) |
| 4 | 2026-09-30 | **T-14 ✅** (P, rama `PreProduccion`): `JiraCloudTracker.search` paginado con `nextPageToken`/`isLast` por `/rest/api/3/search/jql` (páginas de 100, tope 1000), `list_epics` con `hierarchyLevel = 1` (no depende del idioma: en el sitio de pruebas las HU son «Historia»), `list_children` con `parent = CLAVE`; `core/context/jql.py` con `text_search_jql` (escapado Lucene + JQL) y `linked_issues_jql` para T-18. Verificado en Jira real (4 épicas, 4 HU de préstamo digital, 17 incidencias en varias páginas). Nota para T-18: el índice de búsqueda de Jira tarda en reflejar vínculos recién creados (`get_issue` los ve antes que `linkedIssues`). RF-02 «listar proyectos» queda en PA-23 | — | — | T-18 |
| 4 | 2026-09-30 | **T-18 ✅** (P): `core/context/service.py` (`ContextService`) + `core/context/budget.py`; `retrieve_context` delega en él sin cambiar `AgentState` ni `Container`. HU → HU + épica + vínculos (máx. 5) + hermanas como resumen; épica → épica + hijas; necesidad → palabras clave con `OR` reordenadas por título (máx. 3). RAG: memorias primero y **norma ↔ acta** vía `metadata["related"]` (decisión del usuario). Presupuesto 6000 tokens (PA-07 resuelta) con margen por serialización y reserva del texto de la necesidad. Real: Q-01 trae DOC-02 + DOC-19; necesidades reales ponen HU-02, HU-13 y HU-08 primero; HU-01 ≈2,8k/6k tokens. **Para T-20:** el contexto de Jira/RAG es no confiable (delimitarlo en los prompts) y `previous`/`feedback` de las iteraciones no están en el presupuesto de T-18 | — | — | T-22 |
| 4 | 2026-09-30 | T-20 ✅ (B, rama `Dia4`, sesión del compañero): prompts `generate_story`, `evolve_story`, `review_story` y `citation_retry` (v1) en `prompts/`; `core/functional/` con `StoryContext`/`render_context` (fuentes citables delimitadas y escapadas, con fecha y categoría; fragmentos del mismo `DOC-NN` fusionados), validación de citas (solo claves de Jira o `DOC-NN` recibidos; extractos reales; un reintento y `CitationError`) y `StoryWriter.generate/evolve/review` (devuelve `StoryDraft` con `prompt_version`). La revisión (RF-18) devuelve una `UserStory` mejorada: ambigüedades y huecos en `open_questions`, mejoras en `changes_from_previous` | — | Prueba real (`tests/integration/test_functional_live.py`) ejecutadas en verde al integrar en `PreProduccion` (Docker, Jira, LLM y RAG reales). Falta conectar `StoryWriter` al grafo (PA-30) | T-19 |
| 4 | 2026-09-30 | T-19 ✅ (A, rama `Dia4`, sesión del compañero): `core/impact/diff.py` (`diff_stories`, pura y determinista: campos en el orden de la plantilla, CA/RN por ID `acceptance_criteria[CA-02]`, añadidos con `before=None` y eliminados con `after=None`, fuentes por `kind:ref`, sin `changes_from_previous`) y `core/impact/versions.py` (`StoryVersionStore`: versiones inmutables en `artifact_versions`; `save` también inserta o actualiza `artifacts` por la clave foránea, sin retroceder de versión; `get`, `versions`, `latest`, `diff`) | — | Las 17 pruebas de integración (`tests/unit/test_impact_versions.py`, BD temporal `<db>_versions_test`) se ejecutaron en verde al integrar en `PreProduccion` (`uv run pytest -m integration tests/unit/test_impact_versions.py`) con `docker compose up -d db` antes de fusionar | PR de T-19 y T-20 contra `PreProduccion` |
| 4 | 2026-09-30 | **T-22 ✅** (P): `adapters/auth/local.py` (`LocalAuthProvider`: argon2id, tiempo constante con hash ficticio aleatorio, inactivos rechazados, rehash tolerante a fallos, `save_user` upsert), `core/permissions.py` (matriz rol × permiso, `can`/`require`; admin configura pero no genera ni publica, D-01), `core/factories.build_auth`. **Usuarios de demo:** `uv run python -m core.seed_users` crea `af-demo`, `qa-demo`, `admin-demo` con contraseñas aleatorias que se muestran **una sola vez** (decisión del usuario; no se guardan en repo, `.env` ni logs). Propuestas PA-25…PA-29 | — | Ejecutar el seed (lo hace el usuario) | Fusionar `Dia4` (T-19, T-20) y seguir con T-21 |
| 5 | 2026-09-30 | **PA-30 ✅** (P): el nodo `generate` usa `StoryWriter` (prompts de T-20). Origen HU → `structure` (nuevo `prompts/structure_story.md`, v1) una vez por artefacto + `evolve`; necesidad/épica → `generate` y, al iterar, `evolve` sobre el borrador; `prompt_version` y `model_used` en el `Artifact`. Impacto = diff determinista (`diff_stories`) frente a la versión estructurada de Jira; **hasta T-21 no hay HU afectadas ni vínculos «relates to» al publicar**. Cruce con el área B: `core/functional/writer.py` y `tests/fakes/llm.py` (el fake cita la primera fuente del contexto) — revisar al fusionar `Dia5`. **Bloqueo real:** la cadena `evolve_story` falla en vivo por límite de Groq y respaldo de OpenRouter sin definir (`POR_DEFINIR:free`, R-07) | — | Elegir modelos (R-07) | T-21 → T-25 |
| 5 | 2026-09-30 | **T-21 ✅** (P): `core/impact/analysis.py` (`ImpactAnalyzer`) + `prompts/analyze_impact.md` v1 (cruce con `prompts/` del área B, revisar al fusionar `Dia5`). `diffs` siempre deterministas; HU afectadas y regresión del LLM con un prompt pequeño (HU, cambios y resumen de candidatas: épica excluida, máx. 12); solo claves candidatas, un reintento y descarte anotado; sin llamada si no hay cambios o candidatas. También para HU nuevas (§6.1). `publish` vincula «relates to» al actualizar y al crear, un vínculo por clave con todos los motivos. **Sin consumo de cuota:** la prueba real (`tests/integration/test_impact_live.py`) está escrita y pendiente de ejecutar cuando el usuario lo autorice | — | Cuota de Groq (ejecución real pendiente) | T-25 |
| 5 | 2026-09-30 | **T-25 ✅** (P): `core/audit.py` (`SqlAuditTrail` sobre `audit_log`: create/iterate/approve/discard/publish, sin prompts ni contenido) y `core/artifact_state.py` (tabla `artifact_state`, migración `0002`: registro de aprobaciones persistente, que falla cerrado si está dañado, y versión de partida). `JIRA_PUBLISH_MODE=simulation` por defecto: `publish` audita el plan y no escribe en Jira; la aprobación sigue vigente. En `live`: auditoría antes de `update_status`, `failed_ids` y fallos de vínculo como errores, épica excluida (PA-38). PA-33 y PA-37 hechas; PA-06 parcial; PA-40…PA-42 nuevas. SPEC §6, §7 y anexo §11 actualizados. **Pendiente:** cablear `build_audit`/`build_versions`/`build_state_store` en el contenedor real (T-24/T-31), siempre los tres juntos (`audit_log` tiene FK a `artifacts`); `uv run alembic upgrade head` en cada entorno | — | Cuota de Groq (pruebas reales pendientes) | Fusión de `Dia5` |
| 5 | 2026-09-30 | T-26 ✅ (B, rama `Dia5`, sesión del compañero): prompts `generate_tests` (v1) y `tests_retry` (v2, datos delimitados) en `prompts/`; `core/qa/validation.py` (cobertura: CP → CA/RN existentes, todo CA con ≥1 CP, al menos un caso positivo y uno negativo; citas; datos que parecen personales en cualquier texto que acabaría en Jira, sin repetir el valor) y `core/qa/writer.py` (`TestWriter.generate(story, ctx)` → `SuiteDraft` con `coverage_md`; un reintento y después `CoverageError`/`CitationError`; `story_jira_key` = clave de la HU o, si falta, la del origen solo si es una historia). `core/functional/citations.py` acepta ahora `UserStory` o `TestSuite` (solo tipos) | — | Prueba real `tests/integration/test_qa_live.py` sin ejecutar (sin `.env` ni Docker en este equipo): la verifica la sesión principal. Conexión al grafo en modo QA: PA-61 | T-23 |
| 6 | 2026-10-01 | Revisión de la presentación del proyecto y decisiones: R-01 opción A (T-47), plan = estrategia, D-07 se mantiene, categorías del RAG de la presentación (T-49), revisar la HU como flujo propio (T-48). **UI decidida: «Propuesta mixta»** del lienzo (HU y QA, con animaciones), con proyecto por conversación; backend nuevo T-50 … T-53. Anexo para el compañero: `docs/prompts/PROMPT-05b-anexo-companero.md` (T-23 actualizado y T-49) | El compañero hace pull de `PreProduccion` y fusiona en `Dia5` | — | Fusión de `Dia5`; T-50 y T-51 (contratos) antes de T-27 |
| 6 | 2026-10-01 | **T-23 ✅** (B, rama `Dia5`, sesión del compañero): `docs/specs/UI.md` a partir de la «Propuesta mixta» del lienzo (anexo PROMPT-05b): marco común, roles según `core/permissions.py`, una tabla por pantalla (Mixta 1 … 5 y QA 1 … 6) con su dependencia (T-47, T-48, T-50 … T-53, PA-05), contrato de aprobación con huella (§5; toda escritura en Jira pasa por `publish`), estados con los mensajes reales del código y las 6 animaciones con su viabilidad en Streamlit y alternativa estática. **Para T-24:** la Q de carga solo distingue nodos del grafo (PA-66); el permiso de Revisar la calidad y de registrar la ejecución es provisional (T-48, T-47); `ValueError`/`ApprovalError` al aprobar no son `AgentError`. Propuestas PA-62 … PA-68 | — | `alembic upgrade head` (migración 0002) sin ejecutar en este equipo: falta `.env` | T-49 |
| 6 | 2026-10-01 | **T-49 👀** (B, rama `Dia5`, sesión del compañero): categorías del RAG de la presentación con slugs cortos — `productos`, `procesos`, `politicas`, `documentacion`, `glosarios`, `historias`, `pruebas` (+ `memoria`) — en `core/rag/documents.py` y `prompts/classify_source.md` v3. Corpus reasignado con `git mv` (normativa → `politicas`; especificaciones, arquitectura, manuales y actas → `documentacion`; glosario → `glosarios`) y 6 documentos sintéticos nuevos (DOC-23 … DOC-28) para las categorías vacías: **28 documentos, 285 fragmentos** (con fakes). `eval/retrieval_questions.yaml` solo remapea `category`. **Queda en 👀 hasta PA-69 (área A):** `RELATED_PAIRS` de `ContextService` sigue con `normativa`/`actas`, así que tras reindexar el acta de una norma no se añade. **Reindexado** (no contra una base compartida): `uv run python -m core.rag.indexing`; después, `uv run python -m eval.retrieval_eval` y comparar con Recall@6 0,90 · MRR 0,95. PA-69 … PA-71 | — | Sin `.env`, PostgreSQL ni Ollama en este equipo: reindexado y medición pendientes | Aplicar PA-69 (A), reindexar y medir; fusión de `Dia5` |
| 6 | 2026-10-01 | **T-50 ✅** (P): proyecto de Jira en la conversación. `Origin.project` (`initial_state` lo toma de la clave de origen: una clave de otro proyecto lo cambia), `validate_origin` exige proyecto y que el origen sea suyo; `PublishTarget.project_key` en la huella y en el plan (lo aprobado es lo publicado). **Contrato:** `create_story(story, epic_key, project)` (SPEC-00 1.4). `core/projects.py`: validación de claves escritas, `ProjectService` (`available`: último usado y, si no, `JIRA_PROJECT_KEY` si es visible; `choose`) y último proyecto por usuario (tabla `user_last_project`, migración `0003`, sin probar contra Postgres: Docker parado). `retrieve_context` busca en el proyecto del origen. **Los registros de aprobación guardados antes de T-50 fallan cerrados:** hay que regenerar esos artefactos. Vínculos «relates to» a otros proyectos permitidos. Worktrees y rama `Dia5` con la firma antigua de `create_story`: traer `PreProduccion` antes de T-27. PA-45…PA-48 | — | — | `alembic upgrade head` y `pytest -m integration tests/unit/test_projects.py tests/unit/test_migrations.py` con la BD levantada; T-51 |
| 6 | 2026-10-01 | **T-51 ✅** (P): contrato de revisión para la UI (SPEC-00 1.5). `initial_state(..., excluded_sources)`: máx. 50 referencias (clave o id, nunca texto libre), el origen no se excluye; `ContextService` las quita antes del presupuesto y del par norma ↔ acta, y rellena `top_k`; `create` las audita. Payload de `human_review` con `plan` (las operaciones de `publish`, para el recibo) y `error`. Decisión **`edit`** `{decision, content, fingerprint}`: versión nueva sin LLM (diff recalculado en evoluciones, HU afectadas conservadas, mismo `model_used`), campos de identidad fijos, auditada como `iterate` con `edited=true`, vuelve a `human_review`. **Una respuesta rechazada ya no bloquea el hilo** (defecto encontrado por test-writer): vuelve a pausar con `error`, hasta 20 veces; un rechazo del registro de aprobaciones falla cerrado. **Para la UI (T-23):** detectar la pausa por las interrupciones pendientes, no por `next`; ante `ApprovalError`, ofrecer empezar de nuevo. PA-49…PA-52 | — | — | T-52 |
| 6 | 2026-10-01 | **Fusión de `Dia5` en `PreProduccion`** (P): T-23 y T-26 ✅, T-49 👀; solo hubo conflicto en el Kanban (se conservan las filas de las dos ramas). Con T-50 y T-51 pasan 2298 pruebas. PA-68 hecha. **Pendiente de la fusión:** PA-69 (par norma ↔ acta con las categorías nuevas) y PA-71 (fakes), reindexar y medir T-49, PA-61 (QA en el grafo) y actualizar `docs/specs/UI.md` con el contrato final de T-51 (`plan`, `error`, pausa por interrupciones). **Restricciones** del panel «Antes de generar» y **tipos de caso** de QA: la UI los añade al texto de la necesidad o, al evolucionar o preparar pruebas, como primer feedback (decisión del usuario) | — | — | PA-69, PA-61, T-52, T-53 |
| 6 | 2026-10-01 | **PA-69, PA-71 ✅ y T-49 ✅** (P): par norma ↔ acta con las categorías nuevas (`politicas ↔ documentacion`) y fakes alineados. **Reindexado** en la base local: 28 documentos y 285 fragmentos (documentacion 13, glosarios 2, historias 2, politicas 4, procesos 3, productos 2, pruebas 2), sin llamadas al LLM (categorías declaradas). **Medición:** Recall@6 0,90 · MRR 0,95, igual que la línea base; latencia media 206 ms. Con el índice real, DOC-01 vuelve a traer su acta DOC-20. Observación → PA-53 | — | — | PA-61, T-52, T-53 |
| 6 | 2026-10-01 | **PA-61 ✅** (P): en modo QA, `generate` estructura la HU de Jira una vez por artefacto y genera la suite con `TestWriter` (T-26); al iterar la regenera con el feedback acumulado. **Defecto corregido** (lo encontró test-writer): si la primera generación falla, se borra la versión de partida (antes quedaba huérfana y cada reintento volvía a estructurar). `initial_state(..., feedback)` para las restricciones y los tipos de caso. **`core/factories.build_app_container`** para T-24: composición real con `PendingTestManagement` (T-30) y `PendingMemoryGenerator` (T-33); en `live` no se compone. `docs/specs/UI.md` actualizado con T-50 y T-51. **Prompt del compañero:** `docs/prompts/PROMPT-06-dia6-companero.md` (rama `Dia6`: T-24, PA-70 y, si da tiempo, T-28) | — | — | T-52, T-53 (P) en paralelo a T-24 |
| 6 | 2026-10-01 | **T-52 ✅** (P, con autorización del usuario aunque es del área A): conversaciones persistentes (SPEC-00 1.6). `postgres_checkpointer` (pool `psycopg`, serializador de tipos explícitos, `setup()` al arrancar, fuera de Alembic por `CONCURRENTLY`) y `build_checkpointer(config)`; tabla `conversations` (migración `0004`) mantenida por los nodos, con título solo de flujo y clave (decisión del usuario) y estados `started`/`in_review`/`approved`/`simulated`/`published`/`discarded`. **Propiedad del hilo:** `new_conversation_config(user)` genera el `thread_id` en el servidor; `resume_config` solo al dueño; el grafo exige `configurable.user` = dueño (`require_actor` en la app). La lista es secundaria: si su BD falla, el flujo sigue. Probado contra PostgreSQL: la pausa sobrevive a un reinicio y se aprueba con su huella. **Para T-24:** crear el checkpointer una vez (`st.cache_resource`) e invocar siempre con esas configs. `uv run alembic upgrade head` (0004) en cada entorno. PA-54 | — | — | T-53 |
