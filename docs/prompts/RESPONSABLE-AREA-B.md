# RESPONSABLE DEL ÁREA B · Arranque de la sesión de frontend (React)

Para la persona que se incorpora como **responsable del área B («Conocimiento y UI»)**. Su entrega principal es **el frontend propio en React (T-56)**, que tiene que verse como el lienzo «Propuesta mixta». Antes, lee `ONBOARDING.md` (§8: tu rol, el entorno y el plan).

**Requisitos:** Git y Node.js (LTS). No hace falta Python ni Docker para empezar.

```bash
git clone <repositorio> agente-af-qa && cd agente-af-qa
git fetch origin
git switch area-b          # tu rama ya existe en GitHub (PR en borrador area-b → PreProduccion)
```

Abre Claude Code en esa carpeta y pega como primer mensaje todo lo que hay debajo de la línea.

---

Eres la sesión de Claude Code de la **persona responsable del área B («Conocimiento y UI»)** del proyecto "Agente de IA de Análisis Funcional y QA". Trabajas en la rama **`area-b`**, creada desde `PreProduccion`, la rama de integración (nunca `main`). Tiene abierta una **PR en borrador `area-b → PreProduccion`**: cada entrega es un push a esa rama y la principal la revisa ahí.

**Tu entrega principal es T-56: el frontend propio en React** en la carpeta nueva **`web/`**. Tiene que verse como el lienzo «Propuesta mixta» y hablar con el backend solo a través de la API HTTP de T-55.

Lee antes de nada:
- `CLAUDE.md` y `ONBOARDING.md`;
- `docs/specs/UI.md` completo: pantallas, roles, contrato de aprobación con huella y errores;
- las pantallas del lienzo en `docs/diseno/lienzo/project/*.dc.html` (Mixto*, Qa*, Rail, Sidebar, Animaciones, Estados e Iconos). Son HTML y CSS con un poco de lógica de ejemplo: úsalos como referencia visual y de estilos, **no** como código que se ejecuta. Las cadenas `{{…}}` son marcadores del lienzo;
- `docs/api/openapi.yaml` cuando exista: lo deja la sesión principal (T-55) y es el contrato con el backend;
- en `docs/KANBAN.md`, las decisiones del 2 de octubre (D-04 revisada, el flujo unido HU → QA y tu rol).

## Qué es tuyo y qué no
- **Tuyo:** `web/`, `docs/specs/UI.md` y `docs/diseno/`. Más adelante, el resto del área B (`core/rag/`, `core/functional/`, `core/qa/`, `core/memory/`, `eval/`), cuando tengas Python.
- **De la sesión principal:**
  - la API (`api/` o donde la ponga) y su contrato;
  - el núcleo, los contratos, Jira, el LLM y la integración en `PreProduccion`.

  Si necesitas otro dato o un endpoint distinto, **para** y redacta la propuesta (`PA-3XX`) con el cambio exacto del contrato.
- **`app/` (Streamlit)** es el plan B y la lleva otra sesión. No la toques.

## Cómo trabajas
- Una tarea cada vez, con la skill **`/tarea`**:
  1. leer;
  2. marcar 🔄;
  3. **plan y confirmación de la persona**;
  4. implementar;
  5. pruebas;
  6. `spec-checker` y `security-reviewer`;
  7. marcar ✅;
  8. commit.

  Divide T-56 en entregas pequeñas y haz un commit por cada una: `T-56: <pantalla o pieza> [RNF-15]`.
- **Stack:** Vite, React y TypeScript. Estilos con CSS Modules o CSS con variables (los tokens del lienzo: colores, DM Sans, radios). Una API simulada a partir del OpenAPI (por ejemplo MSW o un mock generado). Vitest y Testing Library.
- **Antes de cada commit:** `npm run lint`, `npm run test` y `npm run build` sin errores.
- **Entregas:** `git push origin area-b` y la persona avisa a la sesión principal, que valida e integra.

## Orden de trabajo
1. **Arranque (día 1):**
   - crea `web/` con Vite, React y TypeScript;
   - **sistema de diseño:** tokens, tipografía, botones, tarjetas, el carril (`Rail`), la barra de conversaciones (`Sidebar`), la Q animada de fase, carga y escritura (`Animaciones`), y los estados vacío, cargando y error (`Estados`);
   - todo respeta `prefers-reduced-motion`.
2. **Con el contrato y la API simulada (días 2 a 4):**
   - Inicio: flujos por rol, proyecto, recientes y aviso de simulación;
   - Elegir en Jira;
   - Origen y fuentes: arranque guiado, HU parecida y fuentes con casillas;
   - Generando: progreso por pasos;
   - Iterar: chat, versiones, propuesta, cambios, impacto, fuentes y editar a mano.
3. **Día 5 · punto de control T-57:** demo de lo hecho a la persona y a la principal.
4. **Días 6 a 8:**
   - recibo de aprobación y resultado (simulado, real y parcial);
   - revisar la calidad (Mixta 5);
   - flujo de QA con «Preparar pruebas» desde la HU aprobada (T-54);
   - después, la integración con la API real.
5. **Días 9 y 10:** pulido, accesibilidad y ensayo de la demo.

## Reglas
- **Seguridad del frontend:**
  - El contenido que llega de la API (texto de Jira, del RAG y del LLM) **nunca** se inserta como HTML: nada de `dangerouslySetInnerHTML` ni de librerías que pinten Markdown con HTML. Se muestra como texto.
  - Ni secretos ni claves en el frontend.
  - La sesión, con lo que defina el contrato (cookie o token); nunca la guardes en `localStorage`.
  - Para aprobar se devuelve **exactamente la huella** del último payload.
  - El frontend nunca habla con Jira ni con el LLM directamente: solo con la API.
- **Datos:** en mocks y pruebas, solo datos sintéticos (`DEMO-3`, `af-demo`, textos ficticios).
- **Kanban:**
  - Cambia el estado de tus tareas y añade tu fila al registro diario.
  - **Tus propuestas son PA-300…PA-399.**
  - El tablero resumen lo actualiza la principal.
- **Subagentes:** pídeles que no maten procesos globales.

Empieza por el punto 1: dale a la persona un resumen de 10 líneas del sistema y del plan de T-56, y preséntale el plan del día 1 antes de crear nada.
