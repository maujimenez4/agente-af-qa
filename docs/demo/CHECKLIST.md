# Lista de comprobación previa a la demo

**Para:** quien prepara la máquina de la demo. Hazla la víspera (apartados 1–6) y repite el 7 media hora antes. Nada de esto muestra secretos: no abras el `.env` delante del público.

## 1 · Servicios
- [ ] Docker Desktop arrancado.
- [ ] `docker compose --profile local-llm up -d db ollama`.
- [ ] `docker compose ps`: `db` en *healthy* y `ollama` en marcha.
- [ ] Nada más usando la CPU: **ninguna otra sesión midiendo tiempos con el mismo Ollama** (comparten CPU y se falsean los tiempos de las dos).

## 2 · Modelos
- [ ] `docker compose exec ollama ollama list` muestra `qwen3:1.7b`, `phi4-mini` y `bge-m3` (los de `config/models.yaml`).
- [ ] Modelos **precargados** para que la primera llamada no pague la carga: `docker compose exec ollama ollama run qwen3:1.7b "hola" --keepalive 2h` (y `phi4-mini`, el respaldo). `ollama ps` los muestra cargados con su `UNTIL`.
  - **Ojo:** ese `--keepalive` solo vale para esa carga. La app llama al endpoint OpenAI de Ollama sin `keep_alive`, así que cada llamada suya vuelve al valor del servidor (5 min por defecto) y el modelo se descarga durante los pasos sin LLM. Hasta que se aplique PA-275, repite la precarga justo antes de los pasos que usan el LLM (0 y, si se hace, una iteración en directo).
  - `bge-m3` se carga con la primera búsqueda: abre una vista previa de fuentes antes de empezar.
- [ ] `config/models.yaml` sin cambios respecto a la rama de la demo (`git status config/`).

## 3 · Base de datos y conocimiento
- [ ] `uv run alembic current` → `0005_qa_handoffs (head)`.
- [ ] Corpus indexado: `uv run python -m core.rag.indexing` ya ejecutado (28 documentos del corpus sintético); repetirlo no duplica.
- [ ] Usuarios: `af-demo`, `qa-demo` y `admin-demo` existen y tienes sus contraseñas (si no, `uv run python -m core.seed_users`, que **las cambia**).

## 4 · Jira y modo
- [ ] En el `.env` (sin abrirlo en pantalla): `JIRA_PUBLISH_MODE=simulation`.
- [ ] Red y Jira accesibles: en la UI, la lista de proyectos muestra el proyecto de pruebas y `DEMO-3` (*Renovar un préstamo*) se abre.
- [ ] Si se hace el paso 8: el sandbox `AFQP` tiene la HU publicada y sus casos (filas `sandbox-*` de `docs/demo/preparadas.md`).

## 5 · Conversaciones preparadas
- [ ] `uv run python -m eval.demo_prepare --real` (o sus parámetros del guion) terminado; **solo con permiso de quien coordina el uso del LLM**.
- [ ] `docs/demo/preparadas.md`: todas ✅ salvo lo que se salte a propósito (por ejemplo `ejecucion-en-revision` sin sandbox).
- [ ] Entrando como `af-demo` y `qa-demo` se ven en su lista: `Nueva necesidad · DEMO`, `Evolucionar DEMO-3` (dos), `Preparar pruebas de · DEMO` (encadenada, sin clave) y `Preparar pruebas de DEMO-3` (dos).
- [ ] `docs/demo/calidad-DEMO-3.md` existe (plan B del paso 7).

## 6 · Aplicación
- [ ] API: `uv run python -m api` responde en `http://127.0.0.1:8000/api/v1` (un solo proceso).
- [ ] Frontend o, como plan B, `uv run streamlit run app/main.py` (`http://localhost:8501`).
- [ ] Dos ventanas de navegador (o una privada): una con `af-demo` y otra con `qa-demo`.
- [ ] Capturas del ensayo a mano para los planes B (fuentes, ejecución, HU en Jira, memoria).

## 7 · Media hora antes
- [ ] Repite 1, 2 (precarga) y 4.
- [ ] Abre una preparada de cada usuario para calentar la caché de la UI.
- [ ] Ninguna preparada aprobada por error en el ensayo; si alguna lo está: `uv run python -m eval.demo_prepare --real --rehacer <nombre>` (minutos).
- [ ] Notificaciones del sistema silenciadas y pantalla al 100 % de zoom.
