# SESIÓN JIRA · Ronda 2: escritura real en el sandbox y T-47 (área A · `adapters/`)

Tu rama `ses-jira` ya está fusionada en `PreProduccion`. Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-a switch -C ses-jira origin/PreProduccion
cd .claude/worktrees/area-a
uv sync
uv run pytest -m "not integration"          # debe salir en verde antes de empezar
```

Las pruebas reales necesitan tu `.env` en esta carpeta: cópialo tú, porque está en `.gitignore`.

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", en la rama **`ses-jira`**, recién puesta al día desde `PreProduccion`. Tus T-27 y T-30 ya están fusionadas (✅). La principal ha conectado `JiraNativeTests` en `build_app_container` (`core/factories.build_test_management`) y ha corregido PA-201: en `_diff_comment_md` tu prueba ya pasa sin `xfail`.

Hay **otras sesiones de Claude Code trabajando a la vez**:
- **Principal:** `PreProduccion`. Integra y es dueña de los contratos, el grafo y la composición.
- **UI:** `ses-ui`, con T-31, Mixta 5, T-28 y la pestaña Memoria.
- **T-32:** `ses-memoria`, en `adapters/llm/`.
- **Ollama:** la prueba real de punta a punta.

**Solo tocas lo de esta sesión.**

## 1. Escritura real en el sandbox de Jira (**autorizada por el usuario**) [RF-04, RF-05, RF-06, RF-30, RNF-13]
Es lo que falta para desbloquear `JIRA_PUBLISH_MODE=live`. Las pruebas **escriben de verdad** en el proyecto `JIRA_PROJECT_KEY` del sandbox: crean HU sintéticas con el título `[PRUEBA-AGENTE] …`, un comentario de diff, vínculos «relates to», subtareas `caso-prueba` y dos adjuntos `.md`.

1. **Antes de escribir**, comprueba que la conexión y la lectura van bien: `uv run pytest -m integration tests/integration/test_jira_live.py`.
2. **Ejecuta las pruebas de escritura:**
   ```bash
   # PowerShell: $env:JIRA_WRITE_TESTS = "1"   ·   Git Bash: export JIRA_WRITE_TESTS=1
   uv run pytest -m integration -s tests/integration/test_jira_write_live.py tests/integration/test_jira_testmgmt_live.py
   ```
3. **Si algo falla**, diagnostícalo y corrígelo **en `adapters/`**. Lo que se suele ver en un sitio real:
   - el nombre del tipo de HU («Story» / «Historia», PA-200);
   - el tipo de subtarea;
   - pantallas de creación con campos obligatorios;
   - permisos del token para adjuntar o enlazar.

   Si el arreglo necesita un cambio en `core/config.py` (por ejemplo `JIRA_STORY_ISSUE_TYPE`), **para y avísame**: lo hace la principal.
4. **Repite la publicación de QA** para comprobar la idempotencia de PA-05: no duplica subtareas ni adjuntos.
5. **Deja constancia** en tu fila del registro diario: las **claves creadas**, las pruebas que pasan, el tiempo y los ajustes hechos.
   - El agente no borra nada en Jira. Pide al usuario que borre a mano lo creado: el JQL `summary ~ "PRUEBA-AGENTE"` lo localiza todo, y al borrar la HU se borran sus subtareas.
   - **Ninguna otra escritura:** nada fuera de esas dos pruebas y del proyecto `JIRA_PROJECT_KEY`.

## 2. `/tarea T-47`: registro de la ejecución por caso (parte del adaptador) [RF-28, R-01 opción A]
El estado (*Pasó*, *Falló*, *Bloqueado*, *Sin ejecutar*) y la evidencia, como comentario en la subtarea CP. Lo publica **solo el nodo `publish`, con aprobación humana**.

- **Tu parte:** `JiraNativeTests.record_execution(case_key, status, evidence_md) -> None`.
  - Transición de la subtarea al estado que corresponda: busca la transición por nombre con `GET /issue/{key}/transitions` y documenta el mapeo configurable.
  - Comentario ADF con el resultado y la evidencia, con `markdown_to_adf`.
  - Una etiqueta `ejecucion-<estado>` si te parece útil.
  - Errores envueltos en `adapters/errors.py` y escritura de un solo intento.
- **Contrato:** el método no está todavía en el protocolo `TestManagement` (`adapters/base.py`, congelado) ni en el grafo.
  - **No lo toques:** escribe en tu informe la firma exacta que propones y la principal la añadirá al protocolo, al artefacto y a `publish`.
  - En el fake (`tests/fakes/test_management.py`) **añade** el método sin romper nada.
- **Pruebas:**
  - unitarias con `httpx.MockTransport`;
  - `integration` con `JIRA_WRITE_TESTS=1`, sobre una subtarea creada por la propia prueba. Ya está autorizada, pero avísame antes de ejecutarla.

## Reglas comunes a todas las sesiones
- **Solo tus archivos:** `adapters/jira/`, `adapters/testmgmt/`, `tests/unit/test_jira_*.py`, `tests/unit/test_testmgmt*.py`, `tests/integration/test_jira_*` y, para añadir, `tests/fakes/test_management.py`.
  - No toques `core/`, `app/`, `schemas/`, `adapters/base.py`, `adapters/errors.py`, `prompts/`, `config/` ni la SPEC.
- **Kanban:**
  - Cambia solo el estado de tus filas (T-47 y las PA que cierres).
  - Añade tu fila al registro diario.
  - No toques el tablero resumen.
  - **Propuestas en PA-206…PA-249.**
- **Seguridad:**
  - Tokens solo vía `SecretStr`.
  - Nunca registres `Authorization` ni cuerpos de respuesta.
  - No imprimas valores del `.env`; las claves de las incidencias creadas sí puedes mostrarlas.
  - Ni secretos ni datos personales en pruebas o fixtures; usa datos ficticios.
- **LLM:** esta sesión no lo necesita.
- **Antes de cada commit:**
  - `uv run pytest -m "not integration"`, `uv run ruff check .` y `uv run ruff format --check .` en verde;
  - subagentes `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Commits:**
  - Formato `T-XX: descripción [RF-YY]`.
  - **Sin fusionar.** Haz `git push origin ses-jira` y avísame.

Empieza por el punto 1 y dime el resultado de las pruebas de escritura antes de seguir con T-47.
