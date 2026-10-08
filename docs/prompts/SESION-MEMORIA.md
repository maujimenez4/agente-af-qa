# SESIÓN UI · Ronda 11: el logo completo de Qaracter en el login (PA-444)

> Encargo de la **sesión UI**. Tu ronda 10 ya está fusionada. El responsable de `web/` entregó T-56 (PR #18) y no está tocando `web/`: esta ronda es tuya.

La carpeta `ses-ui` se borró en la limpieza. Créala de nuevo y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```powershell
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git worktree add .claude/worktrees/ses-ui -b ses-login-logo origin/PreProduccion
cd .claude/worktrees/ses-ui/web
npm ci
npm test
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-login-logo`**, creada desde `PreProduccion`. Tu ronda 10 ya está fusionada y T-56 está entregada.

**Contexto:** dirección pide que la pantalla de inicio de sesión muestre el **logotipo completo de Qaracter**: la Q naranja con las letras «qaracter». Hoy solo muestra la Q (`QLogo`, en `web/src/screens/Login/LoginScreen.tsx`).
- El logo sale del «Qaracter Design System», del que se hizo el lienzo.
- Está copiado en `docs/diseno/marca/`:
  - `logo-qaracter-oscuro.svg`: Q `#FF7932` y letras `#233441`, para fondo claro;
  - `logo-qaracter-blanco.svg`: letras blancas, para fondo oscuro.
- Los dos son SVG con trazados, sin scripts ni enlaces (comprobado).
- Reglas del sistema de diseño: altura mínima de 24 px y margen libre de media Q alrededor.

Lee `web/README.md`, `web/DESIGN-DECISIONS.md`, `web/HANDOFF.md` y `docs/specs/UI.md`, y fíjate en el inicio de sesión.

## Tarea: PA-444
1. **Componente del logo completo** (por ejemplo `QaracterLogo`, junto a `components/QMark/`):
   - pinta el SVG **dentro del propio código**, como hace `QLogo` con `Q_PATH`, y no lo carga desde un archivo externo ni desde una URL;
   - reproduce el original tal cual: no redibujes ni aproximes los trazados;
   - la Q usa `var(--color-primary)` si coincide con `#FF7932`; si no, el color del original;
   - accesible: `role="img"` y `aria-label="Qaracter"`; o decorativo si al lado ya está el nombre.
2. **En el login**, sustituye la Q sola por el logo completo encima del título:
   - una altura que respete el mínimo y quepa a 1024 al 125 %;
   - el resto de la pantalla se queda igual.
3. **No toques** la Q del carril, de Inicio ni del asistente: se quedan con `QLogo`.
4. **Documenta** en `UI.md` (pantalla de inicio de sesión) y en `DESIGN-DECISIONS.md` de dónde sale el logo.

## Reglas
- **Solo `web/` y su documentación.** No toques `web/src/api/**`, `api/`, `core/` ni `app/`, ni añadas dependencias.
- **Pruebas (Vitest, deterministas):**
  - el login muestra el logo con su nombre accesible «Qaracter»;
  - la Q sola sigue en el carril;
  - el SVG no lleva `<script>`, `<image>` ni `href` externos.
- **Verificación:**
  - `npm run lint`, `npx tsc -b`, `npm test` (dos veces), `npm run build` y `npm run api:check`;
  - Edge sin interfaz con un perfil nuevo, a 1280×800 y a 1024 al 125 %: haz una captura del login.
- **No mates procesos.** Pídeselo también a los subagentes.
- **Kanban:**
  - cierra PA-444 con la fecha;
  - fila en el registro;
  - propuestas en **PA-448…PA-449**.
- **Antes del commit:** `spec-checker` CONFORME y `security-reviewer` APTO.
- **Sin fusionar.** Haz `git push -u origin ses-login-logo` y avísame, con las capturas.

Empieza presentándome el plan antes de escribir código.
