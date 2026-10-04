# Agente de IA de Análisis Funcional y QA

MVP de un agente que genera y evoluciona Historias de Usuario y artefactos de QA desde Jira Cloud y una base de conocimiento RAG, con aprobación humana antes de publicar en Jira.

## Instalación desde cero

### Requisitos
- **Git** y **[uv](https://docs.astral.sh/uv/)** (instala Python 3.12 por su cuenta con `uv sync`).
- **Docker** con Compose v2 (en Windows, Docker Desktop con WSL 2) para PostgreSQL + pgvector y Ollama.
- Unos **10 GB de disco** (imágenes y modelos) y **16 GB de RAM** recomendados: los modelos locales corren en CPU.
- Un proyecto de **Jira Cloud** de pruebas y un token de API (solo lectura basta en modo `simulation`).
- **Windows: rutas cortas.** Algunas dependencias tienen nombres de archivo muy largos y, con el límite de 260 caracteres, la instalación queda rota sin avisar (`ModuleNotFoundError` en `langsmith`). Clona en una ruta corta (por ejemplo `C:\src\agente-af-qa`) o activa las rutas largas de Windows y `git config --global core.longpaths true`.

### Pasos
```bash
# 1. Código y dependencias (crea .venv con el lockfile)
git clone <repositorio> agente-af-qa && cd agente-af-qa
uv sync

# 2. Configuración: copia la plantilla y rellena TUS valores (nunca se versiona)
cp .env.example .env
#    JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY  → tu Jira de pruebas
#    JIRA_PUBLISH_MODE=simulation                                → nada se escribe en Jira
#    OLLAMA_BASE_URL, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, DATABASE_URL
#    Sin claves de Groq ni OpenRouter: config/models.yaml usa solo modelos locales (D-14).

# 3. Servicios: PostgreSQL + pgvector y Ollama (perfil local-llm)
docker compose --profile local-llm up -d db ollama

# 4. Modelos de config/models.yaml (generación, respaldo y embeddings)
docker compose exec ollama ollama pull qwen3:1.7b
docker compose exec ollama ollama pull phi4-mini
docker compose exec ollama ollama pull bge-m3

# 5. Base de datos: migraciones hasta la 0006 (quality_reviews, PA-272)
uv run alembic upgrade head

# 6. Conocimiento: indexa el corpus sintético de data/seed/corpus (solo embeddings)
uv run python -m core.rag.indexing

# 7. Usuarios locales af-demo, qa-demo y admin-demo
uv run python -m core.seed_users        # las contraseñas se muestran UNA vez: guárdalas

# 8. Arrancar: API para el frontend (http://127.0.0.1:8000/api/v1) y/o la UI en Streamlit
uv run python -m api                    # un solo proceso: las sesiones viven en memoria
uv run streamlit run app/main.py        # http://localhost:8501

# 9. Pruebas
uv run pytest -m "not integration"      # sin servicios externos
uv run pytest -m integration            # contra PostgreSQL, Jira y Ollama reales (requiere .env)
uv run ruff check . && uv run ruff format --check .
```

- El proyecto de Jira se siembra a mano desde el navegador con `data/seed/jira/seed-villaficticia.csv` (ver su `README.md`); el agente nunca escribe en Jira salvo al publicar lo aprobado y solo en `JIRA_PUBLISH_MODE=live`.
- Volver a ejecutar `core.seed_users` cambia las contraseñas de los usuarios de demo.
- En CPU, una HU tarda unos 5–6 minutos con `qwen3:1.7b`. Para la demo hay conversaciones preparadas: `docs/demo/GUION.md`, `docs/demo/CHECKLIST.md` y `uv run python -m eval.demo_prepare`.

**Comprobado en un clon limpio sin `.env`** (2026-10-02, Windows 11): `uv sync`, la migración en modo offline (`uv run alembic upgrade head --sql`, llega a `0005_qa_handoffs`) y `uv run pytest -m "not integration"` en verde. Los pasos 3–8 necesitan Docker, Jira y Ollama con un `.env` propio y no se probaron en ese clon.

### Ollama: modelos cargados (`keep_alive`)
El servicio `ollama` de `docker-compose.yml` mantiene el modelo en memoria **30 minutos** después de la última llamada (`OLLAMA_KEEP_ALIVE`, PA-275); sin eso se descarga a los 5 minutos y la siguiente llamada paga la carga. Además limita a **dos modelos cargados** a la vez (`OLLAMA_MAX_LOADED_MODELS=2`): en el e2e del 2026-10-02 hubo OOM con 7,6 GiB para Docker. Se recomienda dar **10 GB a WSL2** (`%UserProfile%\.wslconfig` con `[wsl2]` y `memory=10GB`, y después `wsl --shutdown`). Para otros valores, añádelos a tu `.env`. **Se aplica al recrear el contenedor**, no en caliente:
```bash
docker compose --profile local-llm up -d ollama     # lo recrea si cambió la configuración
docker compose exec ollama ollama ps                 # modelos cargados y hasta cuándo (UNTIL)
```
Recrearlo corta las llamadas en curso: hazlo cuando nadie esté usando el modelo.

### API en Docker (sin instalar Python)
Para quien solo necesita la API (por ejemplo, el frontend en React), el perfil `full` la arranca en un contenedor (PA-273):
```bash
cp .env.example .env                                          # tus valores; nunca entra en la imagen
docker compose --profile local-llm up -d db ollama            # pasos 3 y 4 de arriba
docker compose --profile full build app                       # varios GB: torch y docling
docker compose --profile full run --rm app alembic upgrade head
docker compose --profile full run --rm app python -m core.rag.indexing
docker compose --profile full run --rm app python -m core.seed_users
docker compose --profile full up -d app                       # http://127.0.0.1:8000/api/v1
```
- La imagen se construye con el lockfile (`uv sync --frozen`), sin dependencias de desarrollo y con un usuario no root. El `.env` no se copia (`.dockerignore`): llega al arrancar con `env_file`.
- Dentro de Compose, la API usa `db` y `ollama` en lugar de `localhost`: `docker-compose.yml` fija `POSTGRES_HOST=db` y `OLLAMA_BASE_URL`, y deja `DATABASE_URL` vacía para anular la del `.env`. La app compone la URL con `POSTGRES_HOST`, `POSTGRES_PORT` y `POSTGRES_USER`, `POSTGRES_PASSWORD` y `POSTGRES_DB` de tu `.env`, y codifica la contraseña: los caracteres especiales (`@`, `/`, `:`, `#`, `?`) ya no rompen la conexión (PA-278).
- Fuera de Compose, si no defines `DATABASE_URL`, la app usa `POSTGRES_HOST` (por defecto `127.0.0.1`) y `POSTGRES_PORT` (por defecto `5432`). Si defines `DATABASE_URL`, manda ella.
- El puerto solo se publica en `127.0.0.1`: la API no queda expuesta a la red.

### Conservación de datos (RGPD)
Las revisiones de calidad se guardan en `quality_reviews` con el informe que genera el LLM a partir de la HU de Jira (PA-279):
- **Plazo:** se conservan `QUALITY_RETENTION_DAYS` días (90 por defecto, en tu `.env`) desde su último cambio. La API borra las caducadas **al arrancar**, y también a mano:
  ```bash
  uv run python -m core.quality --purgar
  ```
- **Baja de una persona:** deja la cuenta inactiva (con una contraseña aleatoria que no se muestra) y borra sus revisiones de calidad. Por ahora solo para los usuarios de demo del seed (`af-demo`, `qa-demo`, `admin-demo`):
  ```bash
  uv run python -m core.seed_users --baja af-demo
  ```
- Ninguno de los dos comandos muestra el contenido de las revisiones: solo cuántas se borraron.
- **Tras una baja, reinicia la API:** las sesiones abiertas viven en su memoria y no vuelven a comprobar si la cuenta está activa, así que una sesión ya iniciada seguiría valiendo hasta caducar (30 min sin actividad o 12 h).

### Servidor MCP de solo lectura (T-59, opcional)
El agente se puede usar como **servidor MCP** (*Model Context Protocol*) desde un asistente compatible, como Claude Desktop, Claude Code o VS Code. Es una capa fina sobre los servicios del agente, igual que la API:

| Herramienta | Qué hace | Rol necesario |
|---|---|---|
| `buscar_historias(proyecto, texto?, limite?)` | HU y épicas de un proyecto de Jira por texto o por clave; sin texto, las recientes | `functional` o `qa` |
| `ver_incidencia(clave)` | Resumen, tipo, estado, épica, descripción y número de CA y RN (sin IA) | `functional` o `qa` |
| `revisar_calidad(clave)` | Informe INVEST, hallazgos y preguntas abiertas, con fuentes. **Usa el modelo local: tarda varios minutos** | `functional` |
| `fuentes_de_contexto(clave)` | Fuentes de Jira, del RAG y de la memoria que usaría el agente para esa HU, con el presupuesto de tokens (cuántas entran). Sin IA | `functional` o `qa` |
| `proponer_inicio(texto, proyecto)` | Con qué empezar a partir de un texto: claves reconocidas (también en minúsculas) o HU parecidas, con sus opciones según el rol. Sin IA; no crea nada | `functional` (HU) o `qa` (pruebas) |
| `mis_conversaciones(limite?)` | Conversaciones del usuario configurado: título, proyecto, modo, origen, estado y versión. Para continuarlas o aprobar, la aplicación | `functional` o `qa` |

- **Nada escribe en Jira.** Aprobar y publicar solo se hace en la aplicación, con la huella. Además, un proxy de solo lectura (lista blanca) solo deja pasar las lecturas de Jira, del RAG, de las conversaciones y del último proyecto usado.
- Usa transporte **stdio** local: no abre puertos. stdout es el canal del protocolo y los logs van a stderr, sin contenido.
- **Actúa como un usuario del agente** fijado en el `.env`: `MCP_USER` (sin él no arranca) y `MCP_ROLE` (`functional` o `qa`). Las credenciales de Jira y de la BD se quedan en ese `.env`: el asistente no las ve.
- El texto de Jira y del modelo se devuelve como datos, no como instrucciones. Los errores salen en español y sin trazas.
- Requisitos: los mismos que la API (pasos 1–4 de arriba: `.env`, `db`, `ollama` y migraciones).

**Arrancarlo a mano** (se queda esperando mensajes por stdin; `Ctrl+C` para salir):
```bash
uv run python -m mcp_server
```

**Claude Desktop** (`claude_desktop_config.json`; en Windows, `%APPDATA%\Claude\claude_desktop_config.json`). Pon la ruta absoluta de tu copia del repositorio:
```json
{
  "mcpServers": {
    "agente-af-qa": {
      "command": "uv",
      "args": ["run", "--directory", "C:/ruta/a/agente-af-qa", "python", "-m", "mcp_server"]
    }
  }
}
```
Reinicia Claude Desktop después de guardar. No hace falta poner variables en `env`: el servidor lee el `.env` de esa carpeta.

**Claude Code**, desde la carpeta del repositorio. Con `--scope project` se guarda en `.mcp.json`, sin rutas ni secretos, y sirve a todo el equipo, porque Claude Code arranca el servidor en la carpeta del proyecto:
```bash
claude mcp add --scope project agente-af-qa -- uv run python -m mcp_server
claude mcp list                                      # comprueba que conecta
```
Solo para ti y desde cualquier carpeta (ámbito personal, con la ruta absoluta de tu copia):
```bash
claude mcp add agente-af-qa -- uv run --directory "C:/ruta/a/agente-af-qa" python -m mcp_server
```
Dentro de Claude Code, `/mcp` muestra el estado y las herramientas.

**Probarlo con el inspector de MCP** (necesita Node.js; abre una página local para llamar a cada herramienta):
```bash
npx @modelcontextprotocol/inspector uv run python -m mcp_server
```

## Contenido
| Archivo | Para qué sirve |
|---|---|
| `CLAUDE.md` | Contexto, principios, áreas y convenciones que leen todas las sesiones de Claude Code |
| `docs/specs/SPEC-00-fundacional.md` | Contratos: esquemas, interfaces, grafo, base de datos y configuración |
| `docs/KANBAN.md` | 46 tareas en 10 + 5 días, con sincronización diaria |
| `docs/decisiones/` | Declaraciones del proyecto (v0.3) e investigación tecnológica (v0.2) |
| `docs/prompts/` | Prompts para arrancar cada sesión de Claude Code |
| `.claude/agents/` | Subagentes `test-writer`, `security-reviewer` y `spec-checker` |
| `config/models.yaml` | Asignación de modelos por tarea (sin secretos) |
| `.env.example` | Plantilla de variables de entorno (solo placeholders) |

## Cómo trabajar (una persona, tres sesiones)

**Día 1 · Sesión principal**
```bash
git init && git add . && git commit -m "T-00: paquete de arranque"
cp .env.example .env        # rellénalo tú; nunca se versiona
claude                      # en main → pega docs/prompts/PROMPT-01-dia1.md
```
Mientras Claude construye la base, haz tú la T-08 (Jira, token y claves de LLM).

**Días 2–9 · Dos worktrees en paralelo**
```bash
claude --worktree area-a    # Integraciones y núcleo
claude --worktree area-b    # Conocimiento y UI
```
En cada worktree nuevo, ejecuta `uv sync` antes de nada. Al final de cada día: fusiona en `main` con las pruebas en verde, verifica el hito de sincronización del Kanban y haz rebase de los worktrees.

**Día 10 · Prueba cruzada y v1.0.** **Días 11–15 · v1.1 y demo final.**

## Principios
La IA propone, el usuario valida y Jira conserva solo resultados aprobados. Sin secretos en el código. Solo datos sintéticos.
