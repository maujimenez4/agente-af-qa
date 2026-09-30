# PROMPT-02 · Corpus sintético (T-09) · Sesión área B

Abre la sesión en el worktree del área B (`cd .claude\worktrees\area-b; claude`) y pega todo lo que hay debajo de la línea como primer mensaje.

---

Eres la sesión del **área B (Conocimiento y UI)** del proyecto "Agente de IA de Análisis Funcional y QA". Trabajas en el worktree `area-b` (rama `area-b`). Hoy toca la tarea **T-09: corpus piloto sintético**.

## Antes de nada
1. Trae lo último de la sesión principal: `git rebase main` (debe quedar sin conflictos).
2. Lee completos, en este orden: `CLAUDE.md`, `docs/specs/SPEC-00-fundacional.md` (congelada, v1.2, incluido el anexo §11), `docs/KANBAN.md` (T-09, T-12, T-15, T-17 y la sección "Decisiones del día 1") y `docs/decisiones/01_declaraciones_proyecto.md` (D-06, RF-07 a RF-12, RF-51).
3. Lee `tests/fakes/dataset.py`: el corpus debe ser **coherente** con ese dominio y sus reglas.
4. Cambia T-09 a 🔄 en el Kanban.

## Qué hay que construir
Un corpus de **15 a 25 documentos Markdown** en `data/seed/corpus/`, sobre un dominio **ficticio**: el servicio digital de la **Biblioteca Municipal de Villaficticia** (préstamo, reservas, renovaciones, socios, catálogo, sanciones, notificaciones…).

### Las 7 categorías (decisión del día 1)
| Slug (carpeta y `category`) | Categoría | Contenido típico |
|---|---|---|
| `normativa` | Normativa y reglamentos | Reglamento de préstamo, política de sanciones, protección de datos ficticia |
| `procesos` | Procesos de negocio | Alta de socio, circuito de reserva y recogida, devolución, reclamaciones |
| `especificaciones` | Especificaciones funcionales | Requisitos de módulos (préstamo digital, catálogo, notificaciones) |
| `glosario` | Glosario | Términos del dominio y siglas |
| `arquitectura` | Arquitectura e integraciones | Sistemas ficticios, APIs internas, integraciones con el catálogo y la pasarela de avisos |
| `manuales` | Manuales de usuario | Guías para socios y para personal de sala |
| `actas` | Actas y decisiones | Actas de reuniones ficticias con decisiones y cambios de reglas |

La categoría `memoria` queda reservada para las memorias que genera el agente: no la uses en el corpus.

### Reglas del dominio que no pueden contradecirse
Son las mismas de `tests/fakes/dataset.py`:
- Máximo **3 reservas activas** por persona socia.
- Una reserva bloquea el ejemplar **48 horas**.
- Un préstamo dura **21 días** y admite **2 renovaciones**, y no se renueva si hay reservas pendientes.

Puedes añadir más reglas (sanciones, límites por tipo de material, etc.), numeradas y citables, pero siempre coherentes entre documentos. Si un acta cambia una regla, el documento normativo afectado debe reflejar la versión vigente y citar el acta.

### Formato de cada documento
- Ruta: `data/seed/corpus/<slug>/<id>-<titulo-corto>.md`; el id tiene la forma `DOC-NN`.
- Cabecera YAML:
  ```yaml
  ---
  id: DOC-01
  title: Reglamento de préstamo
  category: normativa
  version: 1
  date: 2026-01-15          # fecha ficticia
  related: [DOC-05, DOC-12] # otros documentos citados
  epics: [EP-PRESTAMO]      # temas del índice (ver abajo)
  ---
  ```
- Encabezados `#`/`##`/`###` bien estructurados, porque la fragmentación de T-13 va por encabezados.
- Extensión variada, entre 300 y 1.500 palabras, en español.
- Al menos 2 documentos con tablas y 2 con listas numeradas de reglas (`RN-…` o «Artículo N»).
- Cubre las 7 categorías, con al menos 2 documentos en cada una.

### Índice para el seed de Jira
Crea `data/seed/corpus/README.md` con:
- la lista de documentos (id, título, categoría, temas);
- **3–4 temas de épica** (`EP-PRESTAMO`, `EP-RESERVAS`…) con 3–4 ideas de HU cada uno.

T-15 (área A) lo usará para sembrar Jira de forma coherente con el corpus. La épica de préstamo digital y sus HU de reservar, renovar y consultar el historial deben encajar con `DEMO-1` a `DEMO-4` del dataset de los fakes.

## Restricciones
- **Datos 100 % ficticios.** Ni nombres de personas, emails, teléfonos, DNI ni direcciones reales. Usa roles ("persona socia", "responsable de sala") o nombres claramente inventados, sin apellidos plausibles. Tampoco pongas organizaciones ni productos reales: los sistemas se llaman, por ejemplo, "CatálogoVF" o "AvisosVF".
- Ningún secreto ni URL real: solo dominios `.invalid` o `example`.
- No toques directorios del área A ni los contratos congelados (`schemas/`, `adapters/base.py`, `adapters/errors.py`, `core/config.py`, `core/container.py`). Si necesitas un cambio en ellos, **para y propónlo**.
- No implementes la ingesta (T-12) ni la fragmentación (T-13). Si ves mejoras, anótalas en el Kanban como "Propuesta adicional".

## Pruebas
Con el subagente `test-writer`, añade `tests/unit/test_corpus.py`, que compruebe:
- que hay entre 15 y 25 documentos, con al menos 2 por cada una de las 7 categorías;
- que las cabeceras son válidas, los `id` son únicos, `category` coincide con la carpeta y `related` apunta a ids existentes;
- que no aparece la categoría `memoria`;
- que no hay patrones de email, teléfono ni DNI/NIE;
- que las reglas clave (3 reservas, 48 h, 21 días, 2 renovaciones) aparecen en la normativa y no se contradicen.

## Cierre de la tarea
1. Ejecuta `uv run pytest -m "not integration"` y `uv run ruff check .`.
2. Pasa `spec-checker` y `security-reviewer` (este último, también para datos personales), y corrige lo que marquen.
3. Pon T-09 en ✅ y anota en el registro diario lo relevante.
4. Haz commit en la rama `area-b` con `T-09: corpus piloto sintético de Villaficticia [D-06]`. No fusiones en `main`: eso se hace en el punto de sincronización desde la sesión principal.
5. Dame un resumen de 3–5 líneas con el número de documentos por categoría y cualquier duda.

Empieza leyendo la documentación y presenta el plan (lista de documentos por categoría y temas de épica) **antes de escribir**. Espera mi confirmación.
