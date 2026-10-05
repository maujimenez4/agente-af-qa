# SESIÓN JIRA · Ronda 11: skill `/auditoria` (antipatrones y errores en todo el proyecto)

Tu ronda 10 (T-29) ya está fusionada. Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-a switch -C ses-auditoria origin/PreProduccion
cd .claude/worktrees/area-a
uv sync
uv run python -m pytest -m "not integration"   # en verde
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-auditoria`**, creada desde `PreProduccion`. Tu ronda 10 ya está fusionada.

**Objetivo:** crear la skill de proyecto **`/auditoria`**, que revisa el repositorio **completo** (no un diff) contra las reglas propias del proyecto y los antipatrones típicos del stack, y produce un informe. **No la lances completa en esta ronda:** se ejecutará cuando el sistema esté terminado. Aquí se construye y se prueba solo su capa automática.

Ya existen, y la skill **no los repite**, sino que los complementa:
- `security-reviewer` y `spec-checker` (`.claude/agents/`), que revisan el cambio de una tarea;
- `/code-review` y `/security-review` de Claude Code, que son genéricos;
- ruff, gitleaks y pytest en la CI.

Lee `CLAUDE.md` (principios, convenciones, propiedad de directorios), `.claude/skills/tarea/SKILL.md` (el formato de skill del proyecto) y `.claude/agents/*.md`.

## Cómo crearla
Usa la skill **`anthropic-skills:skill-creator`** para redactarla y afinar su `description` (para que se active con «audita el proyecto», «busca antipatrones», «análisis completo», «/auditoria»). Va en **`.claude/skills/auditoria/`**: `SKILL.md` y, si hacen falta, scripts y referencias en la misma carpeta.

## Diseño (decidido con el usuario)
**Capa 1 · Comprobaciones automáticas**, sin IA, deterministas: un script, por ejemplo `.claude/skills/auditoria/checks.py`, ejecutable con `uv run python .claude/skills/auditoria/checks.py`, que imprime hallazgos con regla, archivo:línea y gravedad. Como mínimo:
- escrituras en Jira (`create_story`, `update_story`, `link`, `publish_suite`, `record_execution`, POST/PUT a `/rest/api/3/…`) fuera de `publish` y `_publish_approved` de `core/graph/nodes.py`, del grafo de ejecución y de los adaptadores;
- el núcleo (`core/`) importando implementaciones concretas de `adapters/` (solo `adapters/base.py` y `adapters/errors.py`), salvo los puntos de composición (`core/container.py`, `core/factories.py`);
- prompts escritos en el código en lugar de `prompts/<tarea>.md`;
- logs con `prompt`, `messages`, `Authorization`, `api_key`, `token` o `password` como campo;
- `except Exception` / `except:` que no relanza ni registra;
- expresiones regulares con riesgo de retroceso exponencial (cuantificadores anidados, alternancias solapadas con `*`/`+`);
- lectura de `.env` fuera de `core/config.py`;
- en `web/`: `dangerouslySetInnerHTML`, `href`/`src` dinámicos sin `safeHref`, `localStorage`/`sessionStorage` con tokens, `eval`/`new Function`.

Cada regla con su motivo (qué principio o riesgo cubre) y una lista de excepciones justificadas, para no dar falsos positivos.

**Capa 2 · Revisión con IA por dimensiones**, en paralelo con el tool `Agent`, un subagente por dimensión, y **una segunda pasada que intenta refutar cada hallazgo** (solo quedan los confirmados o plausibles):

| Dimensión | Qué busca |
|---|---|
| Principios del proyecto | Aprobación humana, secretos, datos sintéticos, trazabilidad, salidas estructuradas, alcance |
| Corrección | Carreras, estados imposibles, errores silenciosos, reintentos que escriben dos veces |
| Seguridad | Inyección de órdenes al modelo, XSS, CSRF, permisos, fugas en logs y trazas de Langfuse |
| LLM y RAG | Contexto sin presupuesto, citas sin validar, texto libre interpretado a mano, prompts sin versión |
| Pruebas | Criterios sin prueba, pruebas que dependen del tiempo, mocks que esconden el comportamiento real |
| Frontend | Estados de carga y error, accesibilidad, diferencias con el contrato `docs/api/openapi.yaml` |

- Los subagentes son **de solo lectura** y **no matan procesos globales**.
- La skill permite lanzar solo algunas dimensiones (`/auditoria seguridad pruebas`) o solo la capa 1 (`/auditoria rapida`).

**Salida:**
- **Informe** `docs/auditorias/AUDITORIA-<fecha>.md`: resumen con un recuento por gravedad, luego una tabla por dimensión con gravedad (alta/media/baja), archivo:línea, problema, por qué importa y corrección propuesta.
- **Al final,** la skill propone pasar los hallazgos altos y medios al Kanban como propuestas, con el siguiente número libre del rango de quien la ejecute. **Nunca corrige código por su cuenta** (principio 6).

## Reglas
- **Puedes tocar:**
  - `.claude/skills/auditoria/**`;
  - pruebas de la capa 1 en `tests/unit/test_auditoria_checks.py`, con archivos de ejemplo ficticios en `tmp_path`: cada regla detecta un caso malo y no marca uno bueno;
  - una línea en `CLAUDE.md` que mencione la skill (sección de comandos o flujo).

  Nada de código de producción.
- **Prueba la capa 1 sobre el repositorio real** y adjunta en tu mensaje final el recuento por regla. Si una regla da muchos falsos positivos, afínala; si marca algo real, **no lo arregles**: anótalo como propuesta.
- **No lances la capa 2 sobre todo el repositorio.** Como mucho, una dimensión sobre un directorio pequeño para comprobar que el formato del informe sale bien.
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **gitleaks:** en las pruebas, sin literales que parezcan claves; para probar la regla de logs con secretos, usa nombres de campo, no valores.
- **Kanban:**
  - tu fila en el registro;
  - propuestas en **PA-243…PA-249** (incluye llevar las reglas más valiosas de la capa 1 a la CI como prueba permanente).
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-auditoria` y avísame.

Empieza presentándome el plan (reglas de la capa 1 con sus excepciones, y cómo orquesta la capa 2) antes de escribir código.
