# SESIÓN UI · Ronda 13: el asistente se llama FAQ (PA-478)

> Encargo de la **sesión UI**. Tu ronda 12 (auditoría de la web) ya está fusionada. El responsable de `web/` entregó T-56 y no está tocando `web/`: esta ronda es tuya.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```powershell
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/ses-ui switch -C ses-faq origin/PreProduccion
cd .claude/worktrees/ses-ui/web
npm ci
npm test
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-faq`**, creada desde `PreProduccion`. Tu ronda 12 ya está fusionada.

**Contexto:** el usuario ha decidido que el asistente se llama **FAQ** y quiere el nombre en **toda la web, de forma coherente**. Qaracter sigue siendo la marca; FAQ es el asistente. El diseño está aprobado y documentado en **`docs/diseno/faq/README.md`** (léelo entero: tiene los valores exactos). Junto a él, los prototipos de referencia (`login.dc.html` y los demás); son referencia visual, no código para copiar. Lee también `web/HANDOFF.md`, `web/DESIGN-DECISIONS.md` y `docs/specs/UI.md`.

## Tareas, por orden (propón el plan antes de escribir código)
1. **Un solo punto para el nombre.** Una constante (por ejemplo `ASSISTANT_NAME = 'FAQ'` en `web/src/text/`) usada en todos los textos nuevos. Si dirección cambia el nombre, debe bastar con cambiar esa línea y el logotipo del login.
2. **Inicio de sesión nuevo (§1 del README):** pantalla dividida.
   - **Mitad azul:**
     - el logotipo «FA» + la Q de Qaracter: DM Sans 800 a 120 px, la Q a **84 px**, **alineada a la línea base**;
     - el mensaje «Historias de usuario y pruebas en segundos. Siempre con tu aprobación.», con la segunda frase en naranja;
     - el pie «un asistente de **Qaracter**», solo esas palabras.
   - **Mitad blanca:**
     - el logo de Qaracter (`QaracterLogo`, PA-444) arriba;
     - «Hola de nuevo» y «Inicia sesión para continuar en FAQ.»;
     - el formulario de siempre con el botón naranja **«Entrar en FAQ»**.
   - **En ventanas estrechas,** la mitad azul arriba y el formulario debajo.
   - **No cambia** la lógica del login: los mismos campos, validaciones, errores y bloqueos.
3. **El nombre en el resto de la web (§2 del README):**
   - **pestaña:** «FAQ · Qaracter»;
   - **carril:** solo la Q, con `aria-label` y `title` «FAQ · Inicio»;
   - **Inicio:** «Hola, soy FAQ, tu asistente de análisis funcional y QA.», textos de las tarjetas y del cuadro de texto, y el pie de control;
   - **cabecera de la lista de conversaciones;**
   - **conversación:** la etiqueta «FAQ» bajo el avatar, «Ver la propuesta de FAQ» y el texto de control de la propuesta;
   - **esperas:** «FAQ está…», en `TypingIndicator` y en los pasos de Generando;
   - **títulos de error propios de la web.**
4. **Documentación:**
   - `UI.md`: el inicio de sesión nuevo y los textos con el nombre;
   - `DESIGN-DECISIONS.md`: el nombre, la constante y el logotipo con la Q;
   - `HANDOFF.md`, al día.

## Reglas
- **Solo `web/` y su documentación.** No toques `web/src/api/**` ni el esquema generado, `api/`, `core/`, `app/` ni el contrato, ni añadas dependencias.
- **Los textos que vienen del backend** (mensajes de error, títulos de conversación) **no se cambian**: salen tal cual.
- **Componentes compartidos que toques:** dilo en tu mensaje final con la lista exacta.
- **Accesibilidad:**
  - el logotipo «FAQ» es una imagen con nombre «FAQ», y las partes que lo forman, decorativas;
  - el contraste del texto sobre azul y del naranja, como mínimo 4,5:1 en texto normal;
  - todo funciona con el teclado.
- **Pruebas** (Vitest con MSW, deterministas, sin ampliar esperas): una por criterio. Incluye:
  - el login muestra el logotipo «FAQ», el mensaje, «un asistente de Qaracter», el logo de Qaracter, «Hola de nuevo» y el botón «Entrar en FAQ», y el inicio de sesión funciona igual que antes;
  - la constante del nombre se usa en Inicio, el carril, la conversación y las esperas: cambiarla cambia los textos;
  - el carril ya no muestra texto bajo la Q, pero su nombre accesible es «FAQ · Inicio»;
  - el título de la pestaña;
  - las pruebas existentes que comprueban los textos antiguos, actualizadas. No borres pruebas: adáptalas.
- **Verificación:**
  - `npm run lint`, `npx tsc -b`, `npm test` (dos veces), `npm run build` y `npm run api:check`;
  - Edge sin interfaz con un perfil nuevo, en otro puerto: capturas del login a 1280×800 y a 1024 al 125 %, de Inicio y de una conversación. Comprueba en la captura que la Q y «FA» tienen la misma altura.
  - La web del usuario (5173) y la API (8000) están en uso: no las toques.
- **No mates procesos.** Pídeselo también a los subagentes.
- **Kanban:**
  - cierra PA-478 con la fecha;
  - fila en el registro;
  - propuestas nuevas en **PA-479…PA-481**. Ya está previsto proponer el nombre en la firma de Jira y en el servidor MCP, que son del backend.
- **Antes del commit:** `spec-checker` CONFORME y `security-reviewer` APTO.
- **Sin fusionar.** Haz `git push -u origin ses-faq` y avísame, con las capturas.

Empieza presentándome el plan antes de escribir código.
