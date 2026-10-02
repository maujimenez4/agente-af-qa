# Modelo C4 · Agente de IA de AF y QA

Modelo C4 en tres niveles (contexto, contenedores y componentes), estado a 2026-10-02 tras la D-04 revisada. La fuente de verdad sigue siendo `docs/specs/SPEC-00-fundacional.md`; el contrato de la API está en `docs/api/openapi.yaml`. La vista simplificada está en `docs/arquitectura.md`.

## Nivel 1 · Contexto del sistema

```mermaid
C4Context
    title Contexto · Agente de IA de Análisis Funcional y QA

    Person(af, "Analista funcional", "Crea, evoluciona y revisa Historias de Usuario")
    Person(qa, "QA", "Genera y aprueba suites de prueba de una HU")
    Person(admin, "Administrador", "Gestiona conexiones, modelos y documentos")

    System(agent, "Agente de IA de AF y QA", "Genera HU y artefactos de QA con contexto de Jira y del RAG; publica solo lo aprobado")

    System_Ext(jira, "Jira Cloud", "Épicas, HU, subtareas de casos de prueba, adjuntos y vínculos")
    System_Ext(llm, "Modelos de IA", "Open-weight y gratuitos; hoy Ollama local")

    Rel(af, agent, "Genera y aprueba HU")
    Rel(qa, agent, "Genera y aprueba suites de prueba")
    Rel(admin, agent, "Configura y carga documentos")
    Rel(agent, jira, "Lee contexto; publica lo aprobado", "REST v3")
    Rel(agent, llm, "Pide salidas estructuradas", "API compatible con OpenAI")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Nivel 2 · Contenedores

```mermaid
C4Container
    title Contenedores · Agente de IA de AF y QA

    Person(user, "Analista funcional / QA / Administrador")

    System_Boundary(sys, "Agente de IA de AF y QA") {
        Container(web, "Frontend web", "React, TypeScript, Vite (web/)", "Pantallas de la «Propuesta mixta»: conversaciones, revisión y aprobación, QA")
        Container(api, "API HTTP", "Python, FastAPI (api/)", "Sesión con cookie y CSRF, conversaciones, progreso por SSE, aprobar con huella")
        Container(st, "UI Streamlit (plan B)", "Python, Streamlit (app/)", "Alternativa hasta el punto de control T-57")
        Container(core, "Núcleo del agente", "Python, LangGraph", "Grafo de generación, contexto, validación, aprobación y publicación")
        ContainerDb(db, "Base de datos", "PostgreSQL + pgvector", "Usuarios, artefactos y versiones, auditoría, conversaciones, documentos y fragmentos del RAG")
        Container(files, "Corpus y memorias", "Archivos .md / .pdf / .docx", "Documentos de la base de conocimiento y memorias de HU publicadas")
    }

    System_Ext(jira, "Jira Cloud", "REST v3")
    System_Ext(llm, "Modelos de IA", "Ollama local (Docker)")

    Rel(user, web, "Usa", "HTTPS")
    Rel(web, api, "Llama", "JSON + SSE")
    Rel(api, core, "Invoca el grafo y reanuda la revisión", "en proceso")
    Rel(st, core, "Plan B", "en proceso")
    Rel(core, db, "Lee y escribe", "SQL / búsqueda híbrida")
    Rel(core, files, "Ingesta y genera memorias")
    Rel(core, jira, "Lee contexto; escribe solo desde publish", "HTTPS")
    Rel(core, llm, "Generación y embeddings", "HTTP")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

La API y el núcleo se ejecutan en el mismo proceso de Python; se separan aquí porque tienen responsabilidades distintas. El frontend nunca habla con Jira ni con el LLM: solo con la API. PostgreSQL y Ollama se levantan con Docker Compose.

## Nivel 3 · Componentes del núcleo del agente

```mermaid
C4Component
    title Componentes · Núcleo del agente

    Container(api, "API HTTP", "FastAPI")

    Container_Boundary(core, "Núcleo del agente") {
        Component(graph, "Orquestador", "core/graph · LangGraph", "load_origin → retrieve_context → generate → human_review → publish → memorize")
        Component(context, "Servicio de contexto", "core/context", "Reúne Jira y RAG con presupuesto de tokens")
        Component(writers, "Generadores", "core/functional, core/qa", "StoryWriter (HU, revisión de calidad) y TestWriter (suites) con validación")
        Component(impact, "Análisis de impacto", "core/impact", "Diff entre versiones y HU afectadas")
        Component(control, "Control y aprobación", "state_machine, approvals, audit", "Estados, huella de lo aprobado y auditoría")
        Component(convs, "Conversaciones", "core/conversations, guided_start, projects", "Persistencia, arranque guiado y proyecto por conversación")
        Component(rag, "RAG", "core/rag", "Ingesta, fragmentado e indexado")
        Component(memory, "Memoria", "core/memory", "Resumen .md de cada HU publicada")
        Component(adapters, "Adaptadores", "adapters/*", "Jira (lectura y escritura), casos de prueba, LLM con respaldo, vector store, embeddings, autenticación")
    }

    ContainerDb(db, "Base de datos", "PostgreSQL + pgvector")
    System_Ext(jira, "Jira Cloud")
    System_Ext(llm, "Modelos de IA")

    Rel(api, graph, "Arranca y reanuda")
    Rel(api, convs, "Lista y retoma")
    Rel(graph, context, "Pide contexto")
    Rel(graph, writers, "Genera")
    Rel(writers, impact, "Evoluciones")
    Rel(graph, control, "Valida la aprobación")
    Rel(graph, memory, "Tras publicar")
    Rel(memory, rag, "Reindexa")
    Rel(context, adapters, "Usa")
    Rel(writers, adapters, "Usa")
    Rel(rag, adapters, "Usa")
    Rel(adapters, jira, "REST v3")
    Rel(adapters, llm, "API compatible con OpenAI")
    Rel(adapters, db, "SQL")
    Rel(control, db, "Audita")
    Rel(convs, db, "Checkpointer y conversaciones")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

El núcleo depende solo de los protocolos de `adapters/base.py`; qué implementación se usa se decide en `core/container.py` y `core/factories.py`.
