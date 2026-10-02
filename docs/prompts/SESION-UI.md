# SESIÓN MODELOS · Ronda 6: cerrar huecos funcionales (PA-272, PA-103, PA-113, PA-275 y PA-273)

> Este archivo era el encargo de T-54 y después el de la demo (T-36, parte 1). La demo queda aparcada hasta que el sistema esté terminado (decisión del usuario). Ahora es el encargo de la **sesión Modelos**.

Tu T-36 (parte 1) se queda en la rama `ses-demo`. De ella se ha fusionado solo el README de instalación y las PA-270…PA-275. Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-b switch -C ses-huecos origin/PreProduccion
cd .claude/worktrees/area-b
uv sync
uv run pytest -m "not integration"          # en verde, con 84 xfailed (defectos de T-35 en curso)
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-huecos`**, creada desde `PreProduccion`.

La demo queda aparcada (`ses-demo` se conserva tal cual): los documentos de la demo se harán cuando el sistema esté terminado. **En esta ronda cierras huecos funcionales del sistema.** Ninguno necesita el LLM real.

Hay **otras sesiones trabajando a la vez**:
- **Principal:** integra y revisa. **En esta ronda no toca `api/`**: la API es tuya para estas PA.
- **UI:** `ses-ui`, corrigiendo los defectos de T-35 en `core/approvals.py`, `core/state_machine.py`, `core/graph/execution.py`, `core/context/`, `core/impact/`, `adapters/llm/` y `adapters/auth/`.
- **Jira:** `ses-jira`, corrigiendo defectos en `adapters/jira/`, `adapters/testmgmt/` y `core/memory/`, y moviendo `escape_data` (PA-227).
- **Ollama:** la prueba real de punta a punta. **Usa el LLM y el contenedor de Ollama en esta máquina: no lo reinicies ni cambies su configuración en caliente.**
- **Responsable del área B:** frontend en React contra `docs/api/openapi.yaml`.

## Tareas (en este orden)
1. **PA-272 y PA-103 · Revisar la calidad persistente y en la lista.** Hoy `QualityJob` vive en memoria (`api/runtime.py`, `rt.quality`) y se pierde al reiniciar.
   - Guárdala en PostgreSQL. Propón el diseño en el plan, por ejemplo una tabla `quality_reviews` con la migración `0006`: persona, clave, estado, informe JSON, fechas y errores en la forma común.
   - Al terminar, debe aparecer en la lista de conversaciones de la persona como «Informe listo» (UI.md §2). Decide en el plan si se une a `GET /conversations` (con un campo de tipo) o va en una lista aparte, y **cómo cambia el contrato**. Avisa: el frontend en React lo consume.
   - La propiedad (404 idéntico) y la regla de no escribir en Jira se mantienen.
2. **PA-113 · Recoger una HU que falla.** Si la generación de la conversación de QA falla después de `take`, que no quede bloqueada. Propón en el plan una opción y justifícala:
   - devolver la entrega a pendiente;
   - o reintentar desde la conversación de QA.
3. **PA-275 · `keep_alive` de Ollama.** Que el modelo no se descargue a los 5 minutos sin uso.
   - Opción simple: `OLLAMA_KEEP_ALIVE` en el servicio `ollama` de `docker-compose.yml`. Si lo haces así, **no reinicies el contenedor**: el cambio se aplicará en el próximo arranque.
   - Documenta en el README cómo se aplica.
4. **PA-273 · `docker compose --profile full`.** El servicio `app` usa `build: .`, pero no hay `Dockerfile`.
   - Añade uno mínimo y reproducible (uv con el lockfile, usuario no root y sin copiar el `.env`) que arranque la API (`python -m api`), o quita el servicio si no tiene sentido.
   - Justifícalo en el plan.

## Reglas
- **Puedes tocar:**
  - `api/` (con regeneración del contrato: `uv run python -m api.export_openapi`, sin argumentos);
  - `core/quality.py` y `core/handoff.py`;
  - `migrations/versions/0006_*.py`;
  - `docker-compose.yml`, `Dockerfile` (nuevo), `.dockerignore` (nuevo) y `README.md`;
  - `app/` solo si la persistencia de la calidad lo necesita en Streamlit;
  - y sus pruebas.

  No toques `core/graph/`, `core/approvals.py`, `adapters/`, `schemas/` ni `config/`. Si necesitas un contrato congelado, **para y propónlo**.
- **Pruebas:**
  - con `fake_runtime` y fakes;
  - las de PostgreSQL de la migración llevan la marca `integration` y usan bases de datos temporales;
  - no ejecutes la suite `integration` completa.
- **Kanban:**
  - cierra las PA que hagas con la fecha;
  - añade tu fila al registro;
  - no toques el tablero;
  - **propuestas en PA-276…PA-299**.
- **Seguridad:** no leas el `.env`; el `Dockerfile` no copia secretos; datos ficticios; los logs sin contenido.
- **CPU:** Ollama está midiendo. Ejecuta solo las pruebas de lo que tocas y la suite completa una vez al final.
- **Antes del commit:**
  - `uv run pytest -m "not integration"`, `ruff check` y `ruff format --check` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-huecos` y avísame.

Empieza presentándome el plan (sobre todo el diseño de la persistencia de la calidad, cómo cambia el contrato y la opción para PA-113) antes de escribir código.
