# PROMPT-05b · Anexo al día 5 · T-23 actualizado y T-49 (sesión del compañero)

Sustituye la parte de **T-23** de `PROMPT-05-dia5-companero.md` y añade **T-49**. **T-26 no cambia.**

Antes de pegar el mensaje, trae lo último de la rama de integración:

```bash
git fetch origin
git switch Dia5                       # si aún no existe: git switch -c Dia5 origin/PreProduccion
git merge origin/PreProduccion        # trae T-25 y las decisiones del día 6
uv sync
uv run alembic upgrade head           # migración 0002 (tabla artifact_state)
uv run pytest -m "not integration"
```

Si el merge da conflictos en `docs/KANBAN.md`, conserva las filas de las dos ramas. Si los da en un archivo de código, para y avisa.

---

Seguimos con el proyecto "Agente de IA de Análisis Funcional y QA" en la rama **`Dia5`**. Acabo de fusionar `origin/PreProduccion`, que trae:
- **T-25** (sesión principal): auditoría (`core/audit.py`), estado persistente de aprobaciones (`core/artifact_state.py`) y `publish` en **modo simulación** (`JIRA_PUBLISH_MODE=simulation` por defecto).
- **Las decisiones del día 6** en `docs/KANBAN.md` («Decisiones del día 6» y «Tareas añadidas el día 6»). Léelas antes de empezar.

**Este anexo sustituye las instrucciones de T-23 del prompt del día 5.** T-26 sigue igual. Las reglas de fusión, seguridad, Kanban y propuestas (desde PA-60) también siguen igual.

## Qué ha cambiado
- **La UI está decidida: «Propuesta mixta»**, en la página del mismo nombre del lienzo de diseño: https://claude.ai/artifact/PK7Mfx3z357t1x7e2hsSbB
- Es un asistente conversacional con **arranque guiado**. Ya no es el modelo de pestañas (Contexto, Historia, QA…) que pedía el prompt del día 5.
- **Se añade T-49 a tu área:** las categorías del RAG pasan a ser las de la presentación del proyecto.

## 1. `/tarea T-23`: `docs/specs/UI.md` a partir de la «Propuesta mixta» [RNF-15]
Sigue siendo **solo documentación, sin código**. Documenta las pantallas del lienzo, en este orden:

**Flujo de HU (analista funcional)**
1. **Mixta 1 · Inicio.** Cuatro tarjetas de flujo:
   - Nueva necesidad, Evolucionar HU y Revisar la calidad, para el analista.
   - Preparar pruebas, solo para QA.

   Además:
   - El cuadro de texto cambia su texto de ayuda según el flujo.
   - **Selector de proyecto**: todos los que ve la conexión (`list_projects`), con el último usado preseleccionado.
   - «Elegir en Jira», recientes del proyecto, lista de conversaciones con su proyecto y buscador.
   - Aviso de modo de prueba.
2. **Mixta 1b · Elegir en Jira.** Cascada Proyecto → Épica → HU (`list_projects`, `list_epics`, `list_children`) con búsqueda por texto o clave.
3. **Mixta 2 · Origen fijado.**
   - La HU parecida se busca en Jira **por texto, sin IA**.
   - Tarjeta «Operación fijada»: no cambia durante la conversación.
   - Panel «Antes de generar»: restricciones opcionales y **fuentes con casillas**.
4. **Mixta 2b · Generando.** La Q se llena un cuarto por proceso.
5. **Mixta 3 · Iterar.**
   - El chat sirve para pedir cambios (RF-20), con el indicador «Escribiendo la respuesta».
   - El panel tiene versiones (Jira, v1, v2…) y las pestañas Propuesta, Cambios, Impacto y Fuentes.
   - Los CA sin fuente se pueden *Confirmar* o pedir su fuente (*Pedir fuente*).
   - Botones *Editar a mano*, *Descartar* y *Revisar y aprobar*.
6. **Recibo de aprobación** (Trabajo 3 de la v2): una casilla por operación de Jira; el botón de aprobar se activa al marcarlas todas.
7. **Mixta 4 · Resultado:** simulado (no escribe; la aprobación sigue vigente) o real (operaciones hechas y memoria generada).
8. **Mixta 5 · Revisar la calidad:** informe INVEST con hallazgos. **No publica.**

**Flujo de QA**

9. **QA 1 a QA 6.** HU de origen, tipos de caso y fuentes → generando → iterar la suite → recibo → resultado → registro de la ejecución.
   - **QA 3** tiene las pestañas Casos (con Gherkin), Cobertura (matriz CA/RN × CP), Datos y riesgos, y Estrategia (= plan de pruebas).
   - **QA 4** es el recibo: subtareas con la etiqueta «caso-prueba» y la estrategia y la matriz como adjuntos `.md`.
   - **QA 5** muestra el resultado real, el parcial (con «Reintentar solo los fallidos», RNF-13) o el simulado.
   - **QA 6** registra la ejecución: Pasó, Falló, Bloqueado o Sin ejecutar, con evidencia y aprobación (R-01, opción A).

Para cada pantalla, el documento debe incluir:
- **Qué ve cada rol**, según `core/permissions.py`: el analista no prepara pruebas; QA solo prepara pruebas; el administrador ve Ajustes e Historial.
- **De qué depende en el backend.** Las pantallas que necesitan algo que todavía no existe se marcan con su tarea, sin inventar el contrato:
  - proyecto en la conversación → T-50;
  - fuentes excluidas, `plan` en la revisión y decisión `edit` → T-51;
  - conversaciones que se retoman → T-52;
  - reconocimiento de clave y HU parecida sin IA → T-53;
  - registro de la ejecución → T-47;
  - revisar la calidad → T-48;
  - reintentar los fallidos → PA-05.
- **Contrato de aprobación** (anexo §11 de la SPEC): la UI muestra el plan de operaciones y devuelve `{"decision": "approve", "fingerprint": …}` con la huella recibida. Sin huella no se aprueba.
- **Estados** vacío, cargando y error, con los mensajes en español de `adapters/errors.py`.
- **Animaciones:**
  - la Q de fase (sube un cuarto por fase);
  - la Q de carga por procesos;
  - la Q de «escribiendo»;
  - la entrada escalonada de la versión nueva con el cambio resaltado;
  - el recibo con casillas;
  - la Q que se completa al publicar.

  Todas respetan «reducir movimiento».
- **Viabilidad en Streamlit** (D-04, sin frontend separado). Para cada animación, indica cómo hacerla (SVG y CSS en `st.html` o un componente) y su alternativa estática si no es viable (PA-44). Lo que no se pueda hacer en Streamlit se anota como propuesta adicional; no se implementa.

No hace falta copiar el diseño en ASCII pantalla por pantalla. Basta con una tabla por pantalla (zona → contenido → acción → dependencia) y el enlace al lienzo.

## 2. `/tarea T-49`: categorías del RAG de la presentación [RF-12]
Hazla **después de T-26 y T-23**. Área B: `core/rag/`, `prompts/` y `data/seed/corpus/`.
- **Las 7 categorías nuevas:**
  - productos y servicios;
  - procesos de negocio;
  - políticas y reglas operativas;
  - documentación funcional y técnica;
  - glosarios, catálogos y criterios internos;
  - HU y artefactos previos;
  - estrategias, matrices y casos de prueba.

  Más `memoria`, que sigue reservada para el agente.
- **Qué hay que cambiar:**
  - `CATEGORIES` en `core/rag/documents.py`;
  - el prompt de clasificación, con su `version:` incrementada;
  - los metadatos del corpus de `data/seed/corpus/`, reasignando cada documento.
- **Comprueba que no se rompe:**
  - el par norma ↔ acta de `ContextService`, que usa `metadata["related"]`; las actas deben seguir encontrándose;
  - la evaluación de recuperación (`eval/`). Compara Recall@6 y MRR con los de ahora (0,90 y 0,95).
- **Reindexado:** describe en el PR el comando para reindexar el corpus. No lo ejecutes contra una base compartida.
- Si un cambio exige tocar `core/context/`, que es del área A, **para** y déjalo propuesto en el PR.

## Recordatorio
- **No toques:**
  - `core/graph/`, `core/context/`, `core/impact/`, `core/approvals.py`, `core/audit.py`, `core/artifact_state.py`;
  - `adapters/` (salvo las partes de tu área);
  - ni los contratos congelados.
- **Kanban:** cambia solo el estado de T-23, T-26 y T-49 y añade tu fila al registro diario.
- **Un PR por tarea** contra `PreProduccion`.

Presenta el plan de T-23 antes de escribir el documento.
