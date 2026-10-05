# Backend local para probar `web/` contra la API real (Windows · WSL 2 · Docker)

Guía para levantar la API de T-55 en este equipo y recorrer el frontend con ella. La referencia completa está en el `README.md` de la raíz y en `docs/api/README.md`; aquí solo va lo que necesita el frontend.

> **Reglas:** el `.env` y las contraseñas del seed **nunca** se copian en el chat, en la PR, en un commit ni en capturas. `JIRA_PUBLISH_MODE` se queda en `simulation`: nada se escribe en Jira.

## 0. Comprobaciones previas
En PowerShell:

```powershell
wsl -l -v                  # una distribución con VERSION 2 (si sale 1: wsl --set-version <distro> 2)
docker --version           # Docker Desktop con el motor WSL 2
docker compose version     # Compose v2 («docker compose», sin guion)
uv --version               # ya instalado; Python 3.12 lo gestiona uv
```

- **Python:** ya está. `uv python install 3.12` y `uv sync` funcionan sin administrador; se comprobó el 2026-10-05.
- **Memoria para WSL:** si vas a usar Ollama, da 10 GB a WSL 2. Para eso, crea `%UserProfile%\.wslconfig` con `[wsl2]` y `memory=10GB`, y ejecuta `wsl --shutdown`. Con menos memoria hubo cortes por falta de memoria (OOM).
- **Puertos libres en `127.0.0.1`:** 5432 (PostgreSQL), 11434 (Ollama), 8000 (API) y 5173 (Vite).

## 1. Servicios con Docker Compose
Desde la raíz del repositorio:

```powershell
docker compose up -d db                                  # PostgreSQL 16 + pgvector
docker compose --profile local-llm up -d db ollama       # y además Ollama (perfil local-llm)
docker compose exec ollama ollama pull bge-m3            # embeddings: el RAG lo necesita siempre
docker compose exec ollama ollama pull qwen3:1.7b        # generación en local (si no usas Groq u OpenRouter)
docker compose exec ollama ollama pull phi4-mini         # respaldo en local
```

**Ollama en local o un proveedor gratuito (D-14):**

| | Ollama (perfil `local-llm`) | Groq u OpenRouter |
|---|---|---|
| Coste | CPU al 100 % mientras genera, unos 10 GB de memoria y varios GB de modelos en disco | Nada en local; solo hace falta una clave gratuita |
| Tiempo por HU | Unos 5–6 minutos en CPU con `qwen3:1.7b` | Segundos o decenas de segundos |
| Límites | Ninguno | Límites de uso gratuitos: un 429 hace esperar y pasar al siguiente proveedor de la cadena |
| Datos | No salen del equipo | El prompt sale a un tercero (solo con datos sintéticos) |

**Ollama hace falta igualmente para los embeddings** (`bge-m3`), aunque la generación vaya por Groq u OpenRouter. `bge-m3` es mucho más ligero que los modelos de generación.

## 2. `.env` a partir de `.env.example`
`cp .env.example .env` y rellena **tú** los valores. El `.env` está en `.gitignore`.

| Variable | Para qué |
|---|---|
| `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` | Leer el sandbox de Jira: proyectos, épicas, HU y búsqueda. El acceso se pide por un canal privado |
| `JIRA_PROJECT_KEY` | Proyecto por defecto del sandbox |
| `JIRA_CLOUD_ID` | Opcional: solo con un token con *scopes*, que va por el gateway de Atlassian; sin él, la API usa `JIRA_BASE_URL` |
| `JIRA_TEST_SUBTASK_TYPE` | Opcional: tipo de subtarea de los casos de prueba en el flujo de QA (por defecto, «Subtarea») |
| `JIRA_PUBLISH_MODE` | **`simulation`**: aprobar prepara lo que se publicaría y no escribe nada en Jira |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Credenciales con las que Compose crea la base de datos y con las que se conecta la API |
| `DATABASE_URL` | Opcional: si no está, la API usa `POSTGRES_HOST` y `POSTGRES_PORT` (por defecto `127.0.0.1:5432`) |
| `OLLAMA_BASE_URL` | Dirección de Ollama vista desde la API (fuera de Compose, la del puerto 11434 en `127.0.0.1`) |
| `GROQ_API_KEY`, `OPENROUTER_API_KEY` | Opcionales. Sin ellas, `config/models.yaml` usa solo modelos locales |
| `APP_ENV` | `development`: activa `/api/docs` y los ajustes de desarrollo |
| `LOG_LEVEL` | Opcional |
| `API_ALLOWED_ORIGINS`, `API_INSECURE_DEV_COOKIE`, `API_SESSION_*` | Déjalos como en la plantilla: con el proxy de Vite no hace falta CORS y la cookie `Secure` funciona en `localhost` |

No hacen falta para el frontend: `QUALITY_RETENTION_DAYS` (vale el valor por defecto), `MCP_USER` ni `MCP_ROLE`.

## 3. Base de datos, conocimiento, usuarios y arranque
```powershell
uv run alembic upgrade head          # migraciones
uv run python -m core.rag.indexing   # indexa el corpus sintético (data/seed/corpus); necesita bge-m3
uv run python -m core.seed_users     # af-demo, qa-demo y admin-demo
uv run python -m api                 # http://127.0.0.1:8000/api/v1 · un solo proceso
```

- **`core.seed_users`** muestra las contraseñas **una sola vez**. Guárdalas en tu gestor de contraseñas y no las pegues en ningún sitio. Si lo vuelves a ejecutar, cambian.
- **La API** se compone en la primera petición. Si algo falla (base de datos caída, `.env` incompleto), responde 503 con el motivo y vuelve a intentarlo en la siguiente.
- **Sesiones:** viven en la memoria de la API. Si la reinicias, hay que volver a iniciar sesión; las conversaciones siguen en PostgreSQL.

En otra terminal:

```powershell
cd web
npm ci
npm run dev                          # http://localhost:5173 → proxy /api a 127.0.0.1:8000
```

- **Proxy:** apunta a `http://127.0.0.1:8000` y va **sin** `changeOrigin`, porque la API compara `Origin` con `Host`. Se cambia con `API_PROXY_TARGET`.
- **Navegador:** usa `http://localhost:5173`. La cookie de sesión es `Secure` y el navegador solo la acepta sin HTTPS en `localhost`.

## 4. Recorrido completo contra la API real
- [ ] **Login** con `af-demo`: la sesión sobrevive a recargar la página (`/auth/me`).
- [ ] **Inicio:** proyectos del sandbox, recientes y aviso de simulación; el anillo del carril con el consumo de hoy.
- [ ] **Elegir en Jira:** épicas, HU y búsqueda en el sandbox.
- [ ] **Origen y fuentes:**
  - fuentes del RAG y de Jira con casillas;
  - **presupuesto** «Contexto · N de M tokens», que cambia al desmarcar una fuente;
  - restricciones.
- [ ] **Generando:**
  - los pasos avanzan con el SSE durante varios minutos con Ollama;
  - *Detener* («Deteniendo…» y, después, `cancelled` con *Reintentar*);
  - *Reintentar* tras un error.
- [ ] **Iterar:**
  - pedir un cambio crea la versión siguiente;
  - versión «Jira», pestañas Cambios e Impacto y modelo usado (`model_used`);
  - *Descartar*.
- [ ] **Retomar** desde la lista: una conversación generando, otra en revisión y otra terminada.
- [ ] **Revisar y aprobar** (cuando esté): recibo con la huella exacta → resultado **simulado**, sin nada escrito en Jira.
- [ ] **Errores:** reiniciar la API a mitad de la sesión → «Sesión caducada» → *Iniciar sesión*.

## 5. Fallos más probables
| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `ECONNREFUSED` en la consola de Vite | La API no está arrancada, o el proxy apunta a `localhost` y se resuelve a IPv6 (`::1`) | Arranca `uv run python -m api` y deja el destino en `127.0.0.1` |
| 503 en todas las peticiones | PostgreSQL caído o `.env` incompleto: la API no se pudo componer | `docker compose ps`, revisa el motivo del 503 y el `.env` |
| 403 en los POST | Token CSRF perdido tras reiniciar la API, o el proxy con `changeOrigin` | Vuelve a iniciar sesión y no actives `changeOrigin` |
| Al iniciar sesión, vuelve a pedirla | Navegas por `127.0.0.1` o por otro host, y la cookie `Secure` no se guarda | Usa `http://localhost:5173` |
| `invalid_credentials` | Has vuelto a ejecutar `core.seed_users` y las contraseñas cambiaron | Usa las últimas que mostró |
| Origen sin fuentes del RAG, o 503 al pedirlas | No se ha indexado el corpus o falta `bge-m3` en Ollama | `ollama pull bge-m3` y `uv run python -m core.rag.indexing` |
| Generación muy lenta o se corta | Ollama en CPU (5–6 min por HU) o falta de memoria en WSL | Espera, sin recargar (hay un ping cada 15 s); sube la memoria de WSL o usa Groq u OpenRouter |
| `rate_limited` con cuenta atrás | Límites de uso de Groq u OpenRouter | Espera `retry_after`; la cadena pasa al siguiente proveedor |
| 401 o 404 de Jira | Token, URL o clave de proyecto del sandbox incorrectos | Revísalos en el `.env`, sin pegarlos en ningún sitio |
| `docker compose up` falla al descargar imágenes | Proxy corporativo o virtualización desactivada | Pide a IT el proxy de Docker Desktop y que active la virtualización |
| Puerto 5432 ocupado | Hay otro PostgreSQL instalado en el equipo | Páralo o cambia el puerto publicado y `POSTGRES_PORT` |
