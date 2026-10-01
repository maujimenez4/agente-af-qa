# PROMPT-06 · Día 6 · T-24, PA-70 y T-28 (sesión del compañero)

Prepara el repositorio y pega todo lo que hay debajo de la línea como primer mensaje en Claude Code:

```bash
git fetch origin
git switch -c Dia6 origin/PreProduccion   # rama nueva: Dia5 ya está fusionada
uv sync
docker compose up -d db ollama
uv run alembic upgrade head               # llega hasta 0003 (tabla user_last_project)
uv run pytest -m "not integration"
```

---

Seguimos con el proyecto "Agente de IA de Análisis Funcional y QA". Estás en la rama **`Dia6`**, creada desde **`PreProduccion`**, que es la rama de integración: todo se fusiona en ella mediante PR, **nunca en `main`**.

## Qué ha cambiado desde `Dia5`
La sesión principal ha fusionado tu rama `Dia5` (T-23, T-26 y T-49) en `PreProduccion`, junto con:
- **T-49 cerrada:**
  - PA-69: el par norma ↔ acta pasa a `politicas ↔ documentacion`.
  - PA-71: los fakes usan ya las categorías nuevas.
  - El corpus está reindexado (28 documentos y 285 fragmentos) y medido: Recall@6 0,90 y MRR 0,95, igual que la línea base.
- **T-50 · proyecto en la conversación:**
  - `origin["project"]`;
  - `container.projects.available(user)` devuelve los proyectos visibles y el preseleccionado;
  - `container.projects.choose(user, clave)` al fijarlo;
  - `normalize_issue_key`/`normalize_project_key` en `core/projects.py` para lo que se escribe a mano.
- **T-51 · contrato de revisión.** Está en el anexo §11 de la SPEC y en `docs/specs/UI.md` §5, que ya está actualizado:
  - `initial_state(user, mode, origin, excluded_sources)`;
  - el payload de `human_review` trae `plan` y `error`;
  - nueva decisión `edit`;
  - una respuesta rechazada **no lanza**: vuelve a pausar con `error`.
- **PA-61:** el modo QA del grafo usa tu `TestWriter`.
- **`core/factories.build_app_container(config, router=None)`:** compone el contenedor real para la UI. Publicar casos (T-30) y la memoria (T-33) quedan como adaptadores «pendientes» que fallan con un mensaje claro; en simulación no se usan, y con `JIRA_PUBLISH_MODE=live` el contenedor no se compone (`ConfigError`).

Lee antes:
- `CLAUDE.md`;
- `docs/specs/UI.md` (tu documento, con §5 actualizado);
- el anexo §11 de `docs/specs/SPEC-00-fundacional.md` (versión 1.5);
- en `docs/KANBAN.md`, las «Decisiones del día 6» y las últimas filas del registro diario.

## Tareas de esta sesión
Hazlas con la skill del proyecto, **en este orden**.

### 1. `/tarea T-24`: UI «Propuesta mixta», pasos 1–5 [RF-14, RF-20, RF-42]
Área B: `app/`. Es la primera UI con código: **Streamlit** (D-04), punto de entrada `app/main.py` (`uv run streamlit run app/main.py`).

**Alcance:**
- **Login** con `container.auth.authenticate`. Permisos con `core/permissions.py`: `can` antes de mostrar y `require` antes de ejecutar.
- **Marco común:**
  - barra lateral de conversaciones;
  - aviso de modo de prueba si `container.publish_mode == "simulation"`.
- **Mixta 1 · Inicio:**
  - las cuatro tarjetas de flujo según el rol;
  - selector de proyecto con `container.projects`.
- **Mixta 1b · Elegir en Jira:** `list_projects`, `list_epics` y `list_children`, y búsqueda por clave.
- **Mixta 2 · Origen fijado:**
  - tarjeta «Operación fijada»;
  - restricciones opcionales, que van a `origin.text` en una necesidad y a `initial_state(..., feedback=[...])` en una evolución (UI.md §4);
  - fuentes con casillas que se pasan como `excluded_sources`.
- **Mixta 2b · Generando:** progreso por nodos con `graph.stream` (PA-66 queda para la sesión A).
- **Mixta 3 · Iterar:**
  - chat (`iterate`), versiones y pestañas Propuesta, Cambios, Impacto y Fuentes;
  - *Editar a mano* (`edit`) y *Descartar*;
  - mostrar `error` cuando llegue en la pausa.
- **Selector de modelo (RF-42):** crea el router con `core/factories.model_router(config)`, guárdalo en la sesión y pásalo a `build_app_container(config, router=router)`; `set_override` cambia el modelo de una tarea.

**Contrato con el grafo:**
- Compón **solo** con `build_app_container` y `build_graph(container)`. Nunca instancies adaptadores en `app/`. Al componer, captura `ConfigError` (configuración incompleta o `live`; no es `AgentError`) y `AgentError` (p. ej. Jira sin configurar) y muestra el mensaje.
- Un `thread_id` por conversación.
- Arranque: `graph.invoke(initial_state(...), config)`. Reanudar: `graph.invoke(Command(resume={...}), config)`.
- **La pausa se detecta por las interrupciones pendientes** (`__interrupt__` del resultado o `get_state(config).tasks[*].interrupts`), no por `next`.
- Devuelve siempre la huella del último payload.

**Lo que aún no hay en el backend.** Márcalo en la pantalla, sin inventar contratos:
- **T-52 · conversaciones persistentes:** usa `memory_checkpointer()`. La lista muestra solo las conversaciones de la sesión actual, y se pierden al reiniciar.
- **T-53 · arranque guiado:**
  - de momento, reconocer una clave escrita con `normalize_issue_key`;
  - la «HU parecida por texto» y la **vista previa de fuentes antes de generar** quedan como «disponible pronto».
  - Hasta T-53, el panel de fuentes con casillas se muestra en la pestaña *Fuentes* tras la primera versión; desmarcar abre una conversación nueva con `excluded_sources`.
- **Recibo de aprobación y resultado (Mixta 4):** son **T-31**, no los hagas. *Revisar y aprobar* puede quedar desactivado con «disponible en T-31».

**Animaciones (PA-44):** solo la Q de fase y la de «escribiendo», con SVG y CSS en `st.html`, respetando `prefers-reduced-motion`. Si algo no es viable, usa la alternativa estática de UI.md y anótalo como PA.

**Pruebas:**
- Saca la lógica de la UI a funciones puras en `app/` (construir el origen, el estado inicial y la respuesta del `resume`; leer el payload; elegir lo que ve cada rol) y pruébala con los fakes (`tests/fakes/container.fake_container`).
- Si te da tiempo, añade una prueba de humo con `streamlit.testing.v1.AppTest`.

### 2. PA-70: preguntas de evaluación para las categorías nuevas
Área B: `eval/`. Añade preguntas a `eval/retrieval_questions.yaml` para `productos`, `historias` y `pruebas` (DOC-23 … DOC-28) y anota la nueva línea base. La medición usa Ollama en local, no Groq:
```bash
uv run python -m core.rag.indexing    # solo si cambias el corpus
uv run python -m eval.retrieval_eval
```

### 3. Si terminas: `/tarea T-28`, pantallas QA 1 … QA 3
Estrategia de pruebas y pantallas de QA en `app/` (UI.md §6). Sin el recibo ni el resultado, que son T-31. El backend ya está: modo QA del grafo con `TestWriter`; la matriz sale de `suite.coverage_md()`.

## Reglas para que la fusión sea limpia
- **No toques:**
  - `core/` (salvo `core/rag/`, `core/functional/`, `core/qa/` y `core/memory/`, que son de tu área), `adapters/` ni `schemas/`;
  - los contratos congelados (`adapters/base.py`, `adapters/errors.py`, `core/config.py`, `core/container.py`) ni `core/factories.py`, que es de la sesión principal.

  Si la UI necesita algo del backend, **para** y déjalo propuesto (PA) o avísame.
- **Kanban:**
  - Cambia solo el estado de las filas de T-24, T-28 y PA-70.
  - Añade tu propia fila al registro diario (día 6).
  - No toques el tablero resumen.
  - **Numera tus propuestas desde PA-72.**
- **Seguridad:**
  - Nada de secretos, del contenido del `.env` ni de datos personales reales.
  - Solo se escribe en Jira desde el nodo `publish`; la UI nunca llama a métodos de escritura.
  - Deja `JIRA_PUBLISH_MODE=simulation`.
  - Los logs no registran prompts ni contenido.
- El contenido de Jira, del RAG y del LLM **no es fiable**: nunca va a `st.html` ni a `st.markdown(..., unsafe_allow_html=True)`. Muéstralo como texto o markdown sin HTML; `st.html` es solo para los SVG y CSS propios de las animaciones.
- **Cuota de Groq:**
  - Las pruebas automáticas usan fakes.
  - Si pruebas la app a mano con el LLM real, hazlo con pocas generaciones y avísame de cuántas.
  - Las pruebas `integration` con LLM no se lanzan sin preguntarme.
- Pasa `spec-checker` y `security-reviewer` hasta CONFORME y APTO, con `uv run pytest -m "not integration"`, `uv run ruff check .` y `uv run ruff format --check .` en verde.
- **Commits:**
  - Formato `T-XX: descripción [RF-YY]`.
  - Sube la rama con `git push -u origin Dia6` y abre un PR por tarea contra `PreProduccion`.

Empieza por `/tarea T-24` y preséntame el plan antes de escribir código.
