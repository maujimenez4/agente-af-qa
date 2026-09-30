---
name: tarea
description: Ejecuta de principio a fin una tarea T-XX del docs/KANBAN.md siguiendo el flujo de CLAUDE.md (leer tarea y SPEC, marcar 🔄, plan con confirmación, implementar solo su alcance, test-writer + pytest + ruff, spec-checker + security-reviewer, marcar ✅, registro diario y commit "T-XX: … [RF-YY]"). Úsala siempre que el usuario pida empezar, retomar, continuar o cerrar una tarea del Kanban ("haz la T-10", "vamos con la siguiente tarea", "cierra la T-15", "/tarea T-14"), aunque no diga la palabra "skill". No la uses para preguntas sueltas sobre el proyecto ni para editar el Kanban sin trabajar en una tarea.
argument-hint: "T-XX [cerrar]"
---

# /tarea — flujo de una tarea del Kanban

Esta skill convierte el "Flujo por tarea" de `CLAUDE.md` en un procedimiento repetible. El proyecto lo desarrolla una sola persona con tres sesiones en paralelo (P en `main`, A en `area-a`, B en `area-b`), así que lo que más daño hace no es un error de código, sino **salirse del alcance, tocar lo de otra área o dejar el Kanban desincronizado**. Cada paso existe para evitar una de esas tres cosas.

Argumentos recibidos: `$ARGUMENTS`

- `T-XX` → ejecuta el flujo completo de esa tarea.
- `T-XX cerrar` → la implementación ya está hecha: salta al paso 5 (verificación) y cierra.
- Sin argumentos → propone la siguiente tarea (ver "Elegir tarea").

## 0. Situarse

1. Identifica la sesión por la rama (`git branch --show-current`): `main` → **P**, `area-a` → **A**, `area-b` → **B**.
2. Localiza la fila de la tarea en `docs/KANBAN.md` y lee sus columnas **Sesión**, **Depende**, **Trazabilidad** y **Estado**.
3. Comprueba y, si algo falla, **para y avisa** (no lo resuelvas por tu cuenta):
   - La **Sesión** de la tarea no coincide con la tuya → dilo y sugiere en qué worktree abrirla.
   - Alguna dependencia no está ✅ → enuméralas y pregunta si se continúa igualmente (a veces se avanza con fakes).
   - La tarea está ⛔ → explica el bloqueo anotado.
   - La sesión es **Tú** (tarea manual) → no implementes nada: da una lista de pasos para el usuario y marca ✅ solo cuando confirme que la ha hecho.
4. En un worktree con el árbol limpio, trae lo último: `git rebase main`. Si hay cambios sin commit, no hagas rebase: avisa.

### Elegir tarea (sin argumentos)
Lista las tareas ⬜ de tu sesión cuyas dependencias estén todas ✅, ordenadas por día, y propone la primera. Espera a que el usuario elija.

## 1. Leer antes de tocar nada

Lee lo que la tarea necesita, no todo el repositorio:

- `CLAUDE.md` (principios, propiedad de directorios, convenciones).
- `docs/specs/SPEC-00-fundacional.md`: las secciones que afectan a la tarea (contratos, protocolos, tablas).
- `docs/decisiones/01_declaraciones_proyecto.md`: cada RF, RNF, D-XX o R-XX de la columna **Trazabilidad**.
- La spec de la épica en `docs/specs/` si existe.
- **Prompt de la tarea**: busca `T-XX` en `docs/prompts/`. Si hay uno, es la instrucción más concreta y manda sobre esta skill en el *qué* (entregables, formato, restricciones). Esta skill sigue marcando el *cómo* (orden, verificación, Kanban, commit).
- Las filas de "Decisiones del día N", las "Propuestas adicionales" que mencionen la tarea (`Pendiente · T-XX`) y la última fila del "Registro diario": ahí suele haber alcance adelantado o condiciones acordadas.
- El código y los fakes (`tests/fakes/`) de los módulos que vas a tocar.

## 2. Marcar 🔄

En `docs/KANBAN.md`:
- Cambia el **Estado** de la fila a 🔄.
- Actualiza el **Tablero resumen**: quita la tarea de ⬜ Backlog y ponla en 🔄 En curso. El backlog usa rangos (`T-08 … T-36`); si la tarea rompe un rango, divídelo (`T-08 … T-09, T-11 … T-36`).

## 3. Plan y confirmación

Antes de escribir código, presenta un plan breve y **espera la confirmación del usuario**:

- Qué vas a construir, archivo por archivo, y en qué directorio (y que todos son de tu área).
- Qué criterios de aceptación y RF cubre cada parte.
- Qué queda **fuera** del alcance, sobre todo lo que la tarea parece pedir pero pertenece a otra tarea.
- Dudas o decisiones que necesitan al usuario.

El usuario prefiere corregir un plan a deshacer una implementación; por eso este paso no se salta, aunque la tarea parezca obvia.

## 4. Implementar solo su alcance

- **Propiedad de directorios**: toca solo los de tu área (tabla de `CLAUDE.md`). `tests/fakes/` es compartido: añade, no rompas.
- **Contratos congelados** (`schemas/`, `adapters/base.py`, `adapters/errors.py`, `core/config.py`, `core/container.py`): desde un worktree no se cambian. Si la tarea lo exige, **para** y redacta la propuesta de cambio para la sesión principal.
- **Mejoras no pedidas**: no las implementes. Añádelas a "Propuestas adicionales" con el siguiente `PA-XX` libre (mira el número más alto, no el último de la tabla), columna *Origen* = `T-XX` y *Decisión* = `Pendiente`.
- Aplica las convenciones de `CLAUDE.md`: identificadores en inglés y textos en español, tipado completo, núcleo solo contra `Protocol`, errores envueltos en `adapters/errors.py`, prompts en `prompts/<tarea>.md` con `version:`, structlog sin secretos.
- **Nunca** leas ni uses `.env`, ni escribas en Jira o llames a APIs reales. Las pruebas reales van con `@pytest.mark.integration` y se saltan sin credenciales.
- Datos de ejemplo siempre sintéticos (Faker `es_ES` o valores claramente ficticios).

## 5. Pruebas

1. Lanza el subagente **`test-writer`** indicando la tarea, los módulos tocados y la lista de CA/RF que deben quedar cubiertos (cada criterio con al menos una prueba).
2. Ejecuta y corrige hasta verde:
   ```bash
   uv run pytest -m "not integration"
   uv run ruff check .
   uv run ruff format --check .
   ```
   Si un fallo viene de código de la otra área o de un contrato congelado, no lo parchees: repórtalo.

## 6. Revisión

Lanza **`spec-checker`** y **`security-reviewer`** en paralelo (son de solo lectura). Corrige lo que marquen y vuelve a pasarlos hasta obtener **CONFORME** y **APTO**. Vuelve a ejecutar las pruebas tras cada corrección.

Si tras tres pasadas sigue habiendo un hallazgo que no se puede resolver dentro del alcance (por ejemplo, requiere tocar un contrato), para: anótalo como PA-XX y pregunta al usuario si se cierra la tarea con esa salvedad.

## 7. Cerrar

1. `docs/KANBAN.md`:
   - Estado de la fila → ✅ y **Tablero resumen** actualizado (de 🔄 a ✅, en orden numérico).
   - **Registro diario**: añade la tarea a la columna *Hecho* de la fila del día en curso (créala si no existe, con la fecha de hoy). Anota solo lo que otra sesión necesite saber: alcance adelantado, decisiones tomadas, salvedades, pasos que quedan para el usuario.
2. Commit (sin `push` ni fusión en `main`; la fusión se hace en la sincronización del día):
   - Añade solo los archivos de la tarea más `docs/KANBAN.md`. Revisa `git status` antes: nada de `.env`, `data/memory/` ni archivos de otras tareas.
   - Mensaje: `T-XX: descripción breve en español [IDs]`. Los IDs salen de la columna **Trazabilidad** (RF, RNF, CA o D), separados por comas.
   - Ejemplos del historial: `T-05: schemas de dominio y máquina de estados con pruebas [RF-34, CA-00-02, CA-00-07]`, `T-03: config con pydantic-settings y SecretStr, logging structlog con enmascarado [RNF-01, RNF-02, RNF-23]`.
   - Si el hook de pre-commit (gitleaks, ruff) falla, corrige y crea el commit de nuevo; nunca uses `--no-verify`.
3. Resumen final para el usuario, en 3–5 líneas: qué se entregó, qué CA quedan cubiertos, veredictos de las revisiones, PA añadidas y cualquier paso manual pendiente.
