# Guion de la demo · v1.0 (unos 15 minutos)

**Para:** quien presenta la demo y quien la ensaya (T-36). **Datos:** 100 % sintéticos, de la Biblioteca Municipal de Villaficticia (corpus de `data/seed/corpus` y proyecto de pruebas de `data/seed/jira`).

## Cómo está montada
- **En CPU, el modelo local es lento:** `qwen3:1.7b` va a unos 6 tok/s; una HU tarda 5–6 min y el flujo HU → QA completo, 15–20 min. Por eso **solo se hace en directo lo que no llama al LLM** (fuentes, recibo, aprobar, pasar a QA, registrar la ejecución) o se lanza al principio para que termine a tiempo (revisar la calidad). Lo demás se abre ya generado.
- **Las conversaciones preparadas** las genera de verdad `eval/demo_prepare.py` con el modelo local, sobre la misma composición que la API, y quedan en el checkpointer. Su lista, con ids, estado, modelo y tiempo, está en `docs/demo/preparadas.md`. Se abren desde la lista de conversaciones de cada usuario.
- **Usuarios:** `af-demo` (analista funcional) y `qa-demo` (QA). Dos pestañas del navegador, una por usuario.
- **Modo `simulation`** en toda la demo: el agente enseña lo que publicaría, sin escribir en Jira. La única excepción es el paso 8, preparado antes en el sandbox `AFQP` con autorización expresa.
- **Antes de empezar:** `docs/demo/CHECKLIST.md`.

## Mapa de la demo

| # | Paso del flujo | Min. | Quién | En directo | Se abre preparada |
|---|---|---:|---|---|---|
| 0 | Lanzar «Revisar la calidad» | 0,5 | `af-demo` | sí, en segundo plano | — |
| 1 | Nueva necesidad y **fuentes** | 2 | `af-demo` | sí (sin IA) | — |
| 2 | **Generar e iterar** | 2 | `af-demo` | no | `necesidad-iterada` |
| 3 | **Recibo y aprobar** en simulación | 2 | `af-demo` | sí (sin LLM) | `evolucion-en-revision` |
| 4 | **Pasar a QA** (T-54) | 2 | `af-demo` → `qa-demo` | sí (sin LLM) | `qa-encadenada-en-revision` |
| 5 | **Suite y aprobar** | 2 | `qa-demo` | sí (sin LLM) | `qa-directa-en-revision` |
| 6 | **Registrar la ejecución** (T-47) | 1,5 | `qa-demo` | sí (sin LLM) | `ejecucion-en-revision` |
| 7 | **Revisar la calidad** (resultado) | 1,5 | `af-demo` | sí | — |
| 8 | **Memoria** en `live` (sandbox `AFQP`) | 1,5 | `af-demo` | solo se enseña | `sandbox-hu-publicada` |
|   | Cierre | 0,5 | | | |

## Paso a paso

### 0 · Arranque: lanzar la revisión de calidad (30 s)
- **Se muestra:** con `af-demo`, «Revisar la calidad» de la HU `DEMO-3` (*Renovar un préstamo*) y su progreso por pasos. Tarda unos 5 min en CPU: estará lista en el paso 7.
- **Se abre:** nada preparado; se lanza y se deja trabajando.
- **En directo:** sí, en segundo plano.
- **Se dice:** «Mientras os enseño el flujo, el agente está revisando la calidad de una HU que ya existe en Jira. Volveremos a ella al final».
- **Plan B:** si falla o no termina, en el paso 7 se abre el informe guardado por el script, `docs/demo/calidad-DEMO-3.md`.

### 1 · Nueva necesidad y fuentes (2 min)
- **Se muestra:** Mixta 1 → «Nueva necesidad» en el proyecto de pruebas. Se escribe la necesidad: *«Las personas socias quieren recibir un aviso cuando una reserva esté lista para recoger, con el plazo de recogida y el mostrador»*. Se abre «Antes de generar»: el agente propone las fuentes del RAG (reglamento de préstamos, avisos) y las HU de Jira relacionadas, **sin IA**. Se desmarca una fuente.
- **Se dice:** «El agente no inventa: parte de Jira y de la documentación indexada. La persona decide qué fuentes entran. Nada de esto ha llamado todavía al modelo».
- **En directo:** sí. **No** se pulsa «Generar»: son 5–6 min.
- **Plan B:** sin red con Jira, la vista previa muestra solo el RAG; se comenta que la conexión a Jira es la del proyecto de pruebas. Si no carga nada, captura de esta pantalla del ensayo.

### 2 · Generar e iterar (2 min)
- **Se abre:** `necesidad-iterada` (la misma necesidad, ya generada y con una iteración).
- **Se muestra:** la HU con la plantilla completa (como… quiero… para…, CA en Gherkin `CA-01`…, RN `RN-01`…), las **citas** con su extracto real, el selector de versiones v1 → v2 y el cambio pedido en la iteración: *«Añade un criterio para cuando la reserva caduca sin que nadie la recoja»*. Se señala el modelo usado.
- **Se dice:** «Cada respuesta es una versión. La IA propone; la persona conversa, corrige o edita a mano. Las citas solo pueden apuntar a fuentes que estaban en el contexto».
- **En directo:** no (cada iteración son minutos). Si sobra tiempo, se escribe un feedback y se deja corriendo.
- **Plan B:** si la lista de conversaciones no carga (BD caída), `docs/demo/preparadas.md` y capturas.

### 3 · Recibo y aprobar en simulación (2 min)
- **Se abre:** `evolucion-en-revision` (evolución de `DEMO-3` con su diff frente a Jira y las HU afectadas).
- **Se muestra:** el **recibo**: las operaciones exactas que se harían en Jira (actualizar `DEMO-3`, comentario con el diff, vínculos «relates to» a las HU afectadas). Se pulsa **Aprobar**: la aprobación va ligada a la huella de esa versión y esa operación. El resultado es «simulada»: nada se escribe en Jira y queda en la auditoría.
- **Se dice:** «Nada llega a Jira sin una aprobación humana explícita de esta versión exacta. En simulación vemos el plan sin tocar Jira».
- **En directo:** sí (aprobar no llama al LLM).
- **Plan B:** si aprobar falla, se abre `evolucion-simulada` (ya aprobada en simulación).

### 4 · Pasar a QA (2 min) · lo que pidió dirección (T-54)
- **Se hace:** en `evolucion-en-revision`, ya simulada (o en `evolucion-simulada`), **«Pasar a QA»**. Se cambia a la pestaña de `qa-demo`: la HU aparece en su lista de QA, lista para recoger.
- **Se abre:** `qa-encadenada-en-revision`: una HU recogida por QA con su suite ya generada (casos `CP-01`…, cobertura de CA y RN, datos sintéticos, matriz y estrategia). No se ha releído Jira ni se ha vuelto a estructurar la HU: es la aprobada, tal cual.
- **Se pulsa Aprobar** y se enseña la regla: *«publica antes la HU»*. En simulación esa versión no está en Jira, así que sus casos no se pueden publicar.
- **Se dice:** «El analista no genera pruebas: pasa su HU a QA y cualquier persona de QA la recoge sin empezar de nuevo. Y el sistema impide publicar casos de una HU que aún no está en Jira».
- **En directo:** «Pasar a QA» sí (sin LLM). **No** se pulsa «Recoger» en directo: la recogida genera la suite (5–6 min).
- **Plan B:** si «Pasar a QA» falla, se abre directamente `qa-encadenada-en-revision`.

### 5 · Suite y aprobar (2 min)
- **Se abre:** `qa-directa-en-revision` (QA de una HU que ya está en Jira, `DEMO-3`).
- **Se muestra:** los casos, la cobertura y el recibo («publicar casos de prueba» como subtareas `caso-prueba` con la estrategia y la matriz como adjuntos). Se pulsa **Aprobar** → «simulada».
- **Se dice:** «Con una HU que ya está en Jira, QA aprueba y el agente publicaría los casos como subtareas, con la matriz de cobertura adjunta».
- **En directo:** sí (sin LLM).
- **Plan B:** `qa-directa-simulada` (ya aprobada).

### 6 · Registrar la ejecución (1,5 min) · T-47
- **Se abre:** `ejecucion-en-revision` (HU del sandbox con casos ya publicados).
- **Se muestra:** la lista de casos de la HU leída de Jira; se marca un caso como «pasó» y otro como «falló» con su evidencia (datos ficticios), el recibo y **Aprobar** → «simulada».
- **Se dice:** «QA registra el resultado de cada caso; con aprobación, el agente lo dejaría en cada subtarea de Jira».
- **En directo:** sí (sin LLM). Solo está en la API/frontend (la UI en Streamlit no lo tiene).
- **Plan B:** si no hay casos publicados (la preparación lo salta y lo anota en `preparadas.md`), se cuenta con una captura del ensayo.

### 7 · Revisar la calidad (1,5 min)
- **Se abre:** el resultado de la revisión lanzada en el paso 0.
- **Se muestra:** la valoración INVEST por letra y los hallazgos (ambigüedades, CA sin verificar, reglas sin fuente), con «Evolucionar con esto».
- **En directo:** sí (solo se abre el resultado; no se lanza nada nuevo).
- **Se dice:** «El agente también audita HU que ya existen; no publica nada: propone cómo mejorarlas».
- **Plan B:** `docs/demo/calidad-DEMO-3.md`, generado por el script de preparación.

### 8 · Memoria en `live` en el sandbox (1,5 min)
- **Preparado antes**, con autorización expresa, con `--sandbox-live` (ver «Preparación»): una HU del sandbox `AFQP` aprobada y **publicada de verdad** (`sandbox-hu-publicada`).
- **Se muestra:** la HU actualizada en Jira (`AFQP`), con el comentario del diff; su memoria sintética `data/memory/<CLAVE>.md` (objetivo, alcance, RN, decisiones, dependencias, cambios, CA y referencias); y, en «Antes de generar» de una necesidad nueva en `AFQP`, la memoria entre las primeras fuentes (se prioriza frente a la documentación base).
- **Se dice:** «Lo que se publica alimenta el conocimiento: la memoria resume la HU en muchos menos tokens y se reincorpora al RAG».
- **En directo:** solo se enseña; no se publica nada durante la demo.
- **Plan B:** la captura de la HU en Jira y el `.md` abierto en el editor.

### Cierre (30 s)
«La IA propone, la persona valida y Jira conserva solo lo aprobado. Todo con modelos abiertos y gratuitos, en local».

## Si algo falla
| Problema | Qué hacer |
|---|---|
| **Ollama caído o muy lento** | Todo lo de la demo funciona sin él salvo los pasos 0 y 7 (calidad): se usa el informe guardado. No se lanza nada nuevo con el LLM. |
| **Jira sin red** | Las conversaciones preparadas se abren igual (están en el checkpointer). Pasos 1 (las HU relacionadas) y 6 dependen de Jira: capturas del ensayo. |
| **429 o fallo de un proveedor** | La UI avisa del cambio de proveedor; se sigue con las preparadas. |
| **PostgreSQL caído** | No hay lista de conversaciones: se para la demo, `docker compose up -d db` y se vuelve a entrar (las sesiones duran 30 min). |
| **Una preparada en un estado inesperado** (por ejemplo, aprobada en el ensayo) | `uv run python -m eval.demo_prepare --real --rehacer <nombre>` antes de empezar (minutos). |

## Preparación
1. `docs/demo/CHECKLIST.md`, apartados 1–5.
2. Conversaciones en simulación (unos 30–45 min de CPU; **no** mientras otra sesión mida tiempos con el mismo Ollama):
   ```bash
   uv run python -m eval.demo_prepare --real --project DEMO --story DEMO-3 --qa-story DEMO-3
   ```
3. Solo con autorización expresa, sandbox en `live` (pasos 6 y 8):
   ```bash
   uv run python -m eval.demo_prepare --real --sandbox-live --confirmo-escritura-AFQP \
       --project AFQP --story <CLAVE-DE-AFQP>
   uv run python -m eval.demo_prepare --real --only ejecucion-en-revision \
       --project AFQP --qa-story <CLAVE-DE-AFQP> --execution-story <CLAVE-DE-AFQP>
   ```
4. Revisar `docs/demo/preparadas.md`: todo ✅ salvo lo que se salte a propósito.
5. Ensayo completo con cronómetro y capturas para los planes B.
