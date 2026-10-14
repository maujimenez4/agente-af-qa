# SESIÓN UI · Ronda 14: *Editar a mano* la suite de QA (PA-158)

> Encargo de la **sesión UI**. Tu ronda 13 (PA-478, el nombre FAQ) ya está fusionada. El MVP está cerrado con la etiqueta `demo-comite`; esto es **v1.1** y **no se fusiona hasta después de la presentación al comité**.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```powershell
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/ses-ui switch -C ses-editar-suite origin/PreProduccion
cd .claude/worktrees/ses-ui/web
npm ci
npm test
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA" (el asistente se llama **FAQ**), ahora en la rama **`ses-editar-suite`**, creada desde `PreProduccion`. Tu ronda 13 ya está fusionada.

**Contexto:** el MVP está cerrado (etiqueta `demo-comite`) y mañana se presenta al comité. Esta ronda es **v1.1**: se queda en tu rama hasta después de la presentación. En QA, *Editar a mano* sale hoy «Disponible pronto» y la suite solo se cambia conversando. El backend **ya lo admite**: `POST /conversations/{id}/edit` acepta `content: UserStory | TestSuite`, la `fingerprint` de lo mostrado y una nota opcional (`api/models.py`, `EditIn`). Una edición inválida no da error HTTP: la revisión sigue con `review.error` (UI.md §5).

Lee:
- la fila **PA-158** de `docs/KANBAN.md`, y PA-340 y PA-346;
- `docs/specs/UI.md` §6.3 (QA) y §4.5 bis (el *Editar a mano* de la HU, que ya existe);
- `schemas/test_case.py`: `TestSuite`, `TestCase`, `TestStep`, tipos, prioridad y referencias a CA y RN;
- `web/HANDOFF.md`, `web/DESIGN-DECISIONS.md` y el editor de la HU ya hecho en `web/src`.

## Tareas, por orden (propón el plan antes de escribir código)
1. **Editor de la suite**, con el mismo patrón que el de la HU: en el panel derecho, por grupos.
   - **Casos:** título, tipo, prioridad, precondiciones, pasos (acción, datos, resultado esperado), Gherkin y los CA y RN que verifica.
   - **Operaciones sobre casos:** añadir, quitar y reordenar casos y pasos.
   - **Datos de prueba y estrategia:** si están en el esquema.
2. **Validación igual que la del backend:** lo obligatorio, formato de los ID `CP-NN`, ID sin duplicar, al menos un caso positivo y uno negativo, y referencias solo a CA y RN que existan en la HU. Los errores se muestran junto al campo.
   - **La cobertura en vivo:** el aviso «Falta un caso para CA-NN» se recalcula al editar, con las mismas reglas que la pestaña *Cobertura*. Un CA sin caso bloquea la aprobación; una RN sin caso solo avisa.
3. **Guardar:** *Guardar la versión N+1* llama a `POST /edit` con la suite completa, la `fingerprint` mostrada y la nota. Se guarda como versión nueva sin llamar al modelo, y la nota queda en la conversación.
   - **Si la API devuelve `review.error`,** se muestra su mensaje tal cual.
   - **Cancelar con cambios** pregunta antes de perderlos, como en la HU.
4. **Quitar el «Disponible pronto»** de *Editar a mano* en QA. Si el texto queda solo como enlace a esta función, ajusta el `SoonButton` (PA-346) o elimina su uso aquí.
5. **Documentación:**
   - `UI.md` §6.3, el editor de la suite;
   - `DESIGN-DECISIONS.md`;
   - `HANDOFF.md`.

## Reglas
- **Solo `web/` y su documentación.** No toques `web/src/api/**`, el esquema generado, `api/`, `core/`, `schemas/` ni el contrato, ni añadas dependencias.
- **Si el contrato no basta,** para y descríbelo como propuesta. Por ejemplo, si falta un campo de la suite en la respuesta.
- **Principio 1:** editar no publica nada. La aprobación sigue siendo el recibo de siempre, con la huella de la **versión editada**.
- **Accesibilidad:**
  - todo funciona con el teclado, también añadir, quitar y mover casos y pasos;
  - cada error está asociado a su campo y se anuncia;
  - el contraste es como mínimo 4,5:1.
- **Pruebas** (Vitest con MSW, deterministas, sin ampliar esperas), al menos una por criterio:
  - abrir el editor con la suite actual;
  - editar un caso y guardar: el cuerpo de `POST /edit` lleva la suite completa, la huella y la nota;
  - las validaciones de los ID duplicados o vacíos, la de positivo y negativo, y la de referencias a CA inexistentes;
  - la cobertura en vivo: quitar el único caso de un CA bloquea la aprobación; uno de una RN solo avisa;
  - `review.error` de la API mostrado tal cual;
  - cancelar con cambios pregunta antes;
  - el editor se maneja con el teclado.
- **Verificación:**
  - `npm run lint`, `npx tsc -b`, `npm test` (dos veces), `npm run build` y `npm run api:check`;
  - capturas con Edge sin interfaz, con un perfil nuevo y en otro puerto, a 1280×800 y a 1024 al 125 %: el editor con un caso abierto, con un error y con el aviso de cobertura.
  - La web del usuario (5173) y la API (8000) pueden estar en uso para preparar la demo: **no las toques**.
- **No mates procesos.** Pídeselo también a los subagentes.
- **Kanban:**
  - cierra PA-158 con la fecha;
  - tu fila en el registro;
  - propuestas nuevas en **PA-488…PA-491**.
- **Antes del commit:** `spec-checker` CONFORME y `security-reviewer` APTO.
- **Sin fusionar.** Haz `git push -u origin ses-editar-suite` y avísame, con las capturas.

Empieza presentándome el plan antes de escribir código.
