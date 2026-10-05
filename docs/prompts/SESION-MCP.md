# SESIÓN MCP · Ronda 3: probar la web en React contra la API (T-56)

> Encargo de la **sesión MCP**. T-59 está cerrada y fusionada. El frontend en React (`web/`, rama `area-b`) ya está fusionado en `PreProduccion`. Su responsable no puede montar la API en su equipo, así que la prueba se hace en este.
>
> **Respaldo:** si algo sale mal, el estado anterior a la fusión está en la rama `respaldo/pre-frontend-2026-10-05` (y en la etiqueta `pre-frontend-2026-10-05`).

Pon el worktree al día, **copia el `.env`** (lo hace el usuario, la sesión nunca lo lee) y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```powershell
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/ses-mcp switch -C ses-web origin/PreProduccion
copy .env .claude\worktrees\ses-mcp\.env
cd .claude/worktrees/ses-mcp
uv sync
uv run python -m pytest -m "not integration"   # en verde
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-web`**, creada desde `PreProduccion`. Tu T-59 ya está fusionada.

**Objetivo:** comprobar que la web en React (`web/`, T-56) funciona contra la API (`api/`, T-55) de punta a punta. Si algo falla, arreglar lo que sea de la conexión entre las dos y apuntar el resto para su responsable.

El responsable de `web/` sigue trabajando en paralelo en el flujo de QA (rama `area-b`). Para no pisaros:
- **Tú arreglas solo la conexión:** `web/src/api/**` (cliente, tipos, SSE) y la configuración de Vite. Si es un fallo de la API o del contrato, en `api/` y sus pruebas, sin cambiar lo que ya existe.
- **Lo de pantallas** (textos, estados, navegación, estilos) **no lo tocas:** lo anotas en el informe para el responsable.

Lee antes:
- `web/PRUEBA-API-REAL.md`: la guía y la lista de comprobación que escribió el responsable. Es tu guion.
- `web/README.md`;
- `docs/api/README.md`, sobre todo «Reglas para el frontend» y «Novedades para el frontend».

## Fase 1 · API con los dobles de prueba (automática, sin modelo ni Jira)
Sirve para validar la parte HTTP sin depender de Ollama ni de contraseñas reales: cookie, CSRF, proxy de Vite, SSE, 202 y 409.
1. **Un script solo de desarrollo** que arranque la API real (FastAPI) sobre `tests/fakes/api.fake_runtime`, con `run_inline=False` para que el SSE avance paso a paso. Por ejemplo, `tests/fakes/serve_api.py` (`uv run python -m tests.fakes.serve_api`).
   - Escucha solo en `127.0.0.1`.
   - Se niega a arrancar si `APP_ENV` no es `development`.
   - Usa los usuarios ficticios de `tests/fakes/dataset.py`.
   - Nunca lee el `.env`.
2. `cd web && npm ci && npm run dev`, con el proxy apuntando a ese puerto (`API_PROXY_TARGET`).
3. **Recorre la lista de comprobación** con el navegador sin interfaz que ya usó el responsable (Edge + CDP, con los scripts en el scratchpad y fuera del repositorio) o con peticiones HTTP que imiten a la web.
   - Si añadir Playwright u otra dependencia a `web/` te parece imprescindible, **para y propónmelo**.
   - Cubre lo que esté conectado: login y recarga, Inicio, Elegir en Jira, Origen con el presupuesto, Generando con Detener y Reintentar, Iterar con una v2 y la versión «Jira», el recibo con la operación `comment` (PA-319), aprobar con la huella, el resultado simulado y descartar.
   - Con `qa-demo` y `admin-demo`, solo que no fallen.

## Fase 2 · API real (guiada por el usuario)
Ollama local, PostgreSQL y Jira AFQP en **simulación**. El usuario está delante y lleva el navegador. Él inicia sesión con sus contraseñas: **nunca le pidas ni registres contraseñas**.
1. **Tú arrancas:** `uv run python -m api` (127.0.0.1:8000) y `npm run dev` (http://localhost:5173), y compruebas que `GET /api/v1/settings` responde y que `publish_mode` es `simulation`. Si no lo es, **para**.
2. **Guías al usuario** por la lista de `web/PRUEBA-API-REAL.md`, paso a paso.
   - Con el modelo local, cada generación tarda unos 5 minutos: aprovecha la espera para revisar el log de la API.
   - Antes de cada generación, confirma con el usuario que quiere lanzarla.
3. **Vigila** el log de la API y la consola de Vite. Cada operación deja una traza en Langfuse: si algo falla, úsala para ver en qué paso.

## Reglas
- **Nunca escribe en Jira:** todo en simulación. No cambies `JIRA_PUBLISH_MODE`.
- **Secretos:** nunca leas el `.env`, ni pidas o registres contraseñas, tokens o cookies. Los logs y capturas del informe, sin secretos.
- **Puedes tocar:**
  - `web/src/api/**` y `web/vite.config.ts` (solo la conexión);
  - `tests/fakes/` (añadir, no romper);
  - `api/` y sus pruebas (solo arreglos de la conexión, sin cambiar lo existente del contrato);
  - el informe.

  Ni pantallas de `web/`, ni `core/`, `adapters/`, `schemas/`, `config/` o `app/`.
- **Si cambias `web/`:** `npm run lint`, `npx tsc -b`, `npm test` y `npm run api:check` en verde.
  - En este equipo fallan a veces 2 o 3 pruebas de «Retomar en error · Reintentar», que dependen del tiempo (ya avisado al responsable): no las cuentes como regresión tuya, pero dilo.
- **Si cambias Python:** `uv run python -m pytest -m "not integration"`, `ruff check` y `ruff format --check` en verde. Regenera el contrato si cambia `api/`.
- **No mates procesos globales** (nada de `taskkill` por nombre). Para la API y Vite que arranques tú, usa sus propias tareas en segundo plano. Pídeselo también a los subagentes.
- **Informe** `docs/pruebas/WEB-API-2026-10-05.md` con:
  - qué fases y qué pasos se recorrieron, y con qué resultado;
  - una tabla de hallazgos: paso, síntoma, causa, arreglado por ti o para el responsable, y la prioridad para la demo;
  - los tiempos reales de cada generación (de Langfuse).
- **Kanban:**
  - tu fila en el registro;
  - propuestas en **PA-324…PA-339** (PA-324 ya está usada: empieza en PA-325).
- **Antes del commit:**
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-web` y avísame.

Empieza presentándome el plan (sobre todo el script de la fase 1 y cómo vas a recorrer la web sin navegador visible) antes de escribir código.
