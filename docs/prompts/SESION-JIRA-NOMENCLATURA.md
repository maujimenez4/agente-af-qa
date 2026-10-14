# SESIÓN JIRA · Ronda 17: número `[HU-NN]` en las HU nuevas (PA-202, R-05)

> Encargo de la **sesión Jira**. Tu ronda 16 (memoria de QA) está terminada en `ses-memoria-qa`, sin fusionar. Esta ronda es independiente: sale de `PreProduccion`. Es **v1.1** y **no se fusiona hasta después de la presentación al comité**.

Pon el worktree en la rama nueva y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-a switch -C ses-nomenclatura origin/PreProduccion
cd .claude/worktrees/area-a
uv sync
find .venv/Lib/site-packages/sqlalchemy -name "*.pyd" -exec sh -c 'mv "$1" "$1.bloqueado"' _ {} \;
uv run python -m pytest -m "not integration" -q -p no:cacheprovider   # en verde
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA" (el asistente se llama **FAQ**), ahora en la rama **`ses-nomenclatura`**, creada desde `PreProduccion`. Tu rama `ses-memoria-qa` queda aparte, sin fusionar.

**Contexto:** las HU sembradas en AFQP siguen la convención provisional **R-05** (título `[HU-NN] …`), pero las HU **nuevas** que publica FAQ salen sin prefijo (AFQP-16, AFQP-27 y AFQP-28). Ya está identificado en **PA-202**:
- `adapters/jira/story_template.py` (`prefixed_summary`) ya antepone `[HU-NN]` si `internal_id` tiene formato `HU-\d+`;
- lo que falta es **asignar el número** a una HU nueva, que hoy no lo tiene.

Hay un precedente: los casos de prueba ya se numeran solos mirando los `CP-NN` que existen en Jira (`renumber_cases`, el paso de numeración de `core/graph/nodes.py`).

Lee:
- la fila **PA-202** del Kanban y R-05 en la SPEC-00 y en `docs/decisiones/01_declaraciones_proyecto.md`;
- `adapters/jira/story_template.py`;
- la numeración de casos en `core/graph/nodes.py` y su helper;
- el campo `internal_id` de `schemas/user_story.py`.

## Tareas (propón el plan antes de escribir código)
1. **Asignar `HU-NN` a una HU nueva** en el núcleo, no en el LLM, con el mismo patrón que los casos:
   - **El número:** buscar en el proyecto de destino los títulos `[HU-NN]` existentes y tomar el siguiente libre.
   - **Cuándo:** **antes de la revisión humana**, para que la persona lo vea en la propuesta y la huella de la aprobación lo incluya.
   - **Números fuera de rango** puestos a mano en Jira: se ignoran, como en los casos.
2. **No renumerar lo que ya tiene número:** una HU que se evoluciona conserva su `internal_id`. Una HU nueva que el modelo ya trajera con un `HU-NN` válido y libre se respeta; si choca con uno existente, se reasigna.
3. **Si Jira no responde** al buscar los números, no se bloquea la generación: la HU sigue sin número (como hoy) y queda registrado en el log.
4. **Documentación:**
   - R-05 y PA-202 en el Kanban;
   - la SPEC-00, en lo que diga de R-05;
   - el README, si nombra la convención.

## Reglas
- **Puedes tocar:** `core/graph/`, `adapters/jira/` (solo lectura de títulos y el prefijo), `tests/`, `tests/fakes/` (añadir, no romper) y la documentación anterior.
- **No toques:** `web/`, `api/`, el contrato, `schemas/` (congelado), `prompts/` ni la lógica de aprobación y publicación.
- **Principio 1:** buscar números es **solo lectura** en Jira. Nada nuevo escribe en Jira.
- **Sin pruebas reales** contra Jira ni el LLM.
- **Pruebas con fakes**, al menos una por criterio:
  - una HU nueva recibe el siguiente número libre y se publica como `[HU-NN] Título`;
  - el número está en la propuesta antes de aprobar y forma parte de la huella;
  - una evolución conserva su número;
  - un `internal_id` del modelo que choca con uno existente se reasigna;
  - números fuera de rango ignorados;
  - Jira caído al buscar no bloquea la generación;
  - regresión: las HU sembradas con `[HU-NN]` no cambian.
- **Windows:** `uv run python -m pytest -m "not integration" -q -p no:cacheprovider`.
- **Kanban:**
  - cierra PA-202 con la fecha;
  - tu fila en el registro;
  - propuestas nuevas en **PA-500…PA-503**.
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - el contrato sin cambios (`uv run python -m api.export_openapi`);
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-nomenclatura` y avísame.

Empieza presentándome el plan antes de escribir código.
