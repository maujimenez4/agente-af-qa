# SESIÓN UI · Ronda 8: conversación en «Origen y fuentes» de la web (React)

> Encargo de la **sesión UI**. Tu ronda 7 ya está fusionada. Esta vez trabajas en la **web en React** (`web/`), que ya está en `PreProduccion`. Es del responsable del área B: **avisado de que esta sesión toca solo la pantalla Origen**.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```powershell
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/ses-ui switch -C ses-origen origin/PreProduccion
cd .claude/worktrees/ses-ui/web
npm ci
npm test            # en este equipo pueden fallar 2 o 3 pruebas de «Retomar en error · Reintentar» (dependen del tiempo; ya avisado)
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-origen`**, creada desde `PreProduccion`. Tu ronda 7 ya está fusionada.

**Esta vez trabajas en `web/`**, el frontend en React (T-56) del responsable del área B. Lee antes:
- `web/README.md` y `web/DESIGN-DECISIONS.md`: convenciones, componentes y cómo se prueba;
- `docs/specs/UI.md` §4.3 (Mixta 2 · Origen fijado);
- `docs/api/README.md` (arranque guiado: `POST /start/propose`).

## El fallo (encontrado probando contra la API real)
En **Origen y fuentes**, tras escribir una necesidad, el asistente muestra la propuesta del arranque guiado con sus opciones («Evolucionar AFQP-25», «Crear HU nueva»…).

Si la persona **no elige ninguna y escribe otro mensaje**, el mensaje aparece en el chat pero **no pasa nada**: el composer («Añade detalles a la necesidad (opcional)») lo guarda en `details` sin respuesta, y parece que el agente se ha colgado.

Ejemplo real: «Crea un nuevo proyecto en JIRA llamado pruebas» → opciones de HU parecidas → «Evoluciona AFQP-25» → silencio.

## Tareas (`web/src/screens/Origin/OriginScreen.tsx` y sus pruebas)
1. **Sin operación elegida** (`operation === undefined`), un mensaje nuevo **vuelve a pedir la propuesta**:
   - `POST /start/propose` con ese texto, el proyecto y el modo;
   - la nueva propuesta sale como **otro mensaje del asistente**, con sus opciones, y las anteriores quedan desactivadas. Así «Evoluciona AFQP-25» reconoce la clave y ofrece «Evolucionar AFQP-25»;
   - mientras espera, el composer queda desactivado;
   - si falla, la tarjeta de error de siempre (`ErrorCard`).
2. **Con la operación elegida**, el mensaje sigue siendo un detalle (restricción) para la generación, como hoy, pero el asistente **responde**: «Anotado: lo tendré en cuenta al generar.».
3. **Cuando la propuesta sale de una búsqueda por texto** (sin clave reconocida), el mensaje del asistente añade una línea fija: «Puedo crear una HU nueva, evolucionar una existente o preparar sus pruebas. No gestiono proyectos de Jira.».
   - En el flujo de QA, la frase equivalente para pruebas.
4. **El placeholder del composer** describe lo que hará:
   - sin operación elegida: «Escribe otra necesidad o una clave de Jira»;
   - con operación elegida: «Añade detalles a la necesidad (opcional)».

## Reglas
- **Solo** `web/src/screens/Origin/**`, y si hace falta `web/src/mocks/**` (la API simulada) y textos compartidos. No toques el cliente (`web/src/api/**`): es de la sesión MCP, que está probando la conexión en `ses-web`. Tampoco otras pantallas, ni `api/`, `core/` o `app/`.
- **Las convenciones de `web/`:** componentes existentes, textos en español, nada de `dangerouslySetInnerHTML`, enlaces por `safeHref`.
- **Pruebas (Vitest con MSW):**
  - un segundo mensaje sin operación vuelve a proponer (y reconoce una clave);
  - con operación elegida, el detalle se confirma;
  - la línea de capacidades solo en una búsqueda por texto;
  - el composer desactivado mientras espera;
  - un error de `/start/propose` muestra la tarjeta.

  Pruebas deterministas: nada que dependa de cuánto dura un estado en pantalla.
- **Verificación:** `npm run lint`, `npx tsc -b`, `npm test` y `npm run api:check` en verde (salvo las 2 o 3 de «Reintentar» ya conocidas: dilo si fallan).
- **No mates procesos globales.** Pídeselo también a los subagentes.
- **Kanban:**
  - fila en el registro;
  - propuestas en **PA-150…PA-199**, la primera libre.
- **Antes del commit:** `spec-checker` CONFORME y `security-reviewer` APTO.
- **Sin fusionar.** Haz `git push -u origin ses-origen` y avísame.

Empieza presentándome el plan antes de escribir código.
