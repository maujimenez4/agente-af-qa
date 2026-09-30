# Investigación Tecnológica
## Proyecto 1 · Agente de IA especializado en Análisis Funcional y QA

| Campo | Valor |
|---|---|
| Versión | 0.3 (modelos open-weight gratuitos, D-14 · Xray descartado, D-09) |
| Fecha de la investigación | Septiembre 2026 |
| Estado | Decisiones confirmadas (D-13), excepto las marcadas como pendientes |

---

## 1. Criterios de evaluación

Cada tecnología se evalúa con los mismos criterios, derivados de los RNF y del plazo de 15 días:

| Criterio | Peso | Motivo |
|---|---|---|
| Velocidad de desarrollo | Alto | 15 días para el MVP y una v1.1 |
| Soporte de aprobación humana | Alto | Principio no negociable |
| Independencia del proveedor LLM | Alto | Diapositiva 8, RF-40 a RF-42 |
| Privacidad y ejecución local | Medio | RNF-07 |
| Madurez y mantenimiento | Medio | Reducir el riesgo técnico |
| Coste | Medio | Proyecto de demostración |
| Complejidad operativa | Medio | Menos piezas significa menos riesgo |

---

## 2. Stack recomendado de un vistazo

| Capa | Recomendación | Alternativa | Decisión |
|---|---|---|---|
| Lenguaje | Python 3.12 | — | DT-00 |
| Orquestación del agente | **LangGraph** | PydanticAI · Python puro | DT-01 |
| Acceso a LLM | **SDK de OpenAI con `base_url` configurable + adaptador propio** | LangChain `init_chat_model` · LiteLLM (versiones fijadas) | DT-02 |
| Embeddings | **text-embedding-3-small** (nube) / **bge-m3** (local) | qwen3-embedding | DT-03 |
| Base vectorial | **PostgreSQL + pgvector** | Qdrant · Chroma | DT-04 |
| Procesado de documentos | **Docling** | MarkItDown · Unstructured | DT-05 |
| Jira | **API REST v3 directa (httpx)** | atlassian-python-api · MCP remoto de Atlassian | DT-06 |
| Gestión de pruebas | **Jira nativo: subtareas, adjuntos y vínculos** | Plugin (Xray/Zephyr) en v2.0 | DT-07 |
| Interfaz | **Streamlit** | Chainlit | DT-08 |
| Observabilidad | **Langfuse** | Logs estructurados (structlog) | DT-09 |
| Evaluación de calidad | **DeepEval o RAGAS** (v1.1) | promptfoo | DT-10 |
| Entorno y empaquetado | **uv + Docker Compose** | pip + venv | DT-11 |

---

## 3. Análisis por capa

### 3.1 Orquestación del agente (DT-01)

El flujo tiene pausas obligatorias (aprobación), bucles (iteración) y estado persistente (borrador → aprobado → publicado). Esto encaja con una máquina de estados.

| Opción | Puntos fuertes | Puntos débiles |
|---|---|---|
| **LangGraph** | Versión 1.0 estable desde octubre de 2025. Cualquier nodo puede pausarse con `interrupt()` para que una persona revise o edite el estado y luego reanudar. Checkpoints persistentes. | Curva de aprendizaje mayor; más código que alternativas ligeras |
| PydanticAI | Menos código, tipado fuerte y validación automática de las salidas del LLM; aprobación mediante excepciones `ApprovalRequired` | Orquestación de flujos complejos menos madura (grafo opcional) |
| Python puro | Control total, sin dependencias | Hay que construir a mano el estado, los reintentos y las pausas |

**Recomendación: LangGraph.** El grafo refleja directamente los 8 pasos del flujo, y `interrupt()` implementa el paso 6 (confirmar antes de publicar) de forma nativa. Para mitigar la curva de aprendizaje, conviene empezar con un grafo mínimo de 5 nodos el día 2 y ampliarlo después.

Grafo propuesto:

```mermaid
flowchart LR
    A[Seleccionar origen] --> B[Recuperar Jira]
    B --> C[Recuperar RAG]
    C --> D[Generar propuesta]
    D --> E{Revisión humana<br/>interrupt}
    E -- iterar --> D
    E -- descartar --> Z[Fin]
    E -- aprobar --> F[Publicar en Jira]
    F --> G[Generar memoria .md]
    G --> H[Indexar en RAG]
```

### 3.2 Acceso a los modelos (DT-02)

Ollama expone una API compatible con OpenAI, así que un único cliente cubre OpenAI, Ollama y cualquier proveedor compatible con solo cambiar `base_url`, `api_key` y `model`.

| Opción | Puntos fuertes | Puntos débiles |
|---|---|---|
| **SDK de OpenAI + adaptador propio** | Una sola dependencia oficial; cubre los proveedores de la diapositiva 8 | Los proveedores no compatibles (p. ej. las APIs nativas de otros fabricantes) requieren su propio adaptador |
| LangChain `init_chat_model` | Integración directa con LangGraph; muchos proveedores | Más capas de abstracción |
| LiteLLM | Más de 100 proveedores, contabilidad de costes integrada | En marzo de 2026 se publicaron en PyPI dos versiones comprometidas (1.82.7 y 1.82.8) con malware de robo de credenciales. El proyecto publicó después la 1.83.0 con un proceso de publicación reforzado. Si se usa: versión fijada y verificación por hash (RNF-26). |

**Recomendación:** una interfaz propia `LLMProvider` con implementación basada en el SDK de OpenAI. El Administrador define en la configuración qué proveedor y modelo usa cada tarea (RF-41).

**Asignación inicial de modelos por tarea** (a validar con pruebas):

| Tarea | Requisito de calidad | Nube | Local (Ollama) |
|---|---|---|---|
| Generar HU y CP | Alta | Modelo principal de gama media | Modelo de ~20–30B (p. ej. gpt-oss:20b, familia qwen3) |
| Revisar y mejorar HU | Alta | Modelo principal de gama media | Ídem |
| Sintetizar memoria .md | Media | Modelo mini | Modelo de 8–20B |
| Clasificar fuentes y generar JQL | Baja | Modelo nano | Modelo pequeño |

> **Nota:** el catálogo de modelos de OpenAI cambia con frecuencia y las fuentes secundarias consultadas no coinciden entre sí sobre qué modelos están vigentes. Los nombres exactos y los precios se fijarán el día 1 consultando la página oficial de precios. El diseño no depende de un modelo concreto.

**Optimización de tokens** (además de la memoria .md):
- Poner el system prompt y la plantilla al principio y de forma estable, para aprovechar la caché de prompts del proveedor (la entrada en caché se factura con un fuerte descuento).
- Fijar un presupuesto de contexto por tarea (p. ej. N fragmentos del RAG + la memoria relevante).
- Pedir salidas estructuradas (JSON Schema / Pydantic) para evitar texto redundante. Ollama también las admite.

### 3.3 Embeddings (DT-03)

| Opción | Tipo | Puntos fuertes | Puntos débiles |
|---|---|---|---|
| **text-embedding-3-small** | Nube | Muy barato, simple, buen rendimiento general | Los datos salen del entorno |
| **bge-m3** | Local (Ollama) | Multilingüe (más de 100 idiomas), ventana de 8192 tokens, recuperación densa y dispersa | Necesita recursos locales |
| qwen3-embedding | Local (Ollama) | Líder del ranking multilingüe MTEB en su tamaño de 8B; tamaños 0.6B, 4B y 8B | Los tamaños grandes exigen GPU |

> **Restricción importante:** una colección vectorial solo puede usar un modelo de embeddings. Cambiarlo obliga a reindexar. Se registrará el modelo usado en los metadatos de la colección.

**Recomendación:** empezar con **bge-m3 en local**. Es coherente con el principio de privacidad, rinde bien en español y el corpus sintético es pequeño. text-embedding-3-small queda configurado como alternativa.

### 3.4 Base vectorial (DT-04)

| Opción | Puntos fuertes | Puntos débiles |
|---|---|---|
| **PostgreSQL + pgvector** | Una sola base de datos para usuarios, auditoría, estados de artefactos **y** vectores. Filtros SQL y búsqueda de texto completo para recuperación híbrida. Adecuada hasta unos 10 millones de vectores. | Filtros menos ergonómicos que Qdrant |
| Qdrant | Filtrado por metadatos durante la búsqueda en el índice HNSW, multi-tenencia nativa | Un servicio más que operar, además de la base relacional que igualmente necesitamos |
| Chroma | Arranque inmediato, ideal para prototipos | Menos adecuada para producción; seguiríamos necesitando otra base de datos para la auditoría |

**Recomendación: PostgreSQL + pgvector.** La auditoría (RF-35), los usuarios (RF-45) y los estados (RF-34) exigen igualmente una base relacional. Tener una sola pieza reduce la complejidad operativa en 15 días. La interfaz `VectorStore` permite migrar a Qdrant en v2.0 si se necesita multi-tenencia (RNF-22).

### 3.5 Procesado de documentos y fragmentación (DT-05)

| Opción | Puntos fuertes | Puntos débiles |
|---|---|---|
| **Docling** (IBM, MIT) | Convierte PDF, DOCX, PPTX, XLSX e imágenes a Markdown estructurado; extracción de tablas; OCR; integración con LangChain y LlamaIndex | Dependencias más pesadas |
| MarkItDown (Microsoft, MIT) | Muy ligero y rápido | Menor calidad en tablas y maquetaciones complejas |
| Unstructured | Más de 25 formatos, estrategias de fragmentación | La versión gestionada es de pago; más complejo |

**Recomendación: Docling.** El corpus sintético se redactará directamente en Markdown, así que el riesgo es bajo. Docling queda preparado para cuando lleguen documentos reales en PDF o DOCX.

**Estrategia de fragmentación inicial** (a ajustar con evaluación):
- Dividir primero por encabezados de Markdown (se conserva la sección como metadato) y después de forma recursiva.
- Tamaño de 500–800 tokens y solapamiento del 10–15 %.
- Las memorias .md no se fragmentan: al ser sintéticas y cortas, se indexan completas.
- Recuperación híbrida (vectorial + texto completo de PostgreSQL) con filtro por categoría. El reranker queda para v1.1.

### 3.6 Integración con Jira Cloud (DT-06)

Hallazgos relevantes:
- **Autenticación:** HTTP Basic con el email y un API token. Los tokens nuevos caducan en un plazo de 1 a 365 días y pueden crearse **con scopes** (p. ej. `read:jira-work` y `write:jira-work`). Con tokens con scopes, las peticiones deben ir a `api.atlassian.com/ex/jira/{cloudId}/`.
- **Búsqueda:** el endpoint antiguo `/rest/api/3/search` se ha retirado. Hay que usar `/rest/api/3/search/jql`, que pagina con `nextPageToken`. La comunidad ha reportado problemas de paginación en este endpoint. Mitigación: consultas acotadas (el proyecto de pruebas es pequeño) y, si falla, la API Agile (`/rest/agile/1.0/board/{id}/issue`).
- **Formato:** la API v3 usa Atlassian Document Format (ADF) en las descripciones. Hay que convertir de Markdown a ADF antes de publicar.

| Opción | Puntos fuertes | Puntos débiles |
|---|---|---|
| **API REST directa (httpx)** | Control total de cada escritura, lo que es clave para garantizar la aprobación humana | Hay que implementar la conversión a ADF y la paginación |
| atlassian-python-api | Ahorra código | Hay que verificar que ya use los endpoints nuevos |
| MCP remoto de Atlassian | Estándar emergente, integración rápida con el agente | Menos control sobre las escrituras; se han reportado problemas de paginación en su herramienta de búsqueda |

**Recomendación: API REST directa** detrás de un adaptador `IssueTracker`. El MCP de Atlassian queda como Propuesta adicional para la v2.0.

### 3.7 Gestión de pruebas en Jira nativo (DT-07, D-09)

Se descarta el plugin de gestión de pruebas para el MVP. Los artefactos de QA se publican con la API REST v3 estándar de Jira, sin licencias adicionales:

| Artefacto del agente | Representación en Jira | Endpoint |
|---|---|---|
| Caso de prueba (CP) | Subtarea de la HU con la etiqueta `caso-prueba`, más etiquetas de CA/RN y tipo | `POST /rest/api/3/issue` (con `parent`) |
| Escenario Gherkin | Bloque de código en la descripción ADF de la subtarea | — |
| Estrategia de pruebas | Adjunto `.md` en la HU | `POST /rest/api/3/issue/{key}/attachments` (cabecera `X-Atlassian-Token: no-check`) |
| Matriz de cobertura | Adjunto `.md` en la HU; también se calcula a partir de las etiquetas | Ídem |
| Impacto | Vínculo "relates to" y comentario explicativo | `POST /rest/api/3/issueLink` · `/comment` |
| Ejecución (v1.1, R-01) | Transición de estado de la subtarea y comentario con la evidencia | `/transitions` · `/comment` |

La interfaz `TestManagement` se mantiene, con la implementación `JiraNativeTests`. Así, un plugin como Xray podría añadirse en v2.0 sin tocar el núcleo.

### 3.8 Interfaz de usuario (DT-08)

La interfaz necesita un chat, una vista previa con botones Aprobar, Editar y Descartar, un panel de navegación de Jira y páginas de administración.

| Opción | Puntos fuertes | Puntos débiles |
|---|---|---|
| **Streamlit** | Muy madura y con gran comunidad; componentes de chat (`st.chat_input`, streaming); aplicaciones multipágina, útiles para Chat, Conocimiento y Administración | Relanza el script en cada interacción; hay que gestionar bien `session_state` |
| Chainlit | Experiencia de chat superior y autenticación integrada | Desde mayo de 2025 la mantiene la comunidad; no hay garantía de respuesta ante incidencias de seguridad |
| React + FastAPI | Máxima flexibilidad | No es viable en 15 días junto con el resto |

**Recomendación: Streamlit**, con la lógica del agente en un paquete independiente de la interfaz. Así se puede cambiar de interfaz o exponer una API FastAPI en v1.1 o v2.0 sin tocar el núcleo.

### 3.9 Autenticación simple (D-05)

Tabla de usuarios en PostgreSQL con contraseñas con hash (bcrypt o argon2) y un rol por usuario. Tres usuarios sintéticos de demo, uno por rol. La interfaz `AuthProvider` permitirá enchufar OIDC/SSO en v2.0.

### 3.10 Gestión de secretos (RNF-01, RNF-02)

| Entorno | Mecanismo |
|---|---|
| Desarrollo | Archivo `.env` (incluido en `.gitignore`) cargado con `pydantic-settings`; `.env.example` solo con placeholders |
| Docker | Docker secrets o variables inyectadas en tiempo de ejecución |
| v2.0 | Gestor de secretos corporativo (Vault o el equivalente del proveedor cloud) |

Además, un filtro de logs que enmascare cualquier valor con forma de token, y el uso de `SecretStr` de Pydantic para que los secretos nunca se impriman.

Ejemplo de `.env.example`:
```
JIRA_BASE_URL=https://TU_SITIO.atlassian.net
JIRA_EMAIL=TU_EMAIL
JIRA_API_TOKEN=TU_TOKEN_JIRA
OPENAI_API_KEY=TU_API_KEY
OLLAMA_BASE_URL=http://localhost:11434/v1
DATABASE_URL=postgresql://USUARIO:CONTRASEÑA@localhost:5432/agente
```

### 3.11 Observabilidad (DT-09)

| Opción | Puntos fuertes | Puntos débiles |
|---|---|---|
| **Langfuse** | Código abierto (MIT); trazas, métricas de tokens, coste y latencia, y gestión de prompts versionados (cubre RF-43, RNF-18, RNF-23 y RNF-24). Adquirida por ClickHouse en enero de 2026, con compromiso público de mantener el código abierto y el autoalojamiento. | El autoalojamiento de la v3 requiere varios servicios (ClickHouse, Redis, almacenamiento de objetos) |
| structlog + tabla de métricas propia | Ligero | Sin interfaz de análisis; hay que construir las métricas |

**Recomendación:** logs estructurados con structlog desde el día 1 (MVP) y Langfuse en v1.1. Como los datos son sintéticos, puede usarse la versión cloud para evitar operar la infraestructura. Autoalojarlo solo si se exige.

### 3.12 Evaluación de calidad (DT-10, v1.1)

- Construir un **conjunto dorado** de 10–15 necesidades sintéticas con su HU y CP esperados.
- Medir la fidelidad al contexto (sin alucinaciones, RNF-14), la relevancia del contexto recuperado y la completitud de la plantilla.
- Herramientas: DeepEval o RAGAS (métricas de RAG) y promptfoo (comparar modelos y prompts). Esto permite elegir modelos por tarea con datos (RF-41).

### 3.13 Datos sintéticos y corpus semilla (D-06)

- **Dominio ficticio** sugerido: una aseguradora o entidad financiera inventada, con productos, procesos y reglas verosímiles.
- **Corpus:** 15–25 documentos Markdown que cubran las 7 categorías de fuentes, generados con ayuda del LLM y revisados manualmente.
- **Jira:** 3–4 épicas y 10–15 HU sintéticas cargadas con un script.
- **Datos de prueba:** la librería Faker con locale `es_ES`, más reglas de negocio aplicadas en el código. Siempre identificadores inventados.

### 3.14 Entorno de desarrollo (DT-11)

- **uv** para dependencias, con lockfile y hashes (RNF-26, mitigación de ataques a la cadena de suministro).
- **ruff** para linting y formato, y **pytest** para pruebas.
- **Docker Compose** con los servicios: app (Streamlit), postgres (con pgvector) y ollama (opcional).
- Repositorio Git con un `.gitignore` que excluya `.env`, y opcionalmente un escáner de secretos (gitleaks) antes de cada commit.

---

## 4. Arquitectura propuesta

```mermaid
flowchart TB
    subgraph UI[Interfaz · Streamlit]
        CH[Chat]
        PV[Vista previa y aprobación]
        NAV[Navegación Jira]
        ADM[Administración]
    end

    subgraph CORE[Núcleo del agente · Python]
        ORQ[Orquestador LangGraph]
        AF[Módulo Análisis Funcional]
        QA[Módulo QA]
        MEM[Generador de memoria .md]
        RAGS[Servicio RAG: ingesta y recuperación]
    end

    subgraph ADP[Adaptadores]
        JI[IssueTracker · Jira REST v3]
        XR[TestManagement · Jira nativo]
        LLM[LLMProvider · OpenAI / Ollama]
        VS[VectorStore · pgvector]
    end

    DB[(PostgreSQL + pgvector<br/>usuarios · auditoría · estados · vectores)]
    OBS[Observabilidad · structlog / Langfuse]

    UI --> ORQ
    ORQ --> AF & QA & MEM & RAGS
    AF & QA & MEM --> LLM
    RAGS --> VS --> DB
    ORQ --> JI & XR
    ORQ --> DB
    CORE -.-> OBS
```

Estructura inicial del repositorio:

```
agente-af-qa/
├── app/                 # Interfaz Streamlit (páginas)
├── core/
│   ├── graph/           # Nodos y estado de LangGraph
│   ├── functional/      # Generación y revisión de HU
│   ├── qa/              # Generación de CP y matriz
│   ├── memory/          # Generador de memoria (agnóstico al tipo)
│   └── rag/             # Ingesta, chunking y recuperación
├── adapters/            # jira, testmgmt, llm, embeddings, vectorstore, auth
├── prompts/             # Prompts versionados (.md / .yaml)
├── schemas/             # Modelos Pydantic: HU, CP, Memoria
├── data/seed/           # Corpus sintético y script de carga en Jira
├── tests/
├── docker-compose.yml
├── .env.example
└── pyproject.toml
```

---

## 5. Riesgos técnicos

| ID | Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|---|
| RT-01 | El proyecto de Jira no tiene el tipo de subtarea o los permisos de adjuntos | Baja | Medio | Configurarlo el día 1 y validarlo con `test_connection` |
| RT-02 | Paginación inestable de `/search/jql` | Media | Medio | Consultas acotadas; alternativa con la API Agile |
| RT-03 | Curva de aprendizaje de LangGraph | Media | Medio | Grafo mínimo el día 2; ampliarlo de forma incremental |
| RT-04 | El hardware local no soporta modelos Ollama medianos | Media | Medio | Usar modelos pequeños en local y la nube para las tareas de alta calidad |
| RT-05 | Alucinaciones o referencias inventadas | Media | Alto | Citar las fuentes (RF-21), salidas estructuradas, revisión humana y conjunto dorado |
| RT-06 | Dependencia comprometida en la cadena de suministro | Baja | Alto | Lockfile con hashes, versiones fijadas, pocas dependencias |
| RT-07 | Conversión de Markdown a ADF incompleta | Media | Bajo | Limitarse a un subconjunto de formato (títulos, listas, tablas y código) |

---

## 6. Decisiones tecnológicas pendientes

| ID | Decisión | Recomendación | Estado |
|---|---|---|---|
| DT-00 | Lenguaje | Python 3.12 | ✅ |
| DT-01 | Orquestación | LangGraph | ✅ |
| DT-02 | Acceso a LLM | SDK de OpenAI con adaptador propio y cadena de respaldo (Groq → OpenRouter → Ollama) | ✅ |
| DT-03 | Embeddings | bge-m3 local, text-embedding-3-small como alternativa | 🟡 Depende del hardware (R-08) |
| DT-04 | Base vectorial | PostgreSQL + pgvector | ✅ |
| DT-05 | Procesado de documentos | Docling | ✅ |
| DT-06 | Integración Jira | API REST v3 directa | ✅ |
| DT-07 | Gestión de pruebas | Jira nativo (D-09) | ✅ |
| DT-08 | Interfaz | Streamlit | ✅ |
| DT-09 | Observabilidad | structlog (MVP) + Langfuse (v1.1) | ✅ |
| DT-10 | Evaluación | DeepEval o RAGAS + conjunto dorado (v1.1) | ✅ |
| DT-11 | Entorno | uv + Docker Compose | ✅ |

---

## 7. Preguntas abiertas

1. ¿Qué hardware hay disponible para Ollama (RAM y GPU)? Condiciona DT-03 y los modelos locales.
2. ¿Hay presupuesto para la API de OpenAI durante el desarrollo, o se prioriza el modelo local?
3. ¿Existe alguna preferencia corporativa de stack (lenguaje, nube, base de datos)?
4. ¿La demo final será en local o desplegada en algún entorno compartido?

---

## 8. Actualización v0.3 · Modelos gratuitos (D-14)

| Uso | Proveedor | Modelo inicial | Límite relevante |
|---|---|---|---|
| Generación principal | Groq (nivel gratuito) | `openai/gpt-oss-120b` | 30 peticiones/min · 1.000/día · 200.000 tokens/día (por modelo) |
| Respaldo | OpenRouter (modelos `:free`) | Un modelo open-weight gratuito del catálogo vigente | 20 peticiones/min · 50/día sin créditos |
| Embeddings | Ollama local | bge-m3 | Solo CPU; sin límite |
| Tareas ligeras | Ollama local | Modelo pequeño según la RAM (R-08) | Solo CPU/iGPU |

- **Local en gráficos Intel integrados:** Ollama admite Vulkan (`OLLAMA_VULKAN=1`), pero la ganancia con iGPU es limitada. No es viable como generador principal por latencia (RNF-10) y calidad.
- **Descartados:** GPT-4o mini (de pago, no open source) y Claude (suscripción de API).
- **Verificar el día 1:** soporte de JSON Schema en Groq con gpt-oss y modelos `:free` disponibles en OpenRouter. En cualquier caso se valida con Pydantic y se reintenta (RNF-28).
- **Fuentes:** https://kdnuggets.com/5-free-llm-api-providers-you-can-use-in-2026 · https://blogs.novita.ai/free-llm-api-comparison-2026/ · https://www.phoronix.com/news/ollama-0.12.11-Vulkan

## 9. Fuentes consultadas

- LangGraph vs PydanticAI (human-in-the-loop): https://zenml.io/blog/pydantic-ai-vs-langgraph
- LangChain vs LlamaIndex 2026: https://addepto.com/blog/langchain-vs-llamaindex-main-differences/
- Chroma vs Qdrant vs pgvector (2026): https://chat2db.ai/resources/blog/chroma-vs-qdrant-vs-pgvector · https://techsy.io/en/blog/qdrant-vs-chroma-vs-pgvector
- Embeddings en Ollama: https://www.morphllm.com/ollama-embedding-models · https://registry.ollama.ai/library/qwen3-embedding
- Incidente de seguridad de LiteLLM (marzo 2026): https://letsdatascience.com/news/litellm-breach-exposes-ai-supply-chain-risk-69f3c6f7
- API tokens de Atlassian: https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/
- Búsqueda JQL en Jira Cloud: https://confluence.atlassian.com/display/JIRAKB/Run+JQL+search+query+using+Jira+Cloud+REST+API
- Estado de Chainlit: https://dev.co/ai/frameworks/chainlit
- Langfuse y ClickHouse: https://langfuse.com/blog/joining-clickhouse
- Docling y alternativas: https://dev.to/ashokan/from-pdfs-to-markdown-evaluating-document-parsers-for-air-gapped-rag-systems-58eh
- Precios de OpenAI (fuentes secundarias, a verificar en la oficial): https://morphllm.com/openai-api-pricing · https://benchlm.ai/openai/api-pricing
