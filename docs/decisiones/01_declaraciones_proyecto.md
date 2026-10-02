# Declaraciones del Proyecto
## Proyecto 1 · Agente de IA especializado en Análisis Funcional y QA

| Campo | Valor |
|---|---|
| Versión del documento | 0.4 |
| Estado | Borrador vivo (se actualiza con cada decisión) |
| Horizonte | 10 días de MVP + 5 días de v1.1 y colchón (15 días) |
| Equipo | Una persona orquestando sesiones de Claude Code |
| Entorno | Jira Cloud con proyecto de pruebas propio · Datos 100 % sintéticos |

---

## 1. Visión

Construir un **Producto Mínimo Funcional** de un agente de IA que apoye el Análisis Funcional y el QA. El agente se conecta con Jira, se especializa progresivamente mediante una base de conocimiento RAG y trabaja con distintos modelos de IA. Opera siempre bajo el principio **"la IA propone, el usuario valida y Jira conserva solo resultados aprobados"**.

## 2. Objetivos

| ID | Objetivo |
|---|---|
| OBJ-01 | Generar, revisar y mejorar Historias de Usuario completas a partir del contexto de Jira y del RAG |
| OBJ-02 | Generar artefactos de QA trazables a los criterios de aceptación y a las reglas de negocio |
| OBJ-03 | Publicar en Jira únicamente artefactos aprobados por una persona |
| OBJ-04 | Construir una memoria evolutiva del proyecto en Markdown que reduzca el consumo de tokens |
| OBJ-05 | Operar con varios proveedores de LLM sin depender de uno solo |

## 3. Alcance

### 3.1 Incluido en el MVP (v1.0, días 1–10)
- Conexión con Jira Cloud (lectura y escritura).
- Selección de épica, HU o necesidad nueva, y recuperación del contexto relacionado.
- Pipeline RAG completo (cargar, procesar, fragmentar y vectorizar) sobre un **corpus piloto sintético**.
- Generación de HU nuevas y de evolución de HU existentes, con versionado, diff y análisis de impacto.
- Generación de casos de prueba, escenarios Gherkin, matriz de cobertura, estrategia, datos sintéticos y riesgos.
- Flujo de revisión, iteración, aprobación y publicación con auditoría.
- Publicación de los artefactos de QA en **Jira nativo**: subtareas de prueba, adjuntos y vínculos.
- Memoria sintética .md de las HU publicadas, reincorporada al RAG con prioridad en la búsqueda.
- Modelos **open-weight gratuitos** (D-14): generación en Groq, respaldo en OpenRouter y embeddings y tareas ligeras en Ollama local, con cadena de respaldo ante límites o fallos.
- Autenticación simple con usuarios locales y tres tipos de usuario.

### 3.2 v1.1 (días 11–15)
- Registro de ejecución de pruebas (sujeto a R-01), métricas en Langfuse, lenguaje natural a JQL, ingesta automática, gestión de documentos y evaluación ampliada.

### 3.3 Fuera del alcance (v2.0 o posterior)
- Memoria .md de los artefactos de QA (la arquitectura queda preparada).
- Plugin de gestión de pruebas (Xray, Zephyr): posible mediante el adaptador `TestManagement`.
- Integración con un proveedor de identidad corporativo (SSO).
- Anonimización automática de datos personales.
- Aprobador distinto del autor.
- Multiproyecto o multidominio aislado en el RAG.

---

## 4. Actores y roles

| Tipo | Actor | Responsabilidad |
|---|---|---|
| Humano | **Analista Funcional** | Selecciona la épica, HU o necesidad, itera con el agente, aprueba y publica la HU |
| Humano | **Analista QA** | Selecciona una HU, genera los artefactos de prueba, los revisa, aprueba y publica |
| Humano | **Administrador** | Configura Jira y los proveedores y modelos de IA; gestiona usuarios; realiza la carga de conocimiento |
| Sistema | **Agente IA** | Recupera contexto, genera propuestas, publica tras la aprobación y genera la memoria |
| Externo | **Jira Cloud** | Fuente de épicas, HU y tareas; destino de las HU y los artefactos de QA aprobados |
| Interno | **Base de conocimiento RAG** | Corpus documental y memorias vectorizadas |
| Externo | **Proveedores LLM** | Groq y OpenRouter (nube, nivel gratuito) y Ollama (local); cualquier otro compatible con la API de OpenAI |

> Cada usuario completa **todo** el flujo de principio a fin; no hay traspaso entre usuarios dentro de un mismo flujo (D-01).

---

## 5. Principios no negociables

1. **Validación humana**: ninguna escritura en Jira sin confirmación explícita.
2. **Trazabilidad**: todo artefacto se vincula a su origen (épica, HU, CA, RN, CP).
3. **Seguridad**: los secretos nunca aparecen en el código, los logs ni los ejemplos. Se usan placeholders (`TU_API_KEY`).
4. **Privacidad (RGPD)**: solo datos sintéticos en desarrollo y demo.
5. **Eficiencia**: salidas estructuradas y memorias sintéticas para minimizar tokens.

---

## 6. Flujo principal

1. El usuario selecciona una épica, una HU o una necesidad.
2. El agente consulta Jira y recupera la información relacionada.
3. El agente complementa el contexto mediante RAG.
4. El agente genera la propuesta.
5. El usuario revisa, conversa e itera.
6. El usuario confirma antes de publicar.
7. El agente registra o actualiza la información en Jira.
8. El agente genera la memoria .md y la reincorpora al RAG (en el MVP, solo para las HU).

### 6.1 Mecanismos de selección desde Jira

| Mecanismo | Descripción | Versión |
|---|---|---|
| Por clave o URL | El usuario indica `CLAVE-123` o pega el enlace; el agente recupera la incidencia y sus relaciones | v1.0 |
| Navegación | Panel Proyecto → Épica → HU con listas obtenidas mediante JQL | v1.0 |
| Búsqueda simple | Texto libre que se traduce a `text ~ "..."` en JQL | v1.0 |
| Necesidad nueva | Texto libre; el agente busca HU relacionadas para detectar modificaciones | v1.0 |
| Lenguaje natural a JQL | El LLM genera la JQL (solo lectura, validada antes de ejecutarse) | v1.1 |

### 6.2 Modelo de publicación de artefactos de QA en Jira (D-09)

| Artefacto | Representación en Jira |
|---|---|
| Caso de prueba (CP) | **Subtarea** de la HU, con la etiqueta `caso-prueba` y etiquetas de trazabilidad (`CA-01`, `RN-02`, `tipo-positivo`). La descripción, en ADF, incluye tipo, precondiciones, una tabla de pasos, datos y resultado esperado. |
| Escenario Gherkin | Bloque de código Gherkin dentro de la descripción de la subtarea |
| Estrategia de pruebas | **Adjunto** `estrategia-<CLAVE>.md` en la HU |
| Matriz de cobertura | **Adjunto** `matriz-<CLAVE>.md` en la HU (CA/RN → CP); también se calcula en la aplicación |
| Impacto sobre otras HU | **Vínculo** "relates to" hacia las HU afectadas, con un comentario que explica el impacto |
| Ejecución (v1.1, R-01) | Por decidir: transiciones de estado de la subtarea (Pasó, Falló, Bloqueado) y un comentario con la evidencia |

---

## 7. Registro de decisiones

| ID | Decisión | Estado |
|---|---|---|
| D-01 | Hay tres tipos de usuario (Analista Funcional, QA y Administrador). Cada usuario completa el flujo completo sin cambiar de usuario. | ✅ Aprobada |
| D-02 | No hay rol de "Gestor de conocimiento": el Administrador realiza la carga base y el aprendizaje continuo se produce mediante la memoria .md | ✅ Aprobada |
| D-03 | Se usa Jira Cloud con un proyecto de pruebas propio | ✅ Aprobada |
| D-04 | La interfaz es un chat sencillo con vista previa para las aprobaciones, hecho en Streamlit (sin frontend separado) | 🔁 Revisada el 2026-10-02: frontend propio en React (`web/`, T-56) sobre una API FastAPI (`api/`, T-55) para que se vea como el lienzo «Propuesta mixta»; Streamlit queda como plan B hasta el punto de control T-57 |
| D-05 | La autenticación es simple (usuarios locales) en el MVP; SSO en versiones posteriores | ✅ Aprobada |
| D-06 | El RAG base del MVP es un corpus sintético de un dominio ficticio | ✅ Aprobada |
| D-07 | No se genera memoria .md para artefactos de QA en el MVP, pero la arquitectura lo permite | ✅ Aprobada |
| D-08 | ~~Publicación de QA mediante Xray (opción B)~~ **Sustituida por D-09** | ❌ Revocada |
| D-09 | Los artefactos de QA se publican en **Jira nativo**: subtareas, adjuntos y vínculos (opción A, ver §6.2) | ✅ Aprobada |
| D-10 | El desarrollo lo realiza una sola persona orquestando sesiones de Claude Code (principal + 2 worktrees) | ✅ Aprobada |
| D-11 | Plan de 10 días de MVP con integración temprana (primera HU real el día 4, demo de los pasos 1–5 el día 5) + 5 días de v1.1 | ✅ Aprobada |
| D-12 | La maqueta de UI existente se descarta; la UI se rediseña dentro del proyecto (ver T-17) | ✅ Aprobada |
| D-13 | Stack confirmado: LangGraph, SDK de OpenAI (proveedores compatibles), PostgreSQL + pgvector, Docling, Streamlit (ver investigación) | ✅ Aprobada |
| D-14 | El MVP usa solo **modelos open-weight gratuitos**: generación en Groq (gpt-oss-120b), respaldo en OpenRouter (modelos `:free`), embeddings (bge-m3) y tareas ligeras en Ollama local. Sin Claude, OpenAI de pago ni suscripciones (cierra R-07). | ✅ Aprobada |

## 8. Puntos en revisión

| ID | Tema | Contexto | Afecta a |
|---|---|---|---|
| R-01 | Alcance del soporte a la ejecución de pruebas | **Cerrada el 2026-10-01: opción A** (registrar resultado y evidencia; RF-28 al MVP). Consulta enviada a dirección. Opciones: A) registrar resultados, B) asistencia guiada + defectos, C) ejecución automatizada. Con subtareas, la ejecución se modelaría con estados y comentarios. | RF-28, RF-29 |
| R-05 | Mapeo entre convenciones internas (HU-XX, CP-XX) y claves de Jira | Provisionalmente: prefijo en el título `[HU-XX]` / `[CP-XX]` | RF-04, RF-06, RF-30 |
| R-08 | RAM del equipo (gráficos Intel integrados) | Determina el tamaño del modelo local para tareas ligeras; los embeddings funcionan en CPU en cualquier caso | RF-10, RNF-07 |

---

## 9. Épicas

| ID | Épica | Objetivo |
|---|---|---|
| EP-01 | Integración con Jira | Leer contexto y publicar artefactos aprobados |
| EP-02 | Base de conocimiento RAG | Ingesta, indexación y recuperación del conocimiento |
| EP-03 | Análisis Funcional | Generar, evolucionar y revisar HU con impacto y diff |
| EP-04 | Artefactos de QA | Generar y publicar artefactos de prueba |
| EP-05 | Validación y publicación | Garantizar la aprobación humana y la auditoría |
| EP-06 | Memoria sintética | Conservar conocimiento validado de forma eficiente |
| EP-07 | Gestión de modelos de IA | Operar con varios proveedores configurables |
| EP-08 | Usuarios y administración | Controlar el acceso y la configuración |

---

## 10. Requisitos funcionales

Leyenda: ✅ aprobado · 🔍 en revisión · ⏸ aplazado · **(PA)** Propuesta adicional. Los IDs retirados no se reutilizan (RF-48).

| ID | Requisito | Épica | Versión | Prioridad | Estado |
|---|---|---|---|---|---|
| RF-01 | Configurar y validar la conexión con Jira Cloud (URL del sitio, usuario y token con scopes almacenado de forma segura) | EP-01 | v1.0 | Must | ✅ |
| RF-02 | Buscar y listar proyectos, épicas, HU y tareas mediante filtros o JQL | EP-01 | v1.0 | Must | ✅ |
| RF-03 | Recuperar el detalle de una incidencia (descripción convertida de ADF a texto) y sus relaciones: épica padre, subtareas, enlaces y comentarios | EP-01 | v1.0 | Must | ✅ |
| RF-04 | Crear incidencias en Jira solo tras la aprobación del usuario | EP-01 | v1.0 | Must | ✅ |
| RF-05 | Actualizar incidencias existentes conservando la versión anterior y publicando un comentario con el diff | EP-01 | v1.0 | Must | ✅ |
| RF-06 | Crear vínculos entre incidencias (épica↔HU, HU↔HU afectadas) | EP-01 | v1.0 | Must | ✅ |
| RF-07 | Cargar documentos PDF, DOCX, MD y TXT a la base de conocimiento | EP-02 | v1.0 | Must | ✅ |
| RF-08 | Extraer y normalizar el texto de los documentos | EP-02 | v1.0 | Must | ✅ |
| RF-09 | Fragmentar con tamaño y solapamiento configurables, conservando metadatos | EP-02 | v1.0 | Must | ✅ |
| RF-10 | Vectorizar y almacenar con metadatos (fuente, categoría, fecha, ID relacionado) | EP-02 | v1.0 | Must | ✅ |
| RF-11 | Recuperar los fragmentos relevantes con filtros, indicando su fuente | EP-02 | v1.0 | Must | ✅ |
| RF-12 | Clasificar cada fuente en una de las 7 categorías definidas | EP-02 | v1.0 | Should | ✅ |
| RF-13 | Listar, eliminar y reindexar documentos | EP-02 | v1.1 | Should | ✅ |
| RF-14 | Iniciar el flujo desde una épica, una HU (por clave, navegación o búsqueda) o una necesidad en texto libre | EP-03 | v1.0 | Must | ✅ |
| RF-15 | Generar una propuesta de HU nueva con la plantilla completa del proyecto | EP-03 | v1.0 | Must | ✅ |
| RF-16 | Generar criterios de aceptación en Gherkin con IDs (CA-XX) | EP-03 | v1.0 | Must | ✅ |
| RF-17 | Identificar y documentar las reglas de negocio con IDs (RN-XX) | EP-03 | v1.0 | Must | ✅ |
| RF-18 | Revisar una HU existente y proponer mejoras (ambigüedades, huecos, INVEST) | EP-03 | v1.0 | Should | ✅ |
| RF-19 | Generar la evolución de una HU existente, calcular el diff y analizar el impacto (HU afectadas, reglas, dependencias y regresión) | EP-03 | v1.0 | Must | ✅ |
| RF-20 | Iterar conversacionalmente sin perder el contexto | EP-03 | v1.0 | Must | ✅ |
| RF-21 | Mostrar las fuentes de Jira y del RAG (citas) utilizadas en cada propuesta | EP-03 | v1.0 | Should | ✅ |
| RF-22 | Generar casos y escenarios de prueba (positivos, negativos, alternos y de excepción) | EP-04 | v1.0 | Must | ✅ |
| RF-23 | Incluir en cada caso: ID, CA y RN vinculados, tipo, precondiciones, pasos, datos, resultado esperado y prioridad | EP-04 | v1.0 | Must | ✅ |
| RF-24 | Generar la matriz de cobertura CA/RN ↔ CP | EP-04 | v1.0 | Must | ✅ |
| RF-25 | Generar datos sintéticos coherentes con las reglas de negocio | EP-04 | v1.0 | Should | ✅ |
| RF-26 | Generar la estrategia de pruebas de una HU o épica | EP-04 | v1.0 | Should | ✅ |
| RF-27 | Identificar riesgos, dependencias y áreas de impacto | EP-04 | v1.0 | Should | ✅ |
| RF-28 | Registrar resultados de ejecución por caso de prueba (estado y evidencia) | EP-04 | v1.0 | Should | ⬜ R-01 (A) |
| RF-29 | Proponer un defecto vinculado ante un caso fallido **(PA)** | EP-04 | v2.0 | Could | ⏸ R-01 (A) |
| RF-30 | Publicar los artefactos de QA aprobados en Jira: CP como subtareas, estrategia y matriz como adjuntos (§6.2) | EP-04 | v1.0 | Must | ✅ |
| RF-31 | Mostrar una vista previa del artefacto y de los cambios tal como quedarán en Jira | EP-05 | v1.0 | Must | ✅ |
| RF-32 | Permitir la edición manual antes de aprobar | EP-05 | v1.0 | Should | ✅ |
| RF-33 | Exigir confirmación explícita antes de cualquier escritura | EP-05 | v1.0 | Must | ✅ |
| RF-34 | Gestionar los estados del artefacto: borrador, en revisión, aprobado, publicado y descartado | EP-05 | v1.0 | Must | ✅ |
| RF-35 | Registrar la auditoría de cada acción: usuario, fecha, versión, modelo y claves de Jira | EP-05 | v1.0 | Must | ✅ |
| RF-36 | Generar la memoria .md de cada HU publicada (objetivo, alcance, RN, decisiones, dependencias, cambios, CA y referencias) | EP-06 | v1.0 | Must | ✅ |
| RF-37 | Reincorporar la memoria al RAG con metadatos vinculados a la clave de Jira | EP-06 | v1.0 | Must | ✅ |
| RF-38 | Actualizar la memoria en lugar de duplicarla cuando la HU cambia (reindexado) | EP-06 | v1.0 | Should | ✅ |
| RF-39 | Generar memoria .md de los artefactos de QA | EP-06 | v2.0 | Could | ⏸ D-07 |
| RF-40 | Configurar proveedores de LLM compatibles con la API de OpenAI (Groq, OpenRouter, Ollama y otros) | EP-07 | v1.0 | Must | ✅ |
| RF-41 | Asignar un modelo a cada tipo de tarea | EP-07 | v1.0 | Should | ✅ |
| RF-42 | Cambiar de modelo sin modificar el código, incluido desde un selector en la UI | EP-07 | v1.0 | Must | ✅ |
| RF-43 | Registrar el consumo de tokens y el coste por llamada | EP-07 | v1.0 | Should | ✅ |
| RF-44 | Usar el siguiente proveedor de una cadena de respaldo configurable cuando el principal falle o alcance su límite de uso | EP-07 | v1.0 | Should | ✅ |
| RF-45 | Autenticar usuarios locales (contraseña con hash) | EP-08 | v1.0 | Must | ✅ |
| RF-46 | Gestionar los tipos de usuario y sus permisos | EP-08 | v1.0 | Should | ✅ |
| RF-47 | Consultar el historial de sesiones y artefactos del usuario | EP-08 | v1.1 | Could | ✅ |
| RF-49 | Ingerir automáticamente los documentos depositados en una carpeta configurada | EP-02 | v1.1 | Should | ✅ |
| RF-50 | Traducir búsquedas en lenguaje natural a JQL de solo lectura | EP-01 | v1.1 | Could | ✅ |
| RF-51 | Priorizar las memorias validadas frente a la documentación base en la recuperación | EP-06 | v1.0 | Should | ✅ |

---

## 11. Requisitos no funcionales (ISO/IEC 25010)

| ID | Categoría | Requisito | Versión | Prioridad |
|---|---|---|---|---|
| RNF-01 | Seguridad | Los secretos (token de Jira, API keys de LLM, contraseñas) se almacenan fuera del código y nunca se versionan | v1.0 | Must |
| RNF-02 | Seguridad | Los secretos nunca aparecen en logs, trazas ni respuestas | v1.0 | Must |
| RNF-03 | Seguridad | Todas las comunicaciones externas usan HTTPS/TLS | v1.0 | Must |
| RNF-04 | Seguridad | El token de Jira tiene scopes mínimos y fecha de caducidad | v1.0 | Should |
| RNF-05 | Seguridad | El acceso a las funciones se controla según el tipo de usuario | v1.0 | Should |
| RNF-06 | Cumplimiento normativo | Solo se usan datos sintéticos en desarrollo y demo (RGPD) | v1.0 | Must |
| RNF-07 | Cumplimiento normativo | Existe la opción de un modelo local (Ollama) para que la información no salga del entorno | v1.0 | Should |
| RNF-08 | Cumplimiento normativo | Se anonimizan los datos personales antes de enviarlos a un LLM externo **(PA)** | v2.0 | Could |
| RNF-09 | Eficiencia de desempeño | La recuperación del RAG tarda ≤ 3 s (por validar) | v1.0 | Should |
| RNF-10 | Eficiencia de desempeño | La generación de una HU completa tarda ≤ 60 s con un modelo en la nube (por validar) | v1.0 | Should |
| RNF-11 | Eficiencia de desempeño | La memoria .md reduce los tokens en ≥ 60 % frente al artefacto original (por validar el día 9) | v1.0 | Should |
| RNF-12 | Fiabilidad | Los errores externos se gestionan con reintentos y mensajes claros, sin perder el trabajo del usuario | v1.0 | Must |
| RNF-13 | Fiabilidad | Una publicación fallida no deja artefactos incompletos en Jira sin informar; se registra qué se creó y se permite reintentar | v1.0 | Should |
| RNF-14 | Adecuación funcional | El agente no inventa referencias y cita siempre la fuente | v1.0 | Must |
| RNF-15 | Usabilidad | La interfaz y los artefactos están en español | v1.0 | Must |
| RNF-16 | Usabilidad | Se muestran visualmente las diferencias entre versiones de una HU | v1.0 | Should |
| RNF-17 | Mantenibilidad | La arquitectura es modular, con adaptadores intercambiables (Jira, gestión de pruebas, LLM, embeddings, base vectorial, autenticación) | v1.0 | Must |
| RNF-18 | Mantenibilidad | Los prompts se externalizan y versionan | v1.0 | Should |
| RNF-19 | Mantenibilidad | Los componentes críticos tienen pruebas automatizadas | v1.0 | Should |
| RNF-20 | Portabilidad | La solución se despliega con contenedores (Docker Compose) | v1.0 | Should |
| RNF-21 | Compatibilidad | Es compatible con la API REST v3 de Jira Cloud | v1.0 | Must |
| RNF-22 | Escalabilidad | El RAG soporta varios proyectos o dominios aislados | v2.0 | Could |
| RNF-23 | Observabilidad | Se registran logs estructurados de cada operación | v1.0 | Should |
| RNF-24 | Observabilidad | Existen métricas de tokens, latencia y coste por modelo y tarea en un panel | v1.1 | Should |
| RNF-25 | Mantenibilidad | El generador de memoria es agnóstico al tipo de artefacto | v1.0 | Should |
| RNF-26 | Seguridad | Las dependencias se fijan con lockfile y hashes para mitigar ataques a la cadena de suministro | v1.0 | Must |
| RNF-27 | Fiabilidad | El sistema respeta los límites de los niveles gratuitos: backoff ante 429, presupuesto de tokens por petición y consumo diario visible | v1.0 | Must |
| RNF-28 | Adecuación funcional | Toda salida estructurada del LLM se valida con Pydantic; si no es válida se reintenta una vez y, si vuelve a fallar, se informa al usuario | v1.0 | Must |

---

## 12. Plan de versiones

| Versión | Días | Contenido |
|---|---|---|
| v1.0 MVP | 1–10 | Flujo completo para HU (nueva y evolución) y artefactos de QA en Jira nativo, RAG con memoria, multi-LLM, aprobación y auditoría |
| v1.1 | 11–14 | Ejecución (según R-01), Langfuse, NL→JQL, ingesta automática, gestión de documentos, evaluación ampliada |
| Demo final | 15 | Ensayo, documentación y roadmap |
| v2.0 | Posterior | Memoria de QA, plugin de pruebas, SSO, anonimización, multiproyecto, aprobador distinto del autor |

---

## 13. Glosario

| Término | Definición |
|---|---|
| HU | Historia de Usuario |
| CA | Criterio de aceptación (formato Gherkin) |
| CP | Caso de prueba (en Jira, subtarea con la etiqueta `caso-prueba`) |
| RN | Regla de negocio |
| ADF | Atlassian Document Format: formato de las descripciones y comentarios en la API v3 de Jira |
| RAG | Retrieval-Augmented Generation: recuperación de contexto documental para el LLM |
| Memoria sintética | Resumen estructurado en .md de un resultado validado, reincorporado al RAG |
| Corpus piloto | Documentación sintética inicial de un dominio ficticio |
| JQL | Jira Query Language |

---

## 14. Registro de cambios

| Versión | Cambio |
|---|---|
| 0.1 | Requisitos iniciales, roles y épicas |
| 0.2 | D-01 a D-08; cierre de R-02, R-03 y R-04; RF-48 a RF-50; RNF-25 y RNF-26; mecanismos de selección |
| 0.4 | D-14 (modelos open-weight gratuitos); se cierra R-07; RF-40 y RF-44 actualizados (RF-44 pasa al MVP); se añaden RNF-27 y RNF-28 |
| 0.3 | D-08 revocada y sustituida por D-09 (Jira nativo); D-10 a D-13; se elimina Xray; RF-48 y R-06 retirados; se añaden RF-51, R-07 y R-08; RF-03, RF-05, RF-19, RF-26, RF-30 y RF-43 ampliados o adelantados; plan de 10 + 5 días |
