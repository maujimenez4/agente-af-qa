# SPEC-ADMIN-DOCUMENTOS · Subir documentos a la base de conocimiento desde Administración

| Campo | Valor |
|---|---|
| Versión | 1.0 · borrador para revisión (2026-10-14) |
| Propietario | Sesión Seguridad (redacta) · sesión principal (aprueba contrato y RF) |
| PA | PA-487 (sustituye el alcance de PA-235; cierra lo pendiente de PA-21 al implementarse) |
| Responde a | RF-07 a RF-12, RF-49, RF-53 (propuesto), D-02, D-06, D-13, D-14, RNF-05, RNF-06, RNF-07, RNF-08, RNF-12, RNF-14, RNF-23, RNF-26 |
| Estado | Especificación. **No hay código**: rutas, modelos y nombres nuevos son una propuesta |

> Convención: lo que **ya existe** se cita con su ruta (`archivo:línea`). Lo que se propone va marcado como **(nuevo)**. Los ejemplos usan documentos y datos ficticios.

---

## 1. Objetivo y alcance

Que la persona con rol `admin` añada documentos a la base de conocimiento de FAQ desde **Ajustes**, con el mismo resultado que hoy da `python -m core.rag.indexing` (troceado, embeddings y metadatos), pero sin acceso al servidor y con controles de seguridad y privacidad antes de indexar.

### Entra en v1.1
1. Subir **un** archivo PDF, DOCX, MD o TXT de hasta 20 MB, eligiendo su **categoría**.
2. Procesado **en segundo plano** (extracción con Docling, comprobaciones, troceado, embeddings e indexado) con estado visible.
3. Rechazo antes de indexar si el detector encuentra **datos que parecen personales o secretos** (email, teléfono, DNI/NIE, IBAN, credenciales), más una **declaración obligatoria** del admin de que el documento no contiene datos personales reales (el detector no reconoce nombres, direcciones ni datos de salud, §6.5).
4. Lista de documentos de la base de conocimiento (corpus y subidos), con categoría, fragmentos y origen.
5. **Borrar** un documento subido o del corpus.
6. **Reemplazar** un documento subido indicando cuál, y **volver a vectorizar** los fragmentos guardados.
7. Auditoría de cada subida y cada borrado.

### No entra (v1.1)
- Subidas múltiples, carpetas o ZIP; la ingesta de una carpeta sigue por comando (RF-49, `core/rag/indexing.py:129-160`).
- OCR de PDF escaneados; un PDF sin texto se rechaza con «no contiene texto».
- Editar el texto de un documento o llevar versiones.
- Anonimizar automáticamente (RNF-08, v2.0): se rechaza, no se limpia.
- Borrar o reindexar **memorias** (`categoría memoria`): las gestiona el flujo de publicación (`core/memory/`).
- Gestión de documentos en Streamlit (plan B).

## 2. Trazabilidad

| Referencia | Texto (resumen) | Relación |
|---|---|---|
| RF-07 | Cargar PDF, DOCX, MD y TXT a la base de conocimiento — ✅ (por comando) | Se amplía a la web |
| RF-08 / RF-09 / RF-10 | Extraer y normalizar; fragmentar con solapamiento; vectorizar con metadatos — ✅ | Se reutiliza `core/rag/` |
| RF-11 / RNF-14 | Recuperar con la fuente citada | Los documentos subidos se citan igual que los del corpus |
| RF-12 | Clasificar en las 7 categorías — ✅ (con LLM) | En la web la categoría la elige el admin (§6.6) |
| RF-49 | Ingerir los documentos de una carpeta configurada — ✅ | Se mantiene por comando |
| **RF-53 (nuevo, propuesto)** | «Cargar documentos desde la web con procesado en segundo plano y estado visible» · EP-02 · v1.1 · Should | **Pendiente de la principal** |
| D-02 | Sin rol de gestor de conocimiento: el admin hace la carga base | Solo `admin` (`Permission.MANAGE_DOCUMENTS`) |
| D-06 | El RAG base del MVP es un corpus sintético | Se rechazan documentos con datos que parecen personales (§6.5) |
| D-13 / D-14 | Docling en el stack; solo modelos open-weight gratuitos | Docling en un proceso aparte; sin LLM en la carga (§6.6) |
| RNF-05 | Acceso según el tipo de usuario | `MANAGE_DOCUMENTS` (`core/permissions.py:20`), solo `admin` |
| RNF-06 / RNF-08 | Solo datos sintéticos; anonimizar antes de un LLM externo | La carga no llama a ningún LLM, pero **lo indexado sí se envía** como contexto a Groq al generar HU (§6.6): el control es la detección más la declaración del admin |
| RNF-07 | Opción local | Embeddings locales (`bge-m3`, `config/models.yaml:64`) |
| RNF-26 | Lockfile con hashes | `python-multipart` pasa a dependencia directa |
| R-08 | RAM del equipo limitada | Un solo proceso de Docling (§6.4, §6.12) |

## 3. Estado actual

| Pieza | Qué hay | Qué falta |
|---|---|---|
| Entrada | `python -m core.rag.indexing [carpeta]` (`core/rag/indexing.py:129-160`), carpeta por defecto `data/seed/corpus` | Ruta HTTP |
| Ingesta | `core/rag/ingest.py` `Ingestor.ingest(path)` (l. 116), `ingest_dir` (l. 151) | — |
| Tipos | `SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".md", ".txt")` (`core/rag/documents.py:25`); **solo la extensión** (`ingest.py:119-124`) | Comprobar el tipo real |
| Tamaño | `DEFAULT_MAX_BYTES = 20 MB` (`ingest.py:36`) | **Sin límite de páginas ni de tiempo** para Docling (PA-21) |
| Docling | `DoclingExtractor` (`ingest.py:78-97`); `.txt` sin Docling; conversor sin opciones (`_default_converter`, l. 211-216). `DocumentConverter.convert` admite `max_num_pages` y `max_file_size` (comprobado en la versión instalada) | Usar esos límites y un tope de tiempo |
| Raíz y symlinks | `ingest_dir` los filtra (l. 152-161); `ingest(path)` **no** (PA-21) | Escribir y leer solo dentro de la carpeta de subidas |
| Delimitadores | `escape_data` en la ingesta (PA-215, l. 194-196) y en `render_context` (`core/functional/context.py:79-105`) | — |
| Identificador | id de la cabecera o `path.stem` (l. 141); `uuid5` en PostgreSQL (`adapters/vectorstore/pgvector.py:27, 108-110`). **El mismo id sobrescribe** | Id generado por el servidor y control de duplicados |
| Duplicados | `has_document` existe (`adapters/base.py:164-179`) pero la ingesta no lo usa; `ix_documents_content_hash` existe y nadie lo consulta | Rechazar el mismo contenido |
| Clasificación | `Ingestor._classify` con `TaskType.CLASSIFY_SOURCE`; la cadena empieza en **Groq** (`config/models.yaml:60`): el texto sale a un LLM externo | Categoría del formulario, sin LLM |
| Datos personales | `core/personal_data.py` (`personal_data_kind`, l. 33; `looks_like_secret`, l. 99-102); **no se usan en `core/rag/`** | Comprobación antes de indexar |
| Indexado | `CorpusIndexer.index_dir` (`indexing.py:93-117`): embeddings antes de borrar; `replace_document` atómico | Indexar un documento suelto |
| Borrado | `VectorStore.delete_by_document` existe; **no hay ruta ni comando** de borrado | Ruta de borrado |
| Tablas | `documents` y `chunks` (`migrations/versions/0001_initial.py:123-170`); `documents` no guarda quién lo subió, tamaño, tipo ni estado | Tabla de trabajos de subida (§4.4) |
| Originales | No se guardan; `data/uploads/` está en `.gitignore:21` pero ningún código la usa | Carpeta temporal de procesado |
| API | Sin rutas con ficheros ni multipart; `BodyLimitMiddleware` **global** de 256 KB (`api/security.py:164-204`, `core/config.py:293`); `python-multipart` solo transitiva | Ruta multipart con límite propio |
| Segundo plano | `Runtime.submit` con hilos `api-job` (`api/runtime.py:166-174`, `api_workers=4`); patrón de la revisión de calidad (`api/app.py:889-937`); la cola no tiene tope (auditoría, l. 75) | Proceso aparte para Docling y cola acotada |
| Web | `SoonCard` (`web/src/screens/Admin/AdminScreen.tsx:280-302`): «Añadir documentos a la base de conocimiento» con «Disponible pronto» y `SoonButton` «Elegir archivos» (`adminText.ts:27-35`) | La tarjeta real |

## 4. API propuesta

**No se toca `api/` ni el contrato en esta ronda.** Rutas bajo `APIRouter(prefix="/admin")` (`api/admin.py:40`), con `session_for` + `require(user, Permission.MANAGE_DOCUMENTS)`.

### 4.1 Rutas

| Método y ruta | Qué hace | Respuesta |
|---|---|---|
| `POST /admin/documents` (multipart) | Sube un archivo y encola su procesado | 202 `DocumentJobOut` (`state="queued"`) |
| `GET /admin/documents/jobs/{job_id}` | Estado del procesado (la web consulta cada 2 s) | 200 `DocumentJobOut` |
| `GET /admin/documents/jobs` | Trabajos recientes del admin (últimos 20) | 200 `list[DocumentJobOut]` |
| `GET /admin/documents` | Documentos de la base de conocimiento (sin memorias) | 200 `DocumentsOut` |
| `DELETE /admin/documents/{document_id}` | Quita un documento y sus fragmentos | 204 |
| `POST /admin/documents/{document_id}/reindex` | Vuelve a calcular los embeddings de sus fragmentos guardados | 202 `DocumentJobOut` |

### 4.2 Modelos (pseudocódigo pydantic, **nuevo** en `api/models.py`)

```python
Category = Literal["productos", "procesos", "politicas", "documentacion",
                   "glosarios", "historias", "pruebas"]          # CATEGORIES sin "memoria"
JobState = Literal["queued", "processing", "indexed", "rejected", "error"]

# Formulario multipart de POST /admin/documents
#   file: UploadFile                (un solo archivo)
#   category: Category              (obligatoria)
#   no_personal_data: Literal[True] (obligatoria: «Declaro que no contiene datos personales reales»; se audita)
#   replace_document_id: str | None (sustituir ese documento subido; None = documento nuevo)

class DocumentJobOut(BaseModel):
    id: UUID                       # id del trabajo
    document_id: str               # "web-<8 hex>" generado por el servidor (§6.3)
    filename: str                  # nombre saneado (título por defecto), nunca la ruta original
    category: Category
    state: JobState
    pages: int | None
    chunks: int | None             # al terminar
    error: ErrorBody | None        # rejected / error: code y mensaje, nunca el texto del documento
    created_at: datetime
    updated_at: datetime

class DocumentRow(BaseModel):
    document_id: str
    title: str
    category: Category
    chunks: int
    origin: Literal["corpus", "web"]
    uploaded_by: str | None        # solo los subidos desde la web
    created_at: datetime

class DocumentsOut(BaseModel):
    documents: list[DocumentRow]
```

### 4.3 Errores

Se reutilizan `invalid_request`, `forbidden`, `not_found`, `rate_limited`, `service_unavailable` y `operation_failed` (`api/models.py:39-74`) y se proponen **cuatro nuevos** (cambio de contrato de la principal):

| HTTP | `code` | Cuándo | Mensaje |
|---|---|---|---|
| 401 | `unauthenticated` | Sin sesión | «Inicia sesión para continuar.» |
| 403 | `forbidden` | Sin `MANAGE_DOCUMENTS`, sin CSRF u origen no permitido, o borrar una memoria | «No tienes permiso para realizar esta acción.» / «Las memorias se gestionan al publicar una HU, no desde aquí.» |
| 404 | `not_found` | Documento o trabajo inexistente | «No existe el documento «x».» |
| — (en el trabajo) | `duplicate_document` **(nuevo)** | Al procesar: el mismo contenido (`content_hash` del texto extraído) ya está indexado | «Ese contenido ya está en la base de conocimiento como «X».» |
| 413 | `file_too_large` **(nuevo)** | Más de 20 MB, al subir | «El archivo supera el tamaño máximo (20 MB).» |
| — (en el trabajo) | `file_too_large` | Más de 300 páginas, al procesar | «El documento supera el máximo de 300 páginas.» |
| 415 | `unsupported_file_type` **(nuevo)** | El contenido no es PDF, DOCX, MD ni TXT, aunque lo diga la extensión | «Solo se admiten PDF, DOCX, MD y TXT; el contenido de «x» no corresponde a ninguno.» |
| — (en el trabajo) | `personal_data_detected` **(nuevo)** | Al procesar: el texto parece llevar datos personales o secretos (§6.5) | «El documento parece contener un email (línea 12). Usa datos ficticios y vuelve a subirlo.» |
| 422 | `invalid_request` | Falta el archivo, la categoría o la declaración; la categoría no es válida; o llega más de un archivo o campo | «Elige una categoría válida.» / «Confirma que el documento no contiene datos personales reales.» |
| 404 | `not_found` | `replace_document_id` no es un documento subido | «No existe el documento «x».» |
| 429 | `rate_limited` | Ya tiene un documento en proceso, o la cola está llena (§6.4) | «Ya hay un documento procesándose. Espera a que termine.» con `retry_after` |
| 503 | `service_unavailable` | Base de datos o embeddings no disponibles | «No se pudo acceder a la base de conocimiento.» |
| — (en el trabajo) | `operation_failed` | Docling falla, supera el tiempo o la memoria, o el texto supera los topes | «No se pudo extraer el texto de «x».» / «El documento tarda demasiado en procesarse (más de 120 s).» / «El documento es demasiado grande para procesarlo.» |

Igual que en la revisión de calidad, lo que se detecta **al procesar** no es un error HTTP: llega en `DocumentJobOut.state = "rejected"` (o `"error"`) con su `error.code` (filas «en el trabajo»). Los mensajes no repiten texto del documento (ni títulos de sección): solo el tipo y la línea.

### 4.4 Piezas internas (propuesta)

- **(nuevo)** tabla `document_jobs` en la migración 0007: `id`, `document_id`, `filename`, `category`, `state`, `content_hash`, `size_bytes`, `pages`, `chunks`, `error_code`, `error_message`, `uploaded_by`, `declared_no_personal_data`, `created_at`, `updated_at`. No guarda el texto ni el archivo. Se purga como las revisiones de calidad (`QUALITY_RETENTION_DAYS`, 90 días).
- **(nuevo)** `VectorStore.list_documents()` en `adapters/base.py` (congelado: la principal) y su implementación en `pgvector.py`, para `GET /admin/documents`. Las memorias (`category = "memoria"`) se excluyen.
- **(nuevo)** ajustes en `core/config.py`: `documents_upload_dir` (por defecto `data/uploads`), `documents_max_bytes` (20 MB), `documents_max_pages` (300), `documents_timeout_s` (120), `documents_max_memory_mb` (2048), `documents_max_chars` (2 000 000), `documents_max_chunks` (2000), `documents_queue_max` (3).
- **(nuevo)** excepción por ruta en `BodyLimitMiddleware` para `POST /admin/documents`: 20 MB + 64 KB de multipart, comparando método y ruta normalizada igual que `SessionGuardMiddleware` (con `root_path` y sin barra final). El resto de la API sigue en 256 KB. `SessionGuardMiddleware` ya comprueba sesión, origen y CSRF **antes** de leer el cuerpo (`api/security.py:207-242`).
- **(nuevo)** la ruta comprueba la cola (429) **antes** de leer el cuerpo y lee el formulario con `request.form(max_files=1, max_fields=4, max_part_size=…)`; copia el archivo por bloques a `data/uploads/<job_id>/` y cierra el temporal de Starlette (que se guarda en el TEMP del sistema a partir de 1 MB).
- **(nuevo)** `python-multipart` como dependencia directa en `pyproject.toml`, con hash en `uv.lock`.
- **(nuevo)** trabajador de documentos en `core/rag/` (p. ej. `core/rag/upload.py`) en dos partes:
  - **proceso aislado** (solo extracción): validación del tipo y Docling, con topes de tiempo y memoria, entorno mínimo **sin credenciales** (sin variables de Jira, Groq ni de la BD) y sin red; devuelve el texto o el error;
  - **proceso de la API** (fiable): ignora la cabecera YAML para `id`, `category` y `title`, aplica los topes de texto, detecta datos personales y secretos, trocea con `chunk_with_config`, calcula los embeddings e indexa con `replace_document`.
- **No** se reutiliza `Ingestor.ingest` tal cual: su cabecera YAML manda en `id` y `category` (`ingest.py:138-141`).

## 5. Flujo en la web

Coherente con UI.md §10 y la «Propuesta mixta». La tarjeta deja de ser «Disponible pronto» (`adminText.ts:27-35`; cambian `AdminSoon.pa431.test.tsx` y `AdminScreen.test.tsx`).

### 5.1 Tarjeta «Añadir documentos a la base de conocimiento»
- Texto: «PDF, DOCX, MD o TXT, hasta 20 MB y 300 páginas. Usa solo documentos sin datos personales reales: FAQ busca emails, teléfonos, documentos de identidad, IBAN y credenciales, pero no reconoce nombres, direcciones ni datos de salud. Lo indexado se usa como contexto con los modelos configurados, también externos.»
- Campo **Archivo** (`accept=".pdf,.docx,.md,.txt"`; la API decide igualmente), **Categoría** (desplegable obligatorio con los nombres que ya usa la web, `CATEGORY_NAMES` en `web/src/screens/Origin/operation.ts:92-101`: «Productos y servicios», «Procesos de negocio», «Políticas y reglas operativas», «Documentación funcional y técnica», «Glosarios y criterios internos», «HU y artefactos previos», «Estrategias y casos de prueba»), casilla obligatoria **«Declaro que el documento no contiene datos personales reales»**, opción **Reemplaza a…** (desplegable con los documentos subidos; vacío = documento nuevo) y botón *Subir*.
- Antes de enviar, la web comprueba tamaño y extensión para avisar pronto («El archivo supera los 20 MB.»), sin sustituir la comprobación de la API.

### 5.2 Progreso
- Fila del trabajo con el nombre saneado y su estado: «En cola» → «Procesando… (puede tardar un par de minutos)» → «Indexado · N fragmentos» o «Rechazado: …» / «Error: …» con el mensaje de la API tal cual.
- Consulta `GET /admin/documents/jobs/{id}` cada 2 s, con tope de tiempo (como PA-406).
- Mientras haya uno en proceso, *Subir* queda desactivado con «Espera a que termine el documento en proceso.».

### 5.3 Lista de documentos
- Tabla: **Documento** · **Categoría** · **Fragmentos** · **Origen** («Corpus» / «Subido por {usuario}») · **Acciones**.
- *Eliminar* abre la confirmación: «Se quitará «X» de la base de conocimiento: FAQ dejará de usarlo como fuente en las próximas propuestas. Las HU ya publicadas que lo citan no cambian.»
- *Volver a vectorizar*: «Se recalcularán los embeddings de sus fragmentos (por ejemplo, tras cambiar el modelo de embeddings).»
- Si el documento es del corpus, la confirmación añade: «Volverá a indexarse si alguien ejecuta la indexación del corpus por comando.»

### 5.4 Errores
- `ErrorCard` con el título por `code` (nuevos títulos: «Archivo demasiado grande», «Tipo de archivo no admitido», «Documento duplicado», «Datos personales detectados») y el mensaje de la API como texto.

## 6. Seguridad y privacidad

### 6.1 Amenazas y mitigaciones

| # | Amenaza | Mitigación |
|---|---|---|
| D-01 | Archivo enorme o cuerpo infinito que agota memoria o disco | Límite de 20 MB por ruta en `BodyLimitMiddleware` (cuenta los bytes en streaming); se escribe a disco por bloques; 413 `file_too_large` |
| D-02 | Tipo falso (un ejecutable o HTML con extensión `.pdf`) | Comprobación de la firma del contenido (§6.2); 415 `unsupported_file_type` |
| D-03 | Nombre con rutas o caracteres peligrosos (`../`, `C:\`, nombres reservados de Windows) | Saneado (§6.3); el archivo se guarda con un nombre generado, no con el del usuario |
| D-04 | Documento que bloquea o agota Docling (muchas páginas, PDF malicioso, bomba de descompresión en PDF o DOCX, XML con entidades) | Proceso aparte con topes de tiempo, **memoria** y páginas; límites del ZIP medidos al descomprimir; rechazo de `DOCTYPE`/`ENTITY` (§6.2, §6.4) |
| D-05 | Datos personales o secretos en la base de conocimiento (y, desde ella, en el contexto que va a Groq) | Detección antes de indexar con `core/personal_data.py` y declaración obligatoria del admin, auditada; riesgo residual R-DOC-5 (§6.5) |
| D-06 | El texto sale a un LLM externo | La carga no llama a ningún LLM (categoría del formulario); lo indexado **sí** va como contexto a los modelos configurados, por eso D-05 es el control (§6.6) |
| D-07 | Sobrescribir un documento del corpus o de otra persona sin querer | Id generado por el servidor (`web-` + 8 hex), la cabecera YAML no decide `id` ni `category`, y reemplazo solo indicando el documento (§6.3, §6.7) |
| D-13 | El proceso que analiza archivos de terceros tiene acceso a secretos o a la red | Entorno mínimo sin credenciales, sin red y modelos de Docling ya descargados (`HF_HUB_OFFLINE=1`) (§6.4) |
| D-08 | Inyección de instrucciones en el texto («ignora tus reglas…») | Se trata como datos: `escape_data` en la ingesta y en `render_context`, prompts que lo dicen (§6.9) |
| D-09 | El original queda en disco indefinidamente | Solo mientras se procesa; se borra siempre, también si falla (§6.8) |
| D-10 | Saturación por subidas repetidas | Un documento en proceso por admin y cola total de 3 (§6.4) |
| D-11 | Acceso de alguien sin permiso o CSRF | `require(..., MANAGE_DOCUMENTS)` y `session_for` en todas las rutas |
| D-12 | Fuga del contenido por logs, auditoría o errores | Logs y auditoría solo con id, hash, tamaño, páginas y fragmentos; los errores dan el tipo y la línea, nunca el valor ni títulos del documento |

### 6.2 Tipos permitidos y tipo real

| Tipo | Extensión | Comprobación del contenido |
|---|---|---|
| PDF | `.pdf` | Empieza por `%PDF-` |
| DOCX | `.docx` | ZIP válido con `[Content_Types].xml` y `word/document.xml`; tipo principal `…wordprocessingml.document.main+xml` (se rechazan `.docm`); sin `vbaProject.bin` ni objetos OLE (`word/embeddings/*`); sin entradas cifradas ni ZIP anidados; ninguna parte XML con `<!DOCTYPE` o `<!ENTITY` (XXE, *billion laughs*); relaciones `TargetMode="External"` rechazadas; como mucho 1000 entradas y 100 MB **contados al descomprimir en streaming** (no el tamaño que declara la cabecera) y una razón de compresión de 100 |
| MD / TXT | `.md`, `.txt` | UTF-8 válido (con o sin BOM) y sin bytes nulos |

- La extensión y el contenido tienen que coincidir.
- Sin dependencias nuevas para esto: comprobación propia de la firma (`filetype` solo es transitiva de Docling).

### 6.3 Nombres de fichero
- Se usa solo el nombre final (se quitan `/` y `\` y todo lo anterior), en NFC, con `[A-Za-z0-9._-]` y lo demás como `-`, sin punto inicial, sin nombres reservados de Windows (`CON`, `NUL`…), como mucho 100 caracteres.
- El archivo se escribe como `data/uploads/<job_id>/<uuid>.<ext>`; se comprueba con `resolve()` e `is_relative_to(upload_dir)` y sin seguir symlinks, como en `core/graph/nodes.py:1035-1041`.
- `document_id = "web-" + 8 caracteres hexadecimales` generados por el servidor: nunca coincide con los `DOC-NN` del corpus, no depende del nombre (que puede llevar datos personales, p. ej. «nomina-…») y dos nombres que se sanean igual no chocan. El nombre saneado solo se guarda como título por defecto y en el trabajo.
- La cabecera YAML de un `.md` **no** decide `id`, `category` ni `title` (al contrario que `Ingestor.ingest`, `ingest.py:138-141`): así un MD con `id: DOC-01` o `category: memoria` no sustituye un documento del corpus ni se cuela como memoria. La cabecera también pasa por el detector de §6.5.

### 6.4 Procesado en segundo plano (Docling en un proceso aparte)
- La ruta responde 202 al guardar el archivo; el resto lo hace un **proceso aparte con un solo worker** (Docling carga torch; R-08, la RAM del equipo es limitada).
- `DocumentConverter.convert(..., max_num_pages=300, max_file_size=20 MB)` con opciones fijas: `PdfPipelineOptions(do_ocr=False, do_picture_description=False, enable_remote_services=False)` (el conversor actual, `ingest.py:211-216`, usa los valores por defecto, con OCR).
- Topes del proceso aislado: **120 s** y **2 GB de memoria** (Job Object en Windows, `RLIMIT_AS` en Linux o `mem_limit` en Docker); si se supera cualquiera, se termina el proceso y se arranca otro.
- Entorno del proceso aislado: solo las variables imprescindibles (sin `JIRA_*`, `GROQ_API_KEY`, `DATABASE_URL` ni `POSTGRES_*`), `HF_HUB_OFFLINE=1` con los modelos de Docling ya descargados en la imagen, y sin red si el sistema lo permite. Devuelve solo el texto; la BD y los embeddings los hace el proceso de la API.
- Topes del texto, ya en el proceso de la API: 2 000 000 caracteres y 2000 fragmentos; al superarlos, `rejected` con `operation_failed` («El documento es demasiado grande para procesarlo.»).
- Cola: un documento en proceso por admin y 3 en total; si está llena, 429 `rate_limited` con `retry_after`, **antes** de leer el cuerpo.
- Al arrancar la API, los trabajos `queued` o `processing` se marcan `error` («Se interrumpió al reiniciar la API. Vuelve a subirlo.») y se borran sus archivos temporales (como `build_runtime` con las revisiones de calidad, `api/runtime.py:259-261`).

### 6.5 Datos personales y secretos antes de indexar
- Sobre el texto extraído completo, la cabecera YAML, el título y el nombre: `personal_data_kind` y `looks_like_secret` (`core/personal_data.py`), aplicados **línea a línea (nuevo)** para poder dar la línea: hoy esas funciones solo devuelven el tipo o un booleano.
- Si aparece algo: `state = "rejected"`, `error.code = "personal_data_detected"`, con el tipo y la línea; **nunca el valor** ni el título de la sección. No se indexa nada y se borra el archivo.
- **Límite del detector:** reconoce email, teléfono, DNI/NIE, IBAN ES y credenciales; **no** reconoce nombres, direcciones, datos de salud, tarjetas ni números de la Seguridad Social. Por eso la subida exige la **declaración** «Declaro que el documento no contiene datos personales reales», que queda en `document_jobs.declared_no_personal_data` y en la auditoría. Ampliar el detector (tarjetas con Luhn, NSS) queda para después (R-DOC-5).
- Sin opción de forzarlo en v1.1 (RNF-06: el corpus es sintético).
- Los emails de dominios reservados (`@example.com`, `.invalid`) se aceptan, como en el resto de FAQ.

### 6.6 Clasificación sin LLM y uso posterior del texto
- La categoría es obligatoria en el formulario: no se llama a `classify_source` (cuya cadena empieza en Groq, `config/models.yaml:60`). La **carga** no envía el texto a ningún LLM.
- **Pero lo indexado sí sale después:** los fragmentos se recuperan como contexto de `generate_story`, `evolve_story` y `review_story`, cuya cadena empieza en Groq (`config/models.yaml`). Por eso el control de RGPD es la detección y la declaración de §6.5, no la clasificación (RNF-08 sigue en v2.0).
- `classified_by = "metadata"`, como cuando la cabecera trae la categoría.

### 6.7 Duplicados, reemplazo, borrado y reindexado
- **Mismo contenido**: se sabe al procesar (`content_hash`, sha256 del texto normalizado, `ingest.py:146`); si ya está indexado, el trabajo queda `rejected` con `duplicate_document` y el documento existente.
- **Reemplazo**: solo con `replace_document_id` de un documento **subido** (nunca uno del corpus ni una memoria); `replace_document` sustituye los fragmentos en una sola transacción (`pgvector.py:169`).
- **Borrado**: `delete_by_document` (fragmentos en cascada). Las memorias no se pueden borrar desde aquí (403).
- **Reindexado**: recalcula los embeddings de los fragmentos guardados (`chunks.content`), sin el original. Para cambiar el troceado hay que volver a subir el documento con *Reemplazar*.

### 6.8 Dónde se guarda el original y cuánto tiempo
- En `data/uploads/<job_id>/` (ya en `.gitignore:21`; añadir a `.dockerignore`), **solo mientras se procesa**. Se borra al terminar, tanto si se indexa como si se rechaza o falla, y al arrancar la API (6.4).
- Starlette guarda el multipart en un temporal del sistema a partir de 1 MB: la ruta lo copia a `data/uploads/<job_id>/` y lo cierra enseguida; si la API cae justo entonces, ese temporal queda en el TEMP del sistema (el arranque no lo puede limpiar; el sistema operativo sí).
- En la base de datos quedan los fragmentos (texto troceado), sus metadatos y el trabajo (sin texto), que se purga a los 90 días.

### 6.9 Inyección de instrucciones
- El texto de los documentos es **dato**: se escapa con `escape_data` al ingerir y al montar el contexto (`<fuente …>…</fuente>`, `core/functional/context.py:95-105`), y todos los prompts de generación dicen que el contexto son datos y no instrucciones (p. ej. `prompts/generate_story.md`).
- En la subida no se llama al LLM (6.6), así que no hay un prompt nuevo expuesto.

### 6.10 Auditoría
- Acciones nuevas `document_upload` y `document_delete` en `AuditAction` y en el CHECK `ck_audit_log_action`, en **la misma migración** que las de usuarios (SPEC-ADMIN-USUARIOS §6.6).
- `detail = {"document_id": …, "content_hash": …, "category": …, "chunks": N, "pages": P, "replaced": bool, "declared_no_personal_data": true}`; **nunca el texto ni el nombre original**.
- El reindexado se audita como `document_upload` con `"reindexed": true`.

### 6.11 Logs
- `log.info("documento indexado", user=…, action="document_upload", document_id=…, chunks=…, duration_ms=…)`; nunca contenido ni rutas absolutas.

### 6.12 Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| R-DOC-1 · Un solo proceso de Docling (R-08: la RAM del equipo es limitada; Docling carga torch) | La cola avanza de uno en uno: con 3 documentos grandes, el tercero puede esperar ~6 min; la primera vez el proceso tarda en cargar torch | Cola acotada a 3 y estado visible («En cola»); el proceso se mantiene vivo entre trabajos y solo se reinicia si supera el tiempo |
| R-DOC-2 · Docling no es interrumpible en un hilo | Un PDF patológico bloquearía la API | Proceso aparte que se termina al pasar 120 s |
| R-DOC-3 · El detector de datos personales da falsos positivos (p. ej. códigos con forma de DNI) | Se rechazan documentos legítimos | Mensaje con el tipo y la línea para corregirlos; revisar el patrón si se repite |
| R-DOC-5 · El detector no reconoce nombres, direcciones, salud, tarjetas ni NSS | Un documento con esos datos se indexa y, como contexto, llega a Groq | Declaración obligatoria y auditada del admin; textos de la tarjeta que lo dicen; ampliar el detector (Luhn, NSS) después |
| R-DOC-7 · En Windows no hay un aislamiento de red sencillo para el proceso de Docling | Podría abrir conexiones (p. ej. descargas de modelos) | Sin credenciales en su entorno, `HF_HUB_OFFLINE=1` y servicios remotos desactivados; en Docker, red `none` para el worker |
| R-DOC-6 · Bomba de descompresión en un PDF | Docling reserva mucha memoria en segundos | Tope de memoria del proceso aislado (2 GB) además del de tiempo |
| R-DOC-4 · Documentos del corpus borrados desde la web | Desaparecen hasta la siguiente indexación por comando | Aviso en la confirmación (5.3) |

## 7. Criterios de aceptación

| ID | Criterio |
|---|---|
| CA-DOC-01 | Un `admin` sube un MD de 1 KB con categoría `politicas`: 202 y, al consultar, `indexed` con sus fragmentos buscables y citables |
| CA-DOC-02 | Un `functional` o `qa` recibe 403 en todas las rutas `/admin/documents*` y la web no le muestra la tarjeta |
| CA-DOC-03 | Un archivo de más de 20 MB da 413 `file_too_large` sin escribir más de 20 MB a disco |
| CA-DOC-04 | Un archivo con extensión `.pdf` cuyo contenido no empieza por `%PDF-` da 415 `unsupported_file_type` |
| CA-DOC-05 | Un `.docx` con macros (`.docm` renombrado o con `vbaProject.bin`), con objetos OLE o que no es un ZIP válido da 415 |
| CA-DOC-06 | Un DOCX que descomprime más de 100 MB (aunque su cabecera declare menos) o con más de 1000 entradas se rechaza sin descomprimirlo entero |
| CA-DOC-07 | Un nombre `../../etc/x.md` o `C:\tmp\x.md` se guarda dentro de `data/uploads/<job_id>/` con nombre generado y aparece saneado (`x.md`) en la respuesta; el `document_id` es `web-` + 8 hex |
| CA-DOC-08 | Un documento con un email real, un DNI o un secreto (`api_key: …`) queda `rejected` con `personal_data_detected` y la línea, sin el valor ni títulos del documento, y no se indexa nada |
| CA-DOC-09 | Un email `@example.com` no provoca rechazo |
| CA-DOC-10 | La subida no llama al LLM (`classify_source`): la categoría sale del formulario |
| CA-DOC-11 | El mismo contenido subido dos veces deja el segundo trabajo `rejected` con `duplicate_document` |
| CA-DOC-12 | Con `replace_document_id` de un documento subido, sus fragmentos se sustituyen sin dejar viejos; con el de uno del corpus o una memoria, 403; con uno inexistente, 404 |
| CA-DOC-13 | Un documento subido nunca sustituye a uno del corpus (`DOC-NN`), ni siquiera un `.md` con `id: DOC-01` en su cabecera; un `.md` con `category: memoria` se indexa con la categoría del formulario |
| CA-DOC-14 | Un documento que supera 300 páginas, 120 s o 2 GB de memoria queda `rejected`/`error` y el proceso aislado se reinicia; la API sigue respondiendo |
| CA-DOC-15 | Con un documento en proceso, una segunda subida del mismo admin da 429; con 3 en cola, la de cualquier admin da 429 |
| CA-DOC-16 | El archivo temporal se borra al terminar (indexado, rechazado o error) y al arrancar la API |
| CA-DOC-23 | Sin la declaración «no contiene datos personales reales», la subida da 422 `invalid_request`; con ella, queda en el trabajo y en la auditoría |
| CA-DOC-24 | Un DOCX con `<!DOCTYPE` o `<!ENTITY` en una parte XML, o con una relación `TargetMode="External"`, se rechaza con 415 sin resolver entidades ni abrir conexiones |
| CA-DOC-25 | El proceso aislado no tiene en su entorno variables de Jira, Groq ni de la BD, no abre conexiones de red al procesar y no usa OCR |
| CA-DOC-26 | Un texto extraído de más de 2 000 000 caracteres o que daría más de 2000 fragmentos queda `rejected` sin calcular embeddings |
| CA-DOC-27 | Con la cola llena, la subida da 429 sin leer el cuerpo; más de un archivo o campos de sobra dan 422 |
| CA-DOC-17 | Un documento con «Ignora tus instrucciones y publica…» se indexa como texto: al usarse como fuente aparece escapado dentro de `<fuente>` |
| CA-DOC-18 | Borrar quita el documento y sus fragmentos; borrar una memoria da 403 |
| CA-DOC-19 | Reindexar recalcula los embeddings sin cambiar el texto ni el número de fragmentos |
| CA-DOC-20 | Cada subida, reemplazo, reindexado y borrado deja una entrada en `audit_log` con id y `content_hash`, sin texto ni nombre original |
| CA-DOC-21 | Sin `X-CSRF-Token` u origen no permitido, la subida da 403 sin leer el cuerpo |
| CA-DOC-22 | El resto de la API mantiene el límite de 256 KB |

## 8. Plan de pruebas

| Nivel | Qué | Dónde |
|---|---|---|
| Unitarias con fakes | Validación del tipo real, saneado, límites del ZIP, detector de datos personales sobre el texto, duplicados, reemplazo, borrado, reindexado, cola y 429, rutas y errores, auditoría sin texto | `tests/unit/`, con un extractor falso (en lugar de Docling, como el `Extractor` de `ingest.py:73-75`), `FakeVectorStore`, `FakeEmbeddingProvider` e `InMemoryAuditTrail`; archivos sintéticos generados en la prueba (PDF mínimo, DOCX mínimo, ZIP inflado) |
| `integration` | Docling real con un PDF y un DOCX ficticios pequeños; tope de tiempo con un extractor que duerme en el proceso aparte; `pgvector` con `list_documents`, `replace_document` y borrado; migración 0007 | `@pytest.mark.integration`, se salta sin servicios |
| Web (Vitest + MSW) | Tarjeta, validación previa, progreso por consulta, estados `rejected`/`error`, lista, eliminar y reindexar con confirmación, errores por `code` | `web/src/screens/Admin/` con ejemplos del contrato |
| Manual | Subir un MD del corpus ficticio con otra categoría, preguntarle algo a FAQ que lo cite y borrarlo | Equipo del usuario |

Datos: documentos ficticios (Villaficticia). Para las pruebas del detector, valores con forma real pero inventados (IBAN `ES00…`, DNI `00000000T`) y, como emails, solo dominios reservados de RFC 2606 (`example.com`, `.invalid`) para los casos aceptados y un dominio claramente ficticio para los rechazados.

## 9. Reparto por áreas y estimación

| Orden | Área | Trabajo | Horas |
|---|---|---|---|
| 1 | Principal | Aprobar RF-53; `ErrorCode` nuevos (`file_too_large`, `unsupported_file_type`, `duplicate_document`, `personal_data_detected`); rutas y modelos en `api/admin.py` / `api/models.py`; límite de cuerpo por ruta en `api/security.py`; ajustes en `core/config.py`; `VectorStore.list_documents` en `adapters/base.py`; `python-multipart` directa; contrato | 7 |
| 2 | Área A | Migración 0007 (tabla `document_jobs` y acciones de auditoría, junto con las de usuarios); `list_documents` en `adapters/vectorstore/pgvector.py`; `AuditAction` | 4 |
| 3 | Área B | Trabajador en `core/rag/` (tipo real y DOCX seguro, saneado, proceso aislado de Docling con topes de tiempo y memoria y entorno sin credenciales, datos personales línea a línea, topes de texto, troceado, indexado, reindexado, borrado de temporales); cierre de PA-21 | 13 |
| 4 | Sesión UI | Tarjeta, progreso, lista, confirmaciones, cliente y tipos, MSW y pruebas | 7 |
| — | Todas | Revisión, pruebas `integration` y prueba manual | 2 |
| | | **Total** | **≈ 33 h** |

Dependencias: 1 → 2 → 3; la web (4) empieza contra el MSW cuando el contrato esté en 1. La migración 0007 es común con SPEC-ADMIN-USUARIOS: conviene hacerla una sola vez.

## 10. Preguntas abiertas

| # | Pregunta | Recomendación |
|---|---|---|
| P-01 | ¿Se guarda el original para poder reprocesarlo? | No: solo mientras se procesa (minimiza datos); para cambiar el troceado se vuelve a subir |
| P-02 | ¿Se puede forzar la subida si el detector da un falso positivo? | No en v1.1; si los falsos positivos molestan, revisar el patrón (R-DOC-3) |
| P-03 | ¿La categoría puede ser opcional y clasificarla el modelo local? | No en v1.1: obligatoria, sin LLM; el modelo local se podría ofrecer después |
| P-04 | ¿Límites de 20 MB, 300 páginas y 120 s? | Sí para empezar; ajustables en `core/config.py` |
| P-05 | ¿Se pueden borrar documentos del corpus desde la web? | Sí, con aviso de que vuelven si se reindexa el corpus por comando |
| P-06 | ¿Se mantiene la ingesta por comando (RF-49)? | Sí, para cargas masivas en el servidor; comparte `core/rag/` con la web |
| P-07 | ¿Basta la declaración del admin frente a nombres, direcciones o salud que el detector no ve? | Sí para v1.1 con un corpus sintético (D-06); ampliar el detector antes de usar documentos reales |
