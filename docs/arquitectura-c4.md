# Modelo C4 · Agente de IA de AF y QA

Modelo C4 en tres niveles, más una vista dinámica (estado a 2026-10-08). La vista simple para explicarlo está en `docs/arquitectura.md`. La fuente de verdad es `docs/specs/SPEC-00-fundacional.md`, y el contrato de la API, `docs/api/openapi.yaml`.

**Cómo leer los diagramas:** cada nivel amplía una caja del anterior. Se dibujan como diagramas de flujo con la notación y los colores de C4 (el tipo `C4` de Mermaid coloca mal las cajas).

| Color | Elemento C4 |
|---|---|
| Azul oscuro | Persona |
| Azul | Nuestro sistema o uno de sus contenedores |
| Azul claro | Componente dentro de un contenedor |
| Gris | Sistema externo |

## Nivel 1 · Contexto

Quién usa el sistema y con qué sistemas externos habla.

```mermaid
flowchart TB
    af(["<b>Analista funcional</b><br/>crea, evoluciona y revisa HU"])
    qa(["<b>QA</b><br/>genera suites y registra la ejecución"])
    admin(["<b>Administrador</b><br/>conexiones y modelos"])
    asis["<b>Asistente de IA</b><br/>Claude Desktop, Claude Code, VS Code<br/><i>sistema externo</i>"]

    sys["<b>Agente de IA de AF y QA</b><br/>genera HU y artefactos de QA con el contexto de Jira<br/>y de la base de conocimiento, y publica solo lo aprobado"]

    jira["<b>Jira Cloud</b><br/>épicas, HU, casos de prueba como subtareas,<br/>adjuntos y vínculos<br/><i>sistema externo</i>"]
    groq["<b>Groq</b><br/>modelos open-weight en la nube, nivel gratuito<br/>(gpt-oss-120b, gpt-oss-20b)<br/><i>sistema externo</i>"]
    llm["<b>Ollama</b><br/>modelos open-weight en el propio equipo<br/>(qwen3:1.7b, phi4-mini, bge-m3)<br/><i>sistema externo</i>"]
    lf["<b>Langfuse Cloud</b><br/>trazas, tokens y latencias<br/><i>sistema externo</i>"]

    af -- "genera y aprueba HU" --> sys
    qa -- "genera y aprueba suites" --> sys
    admin -- "comprueba y configura" --> sys
    asis -- "consulta (MCP, solo lectura)" --> sys
    sys -- "lee contexto y publica lo aprobado<br/>[REST v3]" --> jira
    sys -- "HU, evolución, calidad, impacto y memoria<br/>[API compatible con OpenAI]" --> groq
    sys -- "QA, embeddings y respaldo de todo<br/>[API compatible con OpenAI]" --> llm
    sys -. "envía trazas [HTTPS]" .-> lf

    classDef persona fill:#08427b,stroke:#052e56,color:#fff
    classDef sistema fill:#1168bd,stroke:#0b4884,color:#fff
    classDef externo fill:#6b6b6b,stroke:#4a4a4a,color:#fff
    class af,qa,admin persona
    class sys sistema
    class asis,jira,groq,llm,lf externo
```

**Modelos (D-14, PA-443):** solo open-weight y gratuitos. La configuración por defecto es mixta; `config/models.todo-local.yaml` deja todo en Ollama y ninguna llamada sale del equipo (`config/README.md`).

## Nivel 2 · Contenedores

Qué piezas ejecutables y almacenes forman el sistema.

```mermaid
flowchart TB
    user(["<b>Analista funcional / QA / Administrador</b>"])
    asis["<b>Asistente de IA</b><br/><i>externo</i>"]

    subgraph SYS["Agente de IA de AF y QA"]
        direction TB
        web["<b>Web</b><br/>[React, TypeScript, Vite · web/]<br/>pantallas de la «Propuesta mixta»"]
        st["<b>UI Streamlit</b> · plan B<br/>[Python, Streamlit · app/]<br/>los dos flujos completos"]
        api["<b>API HTTP</b><br/>[Python, FastAPI · api/]<br/>sesión con cookie y CSRF, progreso por SSE,<br/>aprobar con huella, detener y reintentar"]
        mcp["<b>Servidor MCP</b><br/>[Python, SDK mcp · mcp_server/]<br/>6 herramientas de solo lectura"]
        core["<b>Núcleo del agente</b><br/>[Python, LangGraph · core/ + adapters/]<br/>grafos, contexto, generación, validación,<br/>aprobación y publicación"]
        db[("<b>Base de datos</b><br/>[PostgreSQL + pgvector]<br/>usuarios, conversaciones, versiones,<br/>aprobaciones, auditoría, uso del LLM,<br/>documentos y fragmentos del RAG")]
        files[("<b>Archivos</b><br/>[.md, .pdf, .docx]<br/>corpus y memorias de HU")]
    end

    jira["<b>Jira Cloud</b><br/><i>externo</i>"]
    groq["<b>Groq</b><br/><i>externo</i><br/>gpt-oss-120b, gpt-oss-20b"]
    llm["<b>Ollama</b><br/>[Docker]<br/>qwen3:1.7b, phi4-mini, bge-m3"]
    lf["<b>Langfuse Cloud</b><br/><i>externo</i>"]

    user -- "usa [HTTPS]" --> web
    user -- "usa" --> st
    asis -- "stdio" --> mcp
    web -- "JSON + SSE [/api/v1]" --> api
    api -- "en proceso" --> core
    st -- "en proceso" --> core
    mcp -- "en proceso, solo lecturas" --> core
    core -- "SQL y búsqueda híbrida" --> db
    core -- "ingesta y memorias" --> files
    core -- "lee, y escribe solo desde publish [REST v3]" --> jira
    core -- "generación (HU, calidad, memoria) [HTTPS]" --> groq
    core -- "generación (QA, respaldo) y embeddings [HTTP]" --> llm
    core -. "trazas [OTLP/HTTPS]" .-> lf

    classDef persona fill:#08427b,stroke:#052e56,color:#fff
    classDef contenedor fill:#438dd5,stroke:#2e6295,color:#fff
    classDef externo fill:#6b6b6b,stroke:#4a4a4a,color:#fff
    class user persona
    class web,st,api,mcp,core,db,files contenedor
    class asis,jira,groq,llm,lf externo
```

- **Un solo proceso de Python por entrada:** la API, Streamlit y el servidor MCP cargan el núcleo como biblioteca. Se dibujan por separado porque tienen responsabilidades distintas.
- **La web** solo habla con la API, nunca con Jira ni con los modelos.
- **El servidor MCP** envuelve Jira con un proxy que solo deja pasar lecturas.
- **Docker Compose** levanta PostgreSQL y Ollama; la API tiene además su propia imagen (perfil `full`).
- **Cadena de modelos:** cada tarea tiene un modelo principal y un respaldo. Ante un 429 de Groq se espera hasta 60 s; si la petición no cabe en su límite por minuto (413), se pasa al local sin reintentar. Los límites (ventana, presupuesto de contexto y topes de salida) son por proveedor.

## Nivel 3 · Componentes del núcleo

Qué hay dentro del contenedor «Núcleo del agente», agrupado por responsabilidad.

```mermaid
flowchart TB
    entradas["<b>API · Streamlit · MCP</b><br/><i>contenedores</i>"]

    subgraph CORE["Núcleo del agente"]
        direction TB

        subgraph ORQ["Orquestación"]
            direction LR
            maingraph["<b>Grafo principal</b><br/>core/graph<br/>origen → contexto → generar →<br/>revisión humana → publicar → memoria"]
            exec["<b>Grafo de ejecución</b><br/>core/graph/execution<br/>casos → revisión → registrar en Jira"]
            convs["<b>Conversaciones</b><br/>conversations, guided_start,<br/>projects, handoff (QA encadenada)"]
        end

        subgraph INT["Inteligencia"]
            direction LR
            ctx["<b>Contexto</b><br/>core/context<br/>Jira + RAG + memorias<br/>con presupuesto de tokens"]
            writers["<b>Generadores</b><br/>core/functional, core/qa, quality<br/>HU, suites y revisión INVEST,<br/>con validación y citas"]
            impact["<b>Impacto</b><br/>core/impact<br/>cambios frente a Jira<br/>y HU afectadas"]
            mem["<b>Memoria</b><br/>core/memory<br/>resumen de cada HU publicada"]
            rag["<b>RAG</b><br/>core/rag<br/>ingesta, fragmentos,<br/>índice y prompts"]
        end

        subgraph CTL["Control"]
            direction LR
            appr["<b>Aprobaciones</b><br/>approvals, state_machine<br/>huella de lo aprobado"]
            audit["<b>Auditoría y permisos</b><br/>audit, permissions,<br/>personal_data"]
        end

        subgraph SOP["Soporte"]
            direction LR
            trace["<b>Trazas</b><br/>core/tracing"]
            usage["<b>Uso y salud</b><br/>usage, health"]
            comp["<b>Composición</b><br/>config, container, factories"]
        end

        adapters["<b>Adaptadores</b> · adapters/<br/>Jira (lectura y publicación) · casos de prueba · LLM con cadena de respaldo ·<br/>embeddings · vector store · autenticación · Langfuse<br/><i>el núcleo solo conoce sus protocolos (adapters/base.py)</i>"]
    end

    db[("PostgreSQL + pgvector")]
    jira["Jira Cloud"]
    groq["Groq"]
    llm["Ollama"]
    lf["Langfuse Cloud"]

    entradas --> ORQ
    maingraph --> ctx & writers & appr
    writers --> impact
    maingraph -- "tras publicar" --> mem
    mem --> rag
    ctx --> rag
    exec --> appr
    ORQ & INT --> adapters
    CTL --> db
    adapters --> db & jira & groq & llm
    adapters -.-> lf

    classDef componente fill:#85bbf0,stroke:#5d82a8,color:#000
    classDef contenedor fill:#438dd5,stroke:#2e6295,color:#fff
    classDef externo fill:#6b6b6b,stroke:#4a4a4a,color:#fff
    class maingraph,exec,convs,ctx,writers,impact,mem,rag,appr,audit,trace,usage,comp,adapters componente
    class entradas,db contenedor
    class jira,groq,llm,lf externo
```

- **Orquestación:**
  - el grafo principal sirve para los dos modos (HU y QA) y se pausa en la revisión humana; el estado se guarda en PostgreSQL, así que una conversación se puede retomar;
  - el grafo de ejecución registra en Jira el resultado de cada caso de prueba (T-47).
- **Inteligencia:**
  - los generadores piden al modelo una salida con un esquema fijo (`schemas/`) y validan los identificadores y las citas;
  - los prompts están en `prompts/<tarea>.md` con su versión.
- **Control:** el único escritor en Jira es el paso `publish`, y exige la huella de lo aprobado; cada decisión queda auditada.
- **Adaptadores:** el núcleo depende solo de los protocolos de `adapters/base.py`; qué implementación se usa se decide en `core/container.py` y `core/factories.py`. En las pruebas, los mismos protocolos tienen dobles en `tests/fakes/`.

## Vista dinámica · Evolucionar una HU

El recorrido de una operación real, desde la web hasta Jira.

```mermaid
sequenceDiagram
    autonumber
    actor AF as Analista funcional
    participant W as Web / Streamlit
    participant A as API
    participant G as Grafo principal
    participant J as Jira Cloud
    participant R as RAG (pgvector)
    participant M as Modelo (Groq; Ollama de respaldo)

    AF->>W: elige la HU y pulsa «Generar»
    W->>A: POST /conversations
    A-->>W: 202 · progreso por SSE
    A->>G: arranca el grafo
    G->>J: lee la HU, sus vínculos y su épica
    G->>R: busca documentos y memorias
    G->>M: pide la HU evolucionada (salida estructurada)
    M-->>G: HU propuesta
    G->>G: valida identificadores y citas, y calcula el impacto
    G-->>W: propuesta en revisión (con la versión de Jira para comparar)
    AF->>W: pide un cambio
    W->>A: POST /iterate
    A->>G: vuelve a generar con la petición
    G-->>W: nueva versión en revisión
    AF->>W: aprueba
    W->>A: POST /approve con la huella
    A->>G: publicar
    G->>J: actualiza la HU (o lo simula)
    G->>R: memoria de la HU (solo en publicación real)
    G-->>W: resultado
```

Cada operación deja además una traza en Langfuse con sus pasos, sus llamadas al modelo y la búsqueda en el RAG.
