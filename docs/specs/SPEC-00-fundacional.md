# SPEC-00 · Fundacional

| Campo | Valor |
|---|---|
| Versión | 1.4 · **CONGELADA** (1.2 y 1.3 el 2026-09-30; 1.3 añade `list_projects`, RF-02; 1.4 el 2026-10-01: proyecto en la conversación y `create_story(…, project)`, T-50) |
| Propietario | Sesión principal |
| Cubre | RNF-01, RNF-02, RNF-12, RNF-14, RNF-17, RNF-18, RNF-20, RNF-23, RNF-25, RNF-26 y la base de todos los RF |

> Esta spec define **contratos**. Una vez congelada, cualquier cambio en las secciones 3 a 6 lo hace solo la sesión principal, y los worktrees hacen rebase después.

---

## 1. Objetivo
Establecer la arquitectura, los modelos de dominio, las interfaces de los adaptadores, el estado del grafo, el modelo de datos y la configuración. Así las dos áreas de trabajo (A: Integraciones y núcleo; B: Conocimiento y UI) pueden desarrollarse en paralelo contra dobles de prueba (*fakes*) e integrarse a diario.

## 2. Arquitectura en capas

```
app/ (Streamlit)  →  core/services.py  →  core/graph (LangGraph)  →  core/{functional,qa,memory,rag,context}
                                                                   ↘   adapters/* (implementan adapters/base.py)
                                                                        ↘ Jira Cloud · proveedores LLM · PostgreSQL
```

Reglas de dependencia:
- `app/` solo conoce `core/services.py` y `schemas/`.
- `core/*` solo conoce `schemas/` y los **protocolos** de `adapters/base.py`.
- `adapters/*` implementan protocolos; nunca importan desde `core/`.
- La composición (qué implementación se usa) se hace en `core/container.py` a partir de la configuración.

## 3. Modelos de dominio (`schemas/`)

Pydantic v2. Todos los modelos se usan también como **esquema de salida estructurada** del LLM.

```python
# schemas/common.py
class Priority(str, Enum): MUST="Must"; SHOULD="Should"; COULD="Could"; WONT="Won't"
class ArtifactStatus(str, Enum):
    DRAFT="draft"; IN_REVIEW="in_review"; APPROVED="approved"
    PUBLISHED="published"; DISCARDED="discarded"
class ArtifactType(str, Enum): USER_STORY="user_story"; TEST_SUITE="test_suite"
class SourceRef(BaseModel):
    kind: Literal["jira", "rag", "memory"]
    ref: str                        # clave de Jira, id de documento o id de memoria
    excerpt: str | None = None      # breve, para mostrar la cita (RF-21)

# schemas/user_story.py
class AcceptanceCriterion(BaseModel):
    id: str                         # "CA-01"
    title: str
    given: list[str]; when: list[str]; then: list[str]
class BusinessRule(BaseModel):
    id: str                         # "RN-01"
    description: str
class UserStory(BaseModel):
    internal_id: str | None = None  # "HU-XX" (R-05: prefijo en el título)
    jira_key: str | None = None
    title: str
    role: str; action: str; benefit: str
    description: str
    business_goal: str
    scope_includes: list[str]; scope_excludes: list[str]
    acceptance_criteria: list[AcceptanceCriterion]
    business_rules: list[BusinessRule]
    assumptions: list[str]; constraints: list[str]; dependencies: list[str]
    alternate_flows: list[str]; exceptions: list[str]
    related_features: list[str]
    changes_from_previous: list[str] = []
    related_requirements: list[str] = []
    priority: Priority
    sources: list[SourceRef] = []
    open_questions: list[str] = []

# schemas/impact.py            (RF-19)
class StoryDiff(BaseModel):
    field: str; before: str | None; after: str | None
class ImpactItem(BaseModel):
    jira_key: str; reason: str
    kind: Literal["story", "rule", "dependency", "regression"]
class ImpactAnalysis(BaseModel):
    diffs: list[StoryDiff]
    affected: list[ImpactItem]
    regression_notes: list[str]

# schemas/test_case.py
class TestCaseType(str, Enum):
    POSITIVE="positivo"; NEGATIVE="negativo"; ALTERNATE="alterno"; EXCEPTION="excepcion"
class TestStep(BaseModel):
    action: str; data: str | None = None; expected: str
class TestCase(BaseModel):
    internal_id: str                # "CP-01"
    title: str
    criterion_ids: list[str]        # CA vinculados
    rule_ids: list[str] = []        # RN vinculadas
    type: TestCaseType
    preconditions: list[str]
    steps: list[TestStep]
    gherkin: str | None = None
    priority: Priority
class TestSuite(BaseModel):
    story_jira_key: str
    cases: list[TestCase]
    strategy_md: str                # estrategia de pruebas (RF-26) → adjunto
    synthetic_data: list[dict[str, str]] = []
    risks: list[str] = []; dependencies: list[str] = []; impact_areas: list[str] = []
    sources: list[SourceRef] = []
    def coverage(self) -> dict[str, list[str]]: ...    # CA/RN-id → [CP-id], calculada
    def coverage_md(self) -> str: ...                  # matriz en Markdown → adjunto

# schemas/memory.py
class Memory(BaseModel):
    artifact_type: ArtifactType
    jira_key: str
    version: int
    objective: str; scope: str
    business_rules: list[str]; decisions: list[str]; dependencies: list[str]
    changes: list[str]; acceptance_criteria: list[str]; references: list[str]
    def to_markdown(self) -> str: ...

# schemas/artifact.py
class Artifact(BaseModel):
    id: UUID
    type: ArtifactType
    status: ArtifactStatus
    version: int
    origin_key: str | None
    content: UserStory | TestSuite
    impact: ImpactAnalysis | None = None
    created_by: str
    model_used: str | None = None
    prompt_version: str | None = None
```

Transiciones válidas de `ArtifactStatus` (RF-34), implementadas en `core/state_machine.py`:
`draft → in_review → approved → published` · `in_review → draft` (iterar) · `draft|in_review → discarded`. Cualquier otra transición lanza `InvalidTransitionError`.

## 4. Interfaces de adaptadores (`adapters/base.py`)

```python
class IssueTracker(Protocol):                       # Área A · Jira
    def test_connection(self) -> None: ...
    def search(self, jql: str, limit: int = 50) -> list[IssueSummary]: ...
    def get_issue(self, key: str) -> IssueDetail: ...     # descripción ADF → texto (RF-03)
    def list_projects(self) -> list[ProjectSummary]: ...  # navegación §6.1 (RF-02)
    def list_epics(self, project: str) -> list[IssueSummary]: ...
    def list_children(self, epic_key: str) -> list[IssueSummary]: ...
    # --- ESCRITURA: solo desde el nodo publish ---
    def create_story(self, story: UserStory, epic_key: str | None, project: str) -> str: ...  # T-50
    def update_story(self, key: str, story: UserStory, diff_comment_md: str) -> None: ...
    def link(self, from_key: str, to_key: str, link_type: str, comment_md: str | None = None) -> None: ...

class TestManagement(Protocol):                     # Área A · Jira nativo (D-09)
    # --- ESCRITURA: solo desde el nodo publish ---
    def publish_suite(self, suite: TestSuite) -> PublishResult: ...
    # crea subtareas CP, adjunta la estrategia y la matriz; devuelve las claves creadas y los fallos
    def list_cases(self, story_key: str) -> list[IssueSummary]: ...

class LLMProvider(Protocol):                        # Área A
    def generate(self, messages: list[Message], task: TaskType) -> LLMResult: ...
    def generate_structured(self, messages: list[Message], schema: type[T],
                            task: TaskType) -> StructuredResult[T]: ...
# LLMResult / StructuredResult: content, provider, model, input_tokens, output_tokens, latency_ms

class EmbeddingProvider(Protocol):                  # Área B
    model_name: str; dimensions: int
    def embed(self, texts: list[str]) -> list[list[float]]: ...

class VectorStore(Protocol):                        # Área B
    def upsert(self, chunks: list[Chunk]) -> None: ...
    def delete_by_document(self, document_id: str) -> None: ...
    def search(self, query_vector: list[float], query_text: str, k: int,
               filters: dict[str, str] | None = None,
               memory_boost: float = 1.0) -> list[RetrievedChunk]: ...   # RF-51

class AuthProvider(Protocol):                       # Área A
    def authenticate(self, username: str, password: str) -> User | None: ...

class MemoryGenerator(Protocol):                    # Área B · agnóstico al tipo (RNF-25)
    def generate(self, artifact: Artifact) -> Memory: ...
```

`TaskType`: `GENERATE_STORY`, `EVOLVE_STORY`, `REVIEW_STORY`, `ANALYZE_IMPACT`, `GENERATE_TESTS`, `SYNTHESIZE_MEMORY`, `CLASSIFY_SOURCE`, `NL_TO_JQL`.

**Implementaciones:**

| Protocolo | MVP | Posterior |
|---|---|---|
| IssueTracker | `JiraCloudTracker` (httpx, REST v3, `/search/jql`) | MCP de Atlassian |
| TestManagement | `JiraNativeTests` (subtareas + adjuntos + etiquetas) | Plugin (Xray/Zephyr) |
| LLMProvider | `OpenAICompatibleProvider` (Groq, OpenRouter, Ollama) + `FallbackLLMProvider` (encadena proveedores ante 429 o error) | Otros compatibles |
| EmbeddingProvider | `OllamaEmbeddings` (bge-m3), `OpenAIEmbeddings` | — |
| VectorStore | `PgVectorStore` (híbrida: vector + `tsvector`) | Qdrant |
| AuthProvider | `LocalAuthProvider` (argon2) | OIDC/SSO |

Cada protocolo tiene su **fake** en `tests/fakes/` desde el día 1.

## 5. Grafo LangGraph (`core/graph/`)

### 5.1 Estado
```python
class AgentState(TypedDict):
    user: str
    mode: Literal["functional", "qa"]
    origin: Origin                  # {kind: "epic"|"story"|"need", key?: str, text?: str, project?: str}
    jira_context: list[IssueDetail]
    rag_context: list[RetrievedChunk]
    artifact: Artifact | None
    feedback: list[str]             # historial de iteración (RF-20)
    decision: Literal["iterate", "approve", "discard"] | None
    published_keys: list[str]
    errors: list[str]
```

### 5.2 Nodos
| Nodo | Responsabilidad | Paso |
|---|---|---|
| `load_origin` | Validar el origen y cargar la incidencia si hay clave | 1 |
| `retrieve_context` | Servicio de contexto: Jira (épica padre, hermanas, vínculos) + RAG (documentos y memorias con prioridad) | 2–3 |
| `generate` | HU nueva, evolución (con `ImpactAnalysis` y diff) o TestSuite, según el modo y el origen | 4 |
| `human_review` | `interrupt()` → la UI muestra la vista previa y los cambios; reanuda con decisión y feedback | 5–6 |
| `publish` | **Único nodo que escribe** en Jira; exige `APPROVED`; registra la auditoría | 7 |
| `memorize` | Memoria .md + reindexado (solo `USER_STORY` en el MVP, D-07) | 8 |

Aristas: `human_review` → `generate` (iterate) · `publish` (approve) · `END` (discard).
Checkpointer: `langgraph-checkpoint-postgres`.

## 6. Modelo de datos (PostgreSQL)

| Tabla | Campos clave |
|---|---|
| `users` | id, username, password_hash, role (`functional`, `qa`, `admin`), active |
| `artifacts` | id, type, status, version, origin_key, jira_key, content (jsonb), impact (jsonb), created_by, model_used, prompt_version, timestamps |
| `artifact_versions` | artifact_id, version, content (jsonb), created_at |
| `audit_log` | id, artifact_id, action (`create`, `iterate`, `approve`, `publish`, `discard`), user, jira_keys, model, detail (jsonb), at |
| `artifact_state` | artifact_id (PK, sin FK), state (jsonb: `ledger` de aprobaciones y `baseline` de la versión de partida), updated_at (T-25, migración `0002`) |
| `user_last_project` | username (PK, sin FK), project_key, updated_at (T-50, migración `0003`: último proyecto usado, para preseleccionarlo) |
| `documents` | id, title, category (7 categorías + `memoria`), source_path, embedding_model, content_hash, related_key, created_at |
| `chunks` | id, document_id, ordinal, section, content, embedding `vector(N)`, tsv `tsvector`, metadata (jsonb) |
| `llm_usage` | id, task, provider, model, input_tokens, output_tokens, est_cost, latency_ms, artifact_id, at (RF-43) |

- Memorias: archivo `data/memory/<JIRA_KEY>.md` + `documents.category='memoria'`, sin fragmentar, con `related_key` para el reindexado (RF-38).
- Migraciones con Alembic.

## 7. Configuración

`.env` contiene los secretos y las URLs (ver `.env.example`). `config/models.yaml` contiene, sin secretos, la asignación de modelos por tarea como **cadena ordenada** de `{provider, model}` (el primero es el principal y el resto, respaldos). Solo se activan los proveedores cuya variable de clave exista. El selector de la UI (RF-42) puede sobrescribir el modelo de una tarea durante la sesión.

`JIRA_PUBLISH_MODE` (`simulation` por defecto, o `live`) decide si el nodo `publish` escribe en Jira; en `simulation` solo audita el plan de operaciones (T-25).

## 8. Transversales
- **Errores:** `adapters/errors.py` → `ExternalServiceError`, `AuthenticationError`, `NotFoundError`, `PublishError`, `InvalidTransitionError`, `RateLimitError`. Reintentos con backoff solo en lecturas.
- **LLM gratuitos (RNF-27, RNF-28):** ante un 429 se respeta `retry-after` y, si se supera el umbral, `FallbackLLMProvider` pasa al siguiente proveedor de la cadena de la tarea. `generate_structured` usa JSON Schema si el proveedor lo admite y, si no, modo JSON. Siempre se valida con Pydantic y se reintenta una vez con el error de validación.
- **Publicación parcial (RNF-13):** `publish_suite` crea los elementos uno a uno y devuelve un `PublishResult(created, failed)`. La auditoría registra ambos y la UI ofrece reintentar solo los fallidos.
- **Logging:** structlog en JSON con un procesador que enmascara tokens y claves.
- **Prompts:** `prompts/<tarea>.md` con cabecera `version:`.
- **ADF:** `adapters/jira/adf.py` con `adf_to_text()` (lectura) y `markdown_to_adf()` (escritura: títulos, párrafos, listas, tablas, negrita y bloques de código).

## 9. Criterios de aceptación
| ID | Criterio |
|---|---|
| CA-00-01 | `uv sync` y `docker compose up -d db` levantan el entorno desde cero |
| CA-00-02 | Existen todos los `schemas/` y protocolos, con tipado y validación |
| CA-00-03 | Cada protocolo tiene un fake funcional con pruebas |
| CA-00-04 | El grafo se ejecuta de extremo a extremo con fakes, incluidos la pausa en `human_review` y la reanudación |
| CA-00-05 | Ningún secreto en el repo (gitleaks en pre-commit y en CI) |
| CA-00-06 | Las migraciones crean todas las tablas de la sección 6 |
| CA-00-07 | La máquina de estados rechaza las transiciones no válidas |

## 10. Pendiente
- R-05: formato de los IDs internos (provisional: prefijo `[HU-XX]` / `[CP-XX]` en el título).
- R-01: alcance de la ejecución → ampliación de `TestManagement` en la v1.1.

## 11. Anexo de congelación (día 1)

Precisiones acordadas durante T-01…T-07. Forman parte del contrato congelado; la implementación de referencia está en el código indicado.

| Tema | Contrato | Código |
|---|---|---|
| Enums | `StrEnum` (equivalente a `str, Enum`) | `schemas/common.py` |
| Validaciones de `schemas/` (ratificadas) | IDs `^CA-\d+$`, `^RN-\d+$`, `^CP-\d+$`; textos obligatorios no vacíos; `version` ≥ 1; listas mínimas (`acceptance_criteria`, `given/when/then`, `criterion_ids`, `steps`, `cases`); IDs únicos; `Artifact.type` coherente con `content`. Un CP debe referenciar al menos un CA | `schemas/` |
| `Artifact` | Mutable (sin `frozen`); la aprobación se garantiza en el registro de aprobaciones | `schemas/artifact.py` |
| Tipos auxiliares (§4) | `ProjectSummary(key, name)` (v1.3); `IssueSummary(key, summary, issue_type, status)`; `IssueDetail(+description_text, parent_key, subtasks, links: list[IssueLink], comments, labels)`; `IssueLink(link_type, key)`; `Message(role, content)`; `LLMResult` / `StructuredResult[T]` (`content`, `provider`, `model`, `input_tokens`, `output_tokens`, `latency_ms`); `Chunk(id, document_id, ordinal, section, content, embedding, metadata)`; `RetrievedChunk(chunk, score, source: SourceRef)`; `PublishResult(created, failed)`; `User(username, role)` | `adapters/base.py` |
| `TaskType` | Valores en minúscula, iguales a las claves de `config/models.yaml` | `adapters/base.py` |
| Protocolos | `@runtime_checkable` | `adapters/base.py` |
| Dependencias (§2) | `core/` puede importar también `adapters/errors.py` | — |
| Errores (§8) | Base común `AgentError`; `RateLimitError.retry_after` | `adapters/errors.py` |
| Reanudación de `human_review` (§5) | El payload del `interrupt` incluye `artifact`, `version`, `target` (operación descrita), `fingerprint`, `impact`, `decisions`. La reanudación es `{"decision": "iterate" \| "approve" \| "discard", "feedback"?: str, "fingerprint": str}`; `fingerprint` es **obligatoria** para `approve` y debe ser la recibida | `core/graph/nodes.py` |
| Aprobación humana (§5) | `core/approvals.py`: la versión y su operación (`PublishTarget`: modo, tipo y clave de origen, usuario, hilo) se registran al generar; la operación no cambia entre iteraciones; `publish` toma la operación del registro, exige aprobación vigente y la consume (un solo uso); `memorize` exige publicación registrada. Desde T-25 persiste por artefacto en `artifact_state.state["ledger"]`; un registro dañado falla cerrado (`ApprovalError`) | `core/approvals.py` |
| Claves de Jira | `^[A-Z][A-Z0-9_]+-\d+$`, validadas al cargar, generar y publicar | `core/graph/nodes.py` |
| Composición | `core/container.build_container()` exige todas las dependencias hasta que existan los adaptadores reales; `bootstrap_logging()` cablea el enmascarado de secretos | `core/container.py` |
| Checkpointer | Serializador con lista explícita de tipos (`checkpoint_serializer()`), sin pickle; reutilizarlo al conectar Postgres | `core/graph/builder.py` |
| `documents.category` | Texto libre sin CHECK hasta definir las 7 categorías (T-09/T-12) | `migrations/versions/0001_initial.py` |
| Embeddings | Solo `OllamaEmbeddings` (API compatible con OpenAI); `OpenAIEmbeddings` se descarta por D-14 (sin servicios de pago) | `adapters/embeddings/ollama.py` |
| `VectorStore` sobre Postgres | Ids de texto del protocolo → UUID (`uuid5`), originales en `metadata` (`_chunk_id`, `_document_id` reservadas); `upsert` crea/actualiza `documents` desde la `metadata` del fragmento (`category` obligatoria) y registra `embedding_model`; la búsqueda solo considera el modelo de la colección | `adapters/vectorstore/pgvector.py` |
| Composición real | `core/factories.py` traduce `AppConfig` a los adaptadores reales (`build_llm_provider`, `model_router`, `build_issue_tracker`, `build_embeddings`, `build_vector_store`, `build_auth`); `core/container.py` lo usará al sustituir los fakes. Las CLI `core/rag/indexing.main`, `eval/retrieval_eval.main` y `core/seed_users.main` son también puntos de composición | `core/factories.py` |
| Jira y scopes | Token con scopes vía `https://api.atlassian.com/ex/jira/<cloudId>`; `test_connection` usa `/rest/api/3/project/search` (basta `read:jira-work`) | `adapters/jira/tracker.py` |
| `list_projects` (v1.3) | `IssueTracker.list_projects() -> list[ProjectSummary]` (`ProjectSummary(key, name)`), para la navegación Proyecto → Épica → HU (§6.1, RF-02); en Jira, `/rest/api/3/project/search` (basta `read:jira-work`) | `adapters/base.py`, `adapters/jira/tracker.py` |
| Permisos por rol | `core/permissions.py`: `Permission`, `ROLE_PERMISSIONS`, `can`, `require` (D-01: cada rol su flujo; el administrador configura pero no genera ni publica) | `core/permissions.py` |
| Persistencia del núcleo | `core/` puede acceder con SQLAlchemy a **sus propias tablas** (`artifact_versions`, `audit_log`, `artifacts`) mediante repositorios como `core/impact/versions.py`, `core/audit.py` y `core/artifact_state.py` (incluida `artifact_state`); los servicios externos (Jira, LLM, embeddings, vectores, usuarios) siguen detrás de `adapters/` | `core/impact/versions.py` |
| Modo de publicación (T-25) | `Container.publish_mode` (`simulation` \| `live`) desde `Settings.jira_publish_mode`. En `simulation`, `publish` calcula el plan (`update_story`/`create_story`, `link`, `publish_suite`), audita `publish` con `detail.simulated=true` y el plan, no escribe en Jira, no consume la aprobación y el artefacto sigue `APPROVED` | `core/graph/nodes.py` |
| Auditoría (T-25, RF-35) | `core/audit.py`: `AuditEntry(artifact_id, action, user, jira_keys, model, detail)`; `generate` → `create`/`iterate` (`prompt_version`), `human_review` → `approve` (`operation`)/`discard`, `publish` → `publish` (`simulated`, `plan`, `failed`, `failed_ids`). `detail` nunca lleva prompts ni contenido del artefacto. En `live`, se audita antes de actualizar el estado de `artifacts`; los vínculos que fallan se informan como error sin deshacer lo publicado (RNF-13) | `core/audit.py`, `core/graph/nodes.py` |
| Composición de T-25 | `Container` añade `audit`, `versions` (`VersionSink`: `save`, `update_status`), `state_store` y `publish_mode`; `__post_init__` conecta el registro de aprobaciones al `state_store`. Fábricas `build_audit`, `build_versions`, `build_state_store` | `core/container.py`, `core/factories.py` |
| Versión de partida (PA-30, PA-37) | La HU de Jira estructurada una sola vez se guarda en `artifact_state.state["baseline"]` y se borra al descartar o publicar | `core/graph/nodes.py` |
| Vínculos y épica (PA-38) | Al evolucionar o crear una HU, nunca se vincula `relates to` con su épica | `core/graph/nodes.py` |
| Proyecto en la conversación (T-50) | `Origin.project`: proyecto de Jira de la conversación, elegido al empezar entre los de `list_projects`; `initial_state` lo toma del prefijo de la clave de origen (una clave de otro proyecto lo cambia). `validate_origin` exige proyecto con formato `^[A-Z][A-Z0-9_]+$` y que la clave de origen sea suya. `PublishTarget.project_key` entra en la huella (lo aprobado es lo publicado) y el plan de `publish` lo incluye; `publish` rechaza una operación cuyo origen no sea del proyecto aprobado; los vínculos «relates to» del impacto sí pueden ir a HU de otros proyectos (se muestran en el plan y entran en la huella). Un registro de aprobaciones anterior sin `project_key` falla cerrado | `core/graph/state.py`, `core/graph/nodes.py`, `core/approvals.py` |
| `create_story` (T-50) | `IssueTracker.create_story(story, epic_key, project)`: la HU se crea en el proyecto aprobado | `adapters/base.py` |
| Elección del proyecto (T-50) | `core/projects.py`: `normalize_project_key`, `normalize_issue_key` y `project_of` para las claves escritas; `ProjectService.available(user)` → `ProjectChoice(projects, preselected)` (último usado si sigue visible; si no, `JIRA_PROJECT_KEY` si es visible) y `choose(user, project)` (valida contra `list_projects`, `NotFoundError` si no es visible, y lo recuerda). `Container.last_projects` (`LastProjectStore`, en memoria por defecto; `SqlLastProjectStore` con `build_last_projects`) y `Container.projects`. `ContextService` busca en el proyecto del origen | `core/projects.py`, `core/container.py`, `core/factories.py` |
