# SESIÓN UI · Ronda 10: arreglos de la web tras la prueba manual del usuario (PA-427…PA-431)

> Encargo de la **sesión UI**. Tu ronda 9 (`ses-web-fixes`) ya está fusionada. **Coordinado con el responsable de `web/`:** esta ronda es tuya y él no toca estos archivos mientras dure.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```powershell
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/ses-ui switch -C ses-web-pulido origin/PreProduccion
cd .claude/worktrees/ses-ui/web
npm ci
npm test
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-web-pulido`**, creada desde `PreProduccion`. Tu ronda 9 ya está fusionada.

**Contexto:** el usuario ha probado la web en React contra la API real y ha anotado cinco cosas. Lee:
- `web/README.md`, `web/DESIGN-DECISIONS.md` y `web/HANDOFF.md` (lo último fusionado: el escalado de Windows, PA-335; Editar a mano, parte B; el presupuesto al instante, PA-330);
- `docs/specs/UI.md`.

## Tareas
1. **PA-427 · Revisar la calidad: la Q no se anima mientras revisa.** En Generando, la Q de carga se anima mientras se genera. En la pantalla de calidad (`web/src/screens/Quality/`), mientras la revisión está `running` («Revisando la calidad de …»), la Q se queda quieta. Que se anime igual, con el mismo componente de `components/QMark/`, respetando «reducir movimiento».
2. **PA-428 · El texto de las fuentes sale con las marcas de Markdown.** En el panel de fuentes de la propuesta (HU y QA, `components/Proposal/ProposalViews.tsx`) y en el informe de calidad (`screens/Quality/`), los extractos del RAG son fragmentos de documentos en Markdown y se ven con `**`, `#`, `-` y tablas en bruto: por ejemplo, DOC-12 es una tabla.
   - Píntalos con el componente de Markdown seguro de PA-334 (`components/Markdown/`), **sin HTML ni `dangerouslySetInnerHTML`**.
   - Amplíalo para **tablas sencillas** (cabecera y filas, como `<table>` de React) y listas numeradas, si no las tiene.
   - Un extracto cortado a mitad de una tabla o de una marca no debe romper la pantalla: lo que no se reconozca, como texto.
3. **PA-429 · Al final de Generando e Iterar, el último mensaje queda cortado.** El botón naranja «Ver la propuesta» del último mensaje se ve cortado abajo y hay que desplazar para verlo entero. Que el chat deje margen al final y, al llegar un mensaje nuevo, lo muestre **entero** (el desplazamiento hasta abajo tiene que incluir ese margen). Compruébalo a 1280×800 y a 1024 al 125 %.
4. **PA-430 · Texto al iterar.** Mientras se genera una versión nueva tras pedir un cambio, el indicador dice «Escribiendo la respuesta» (`components/QMark/TypingIndicator.tsx`). Al iterar debe decir **«Generando una nueva versión…»**. Pásalo como `label` desde Iterar, sin cambiar el texto por defecto si se usa en otros sitios.
5. **PA-431 · Administración: lo que no está disponible tiene que decirlo.** En Ajustes, «Añadir documentos» (Elegir archivos) y «Usuarios y roles» salen desactivados sin explicación visible. Añade en cada tarjeta un distintivo o texto visible **«Disponible pronto»**, con el estilo de los demás «disponible pronto» de la web, y una frase breve:
   - documentos: «La carga de documentos llegará en una versión posterior.»;
   - usuarios: «Los usuarios se gestionan hoy desde el servidor.».

   No toques el resto de la pantalla: el responsable de `web/` la va a rehacer.

## Reglas
- **Solo `web/`.** No toques `web/src/api/**`, `api/`, `core/` ni `app/`.
- **Componentes compartidos que vas a tocar:** `components/Markdown/`, `components/Proposal/`, el chat (`components/Chat/` o `Workspace`) y `TypingIndicator`. Avísalo en tu mensaje final con la lista exacta.
- **Pruebas (Vitest con MSW, deterministas, sin ampliar esperas):**
  - la Q animada en una revisión en curso y quieta con «reducir movimiento»;
  - extractos con negritas, títulos, listas, tablas y un `<script>` o `<img onerror>`, este último como texto;
  - el mensaje final visible entero, comprobando la estructura y el desplazamiento;
  - «Generando una nueva versión…» al iterar;
  - los «Disponible pronto» de Administración.
- **Verificación:**
  - `npm run lint`, `npx tsc -b`, `npm test` (dos veces) y `npm run api:check`;
  - Edge sin interfaz con un perfil nuevo, a 1280×800 y 1024 al 125 %, para PA-429 y PA-428.
- **No mates procesos.** Pídeselo también a los subagentes.
- **Kanban:**
  - añade PA-427…PA-431 como hechas con la fecha;
  - fila en el registro;
  - propuestas en **PA-131…PA-139**.
- **Antes del commit:** `spec-checker` CONFORME y `security-reviewer` APTO.
- **Sin fusionar.** Haz `git push -u origin ses-web-pulido` y avísame.

Empieza presentándome el plan antes de escribir código.
