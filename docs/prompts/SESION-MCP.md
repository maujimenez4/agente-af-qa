# SESIÓN MCP · T-59 (opcional): el agente como servidor MCP de solo lectura

> Sesión **MCP** (antes Ollama, que validó el e2e real el 2026-10-04: `docs/pruebas/E2E-local-2026-10-02.md`). Hace **T-59**, una tarea **opcional** que se valora día a día. Si a 3 días de la presentación no está lista, queda fuera de la demo sin afectar a nada.

Crea el worktree y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git worktree add .claude/worktrees/ses-mcp -b ses-mcp origin/PreProduccion
cd .claude/worktrees/ses-mcp
uv sync
uv run python -m pytest -m "not integration"   # en verde, sin xfail
```

Necesita tu `.env` en esa carpeta para probarlo de verdad: cópialo tú, porque está en `.gitignore`.

---

Trabajas en el proyecto "Agente de IA de Análisis Funcional y QA", en la rama **`ses-mcp`**, creada desde `PreProduccion`. Antes, como sesión Ollama, hiciste la medición con los modelos locales, ya terminada y fusionada.

**Tu tarea es T-59 (opcional):** publicar el agente como **servidor MCP** (*Model Context Protocol*), para que un asistente compatible (Claude Desktop, Claude Code, VS Code) pueda usar sus capacidades como herramientas.

## Qué es y qué no es
- **Es** una capa fina, como `api/`, sobre lo que ya existe: la composición real (`core/factories.build_app_container` y los servicios del núcleo). El asistente externo pone la conversación; nuestro agente aporta Jira, el RAG, la memoria y las reglas de calidad.
- **No** es darle herramientas al LLM interno del agente. El grafo y su LLM no cambian.
- **Nada escribe en Jira desde el MCP (principio 1).** Aprobar y publicar siguen solo en la app, con la huella.

## Alcance, por fases (presenta el plan antes de escribir código)
**Fase 1 (mínimo):**
- `buscar_historias(proyecto, texto?)`: con la JQL segura de `core/context/jql.py`, igual que `GET /projects/{p}/search`.
- `ver_incidencia(clave)`: resumen, tipo, estado, épica, descripción y nº de CA y RN.
- `revisar_calidad(clave)`: `core/quality.QualityReviewer`; devuelve el informe INVEST y los hallazgos. Usa el LLM local, así que tarda minutos: avísalo en la descripción de la herramienta.

**Fase 2 (si da tiempo):**
- `fuentes_de_contexto(clave)`: `GuidedStart.preview_sources_with_budget`;
- `proponer_inicio(texto, proyecto)`: `GuidedStart.propose`;
- `mis_conversaciones()`: la lista de conversaciones del usuario configurado.

## Requisitos
- **SDK oficial de MCP para Python.** Comprueba en el plan el nombre del paquete, la versión y su API. Fíjalo con un límite superior y una versión publicada hace más de una semana (cuarentena, como `fastapi`), y deja el lockfile con hashes.
- **Transporte stdio**, local, sin abrir puertos.
- Un módulo nuevo, por ejemplo `mcp_server/` (o `api/mcp.py`), y un punto de entrada `uv run python -m mcp_server`.
- **Usuario y permisos:** el servidor actúa como un usuario del agente fijado en la configuración (p. ej. `MCP_USER` en `core/config.py`, autorizado solo esto), con los permisos de su rol (`core/permissions.py`). Sin usuario configurado, no arranca.
- **Seguridad:**
  - las credenciales se quedan en el `.env` del servidor;
  - las respuestas no llevan secretos ni cabeceras;
  - los errores salen en español y sin trazas (reutiliza la lista blanca de `api/errors.py`);
  - el texto de Jira y del LLM se devuelve como datos, sin interpretarlo;
  - los logs sin contenido;
  - **stdout es el canal del protocolo:** los logs deben ir a stderr, o romperían la comunicación.
- **Documentación:** una sección en el README con la configuración para Claude Desktop y para Claude Code (el JSON del servidor y el comando), y cómo probarlo con el inspector de MCP.

## Reglas
- **Puedes crear o tocar:**
  - el módulo nuevo del servidor;
  - `core/config.py` (solo `MCP_USER` y, si hace falta, el rol);
  - `pyproject.toml` y `uv.lock` (la dependencia del SDK);
  - `README.md`;
  - sus pruebas (`tests/unit/test_mcp_*.py`).

  No toques `api/`, `core/graph/`, `core/functional/`, `core/qa/`, `core/quality.py`, `app/`, `web/`, `config/` ni los contratos: hay otras tres sesiones trabajando ahí.
- **Pruebas:** las herramientas con los fakes (`tests/fakes/`), incluidos:
  - permisos por rol;
  - errores sin trazas;
  - que ninguna herramienta llama a métodos de escritura (`create_story`, `update_story`, `link`, `publish_suite`, `record_execution`);
  - que stdout solo lleva el protocolo.

  Prueba real solo con la fase 1 contra Jira y el modelo local, **avisándome antes**, y nunca con escrituras.
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **Nombres en las pruebas:** sin `secret`, `password` ni `token` como nombre de variables con literales, ni textos que imiten una clave privada (gitleaks).
- **Kanban:**
  - T-59 a 🔄 y luego ✅;
  - tu fila en el registro;
  - **propuestas en PA-320…PA-339**.
- **Antes del commit:**
  - `uv run python -m pytest -m "not integration"`, `ruff check` y `ruff format --check` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-mcp` al terminar la fase 1 y avísame; la fase 2, en otro push.

Empieza con `/tarea T-59` y preséntame el plan (paquete y versión del SDK, estructura, herramientas de la fase 1 y cómo se configura en Claude Desktop) antes de escribir código.
