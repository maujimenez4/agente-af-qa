# SESIÓN SEGURIDAD · Ronda 6: especificaciones de Administración (PA-486, PA-487)

> Encargo de la **sesión Seguridad**. Tu ronda anterior ya está fusionada. El MVP está cerrado con la etiqueta `demo-comite`. Esta ronda **no escribe código**: deja dos especificaciones para v1.1.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/ses-seguridad switch -C ses-specs-admin origin/PreProduccion
cd .claude/worktrees/ses-seguridad
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA" (el asistente se llama **FAQ**), ahora en la rama **`ses-specs-admin`**, creada desde `PreProduccion`.

**Contexto:** el MVP está cerrado y mañana se presenta al comité. Quedan dos piezas de Administración que en la web salen «Disponible pronto»:
- **gestión de usuarios** (PA-486): hoy solo existe el comando `core.seed_users`;
- **subida de documentos a la base de conocimiento** (PA-487): hoy solo por comando, con `core/rag/ingest.py` y Docling.

Son sensibles (credenciales, datos personales, ficheros de terceros), así que primero va su **especificación**, revisada con calma. Esta ronda **no implementa nada**.

Lee:
- `CLAUDE.md` y la SPEC-00, sobre todo las secciones de seguridad, autenticación, RAG y API;
- en `docs/decisiones/01_declaraciones_proyecto.md`: RF-45, D-02, D-05 y D-06, y los RNF de seguridad y privacidad;
- `adapters/auth/` (argon2, bloqueo por intentos), `core/seed_users.py` y PA-279 y PA-284 (bajas, RGPD);
- `core/rag/` (`ingest.py`, `documents.py`, `chunking.py`, `indexing.py`) y `core/personal_data.py`;
- `api/admin.py` y `api/app.py`: permisos (`MANAGE_*`) y cómo se protegen las rutas de admin;
- `docs/specs/UI.md` §10 (Ajustes) y las filas PA-431 y PA-401;
- `docs/auditorias/AUDITORIA-2026-10-08.md`, lo que toque a autenticación y ficheros.

## Entregables
Dos documentos nuevos en `docs/specs/`, con la misma estructura:
1. **`SPEC-ADMIN-USUARIOS.md`** (PA-486)
2. **`SPEC-ADMIN-DOCUMENTOS.md`** (PA-487)

### Cada uno con
1. **Objetivo y alcance:** qué entra en v1.1 y qué no.
2. **Trazabilidad:** RF, RNF y D a los que responde. Si hace falta uno nuevo, proponlo como RF-XX con «Pendiente de la principal».
3. **Estado actual:** qué hay en el código y qué falta, con rutas de archivo.
4. **API propuesta:** rutas, métodos, cuerpos y respuestas (modelos pydantic en pseudocódigo), errores con su `code` y mensaje en español, y permisos por rol. **No toques `api/` ni el contrato:** es una propuesta.
5. **Flujo en la web:** pantallas de Ajustes, estados, errores y textos en español. Coherente con UI.md y el lenguaje de FAQ.
6. **Seguridad y privacidad**, con amenazas y mitigaciones:
   - **Usuarios:**
     - la contraseña se genera al azar y se muestra **una sola vez**, nunca en logs ni en respuestas repetibles;
     - argon2, bloqueo por intentos y política de contraseñas;
     - que un admin no pueda quitarse su propio rol ni dejar el sistema sin admin;
     - la baja con RGPD (PA-279, PA-284);
     - la auditoría de cada acción (`core/audit.py`).
   - **Documentos:**
     - tipos permitidos y tamaño máximo;
     - comprobación del tipo real (no solo la extensión);
     - nombres de fichero saneados y sin rutas;
     - procesado con Docling **en segundo plano**, con estado visible;
     - detección de datos personales y secretos antes de indexar;
     - duplicados, borrado y reindexado;
     - dónde se guarda el original y cuánto tiempo;
     - inyección de instrucciones en el texto de los documentos (se tratan como datos).
7. **Criterios de aceptación** numerados (CA-USR-NN y CA-DOC-NN), verificables y con al menos uno por riesgo de seguridad.
8. **Plan de pruebas:** qué va con fakes, qué es `integration` y qué se prueba en la web.
9. **Reparto por áreas y estimación:** qué es de la principal (`api/`, contrato, `core/config.py` si hace falta), del área A, del área B y de la sesión UI. Horas aproximadas y orden.
10. **Preguntas abiertas** para el usuario, cada una con una recomendación.

## Reglas
- **Solo documentación:** los dos documentos nuevos, `docs/KANBAN.md` y, si hace falta, una nota en la SPEC-00 que apunte a ellos. **Ningún cambio de código, del contrato ni de `schemas/`.**
- **Sin secretos ni datos reales** en los ejemplos: placeholders (`TU_CONTRASEÑA`) y datos ficticios.
- **Concreto y verificable:** rutas reales del repositorio, sin funciones inventadas. Si algo no existe, dilo.
- **Kanban:**
  - PA-486 y PA-487 a «Spec lista (fecha), pendiente de implementar»;
  - tu fila en el registro;
  - propuestas nuevas en **PA-496…PA-499**.
- **Antes del commit:** pasa `security-reviewer` sobre los dos documentos (que no filtren nada y que las mitigaciones sean suficientes) y corrige lo que marque. Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-specs-admin` y avísame con un resumen de cada spec: alcance, riesgos principales, estimación y preguntas abiertas.

Empieza presentándome el índice de cada documento y las dudas que tengas antes de redactarlos.
