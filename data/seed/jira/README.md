# Seed de Jira · Biblioteca Municipal de Villaficticia (T-15)

`seed-villaficticia.csv` siembra el proyecto de pruebas de Jira Cloud con **4 épicas y 13 HU sintéticas** del servicio digital de una biblioteca ficticia (D-06). Todos los datos son inventados: no hay personas, organizaciones ni productos reales, y los sistemas (CatálogoVF, AvisosVF) no existen.

> **La importación la hace una persona desde el navegador.** El agente y el código del repositorio no escriben en Jira salvo el nodo `publish`, con aprobación humana (principio 1 de `CLAUDE.md`). El CSV no lleva subtareas de caso de prueba: las genera y publica el agente (D-09).

## Contenido

| Issue ID | Tipo | Resumen | Calidad (a propósito) | Relates |
|---|---|---|---|---|
| 1 | Epic | Préstamo digital de libros | — | |
| 2 | Story | [HU-01] Reservar un libro disponible | Completa | |
| 3 | Story | [HU-02] Renovar un préstamo | Completa | 2 |
| 4 | Story | [HU-03] Consultar el historial de préstamos | Incompleta: sin CA, RN ni alcance | |
| 5 | Story | [HU-04] Cancelar una reserva | Ambigua: «en cualquier momento», «avisar a alguien», no dice qué pasa con el cupo de reservas | 2 |
| 6 | Epic | Alta y gestión de personas socias | — | |
| 7 | Story | [HU-05] Alta de persona socia en línea | Completa | |
| 8 | Story | [HU-06] Renovar el carné de persona socia | Ambigua: caducidad «periódica» y «documentación necesaria» sin definir; «renovar» también se usa para los préstamos | |
| 9 | Story | [HU-07] Actualizar mis datos de contacto | Incompleta: solo el enunciado | |
| 10 | Epic | Catálogo en línea CatálogoVF | — | |
| 11 | Story | [HU-08] Buscar libros en el catálogo | Completa | |
| 12 | Story | [HU-09] Ver la disponibilidad de ejemplares | Completa | 2 |
| 13 | Story | [HU-10] Recomendaciones de lectura | Ambigua: «buenas», «rápido», «mis gustos»; uso del historial sin tratar la privacidad | |
| 14 | Epic | Sanciones y avisos AvisosVF | — | |
| 15 | Story | [HU-11] Aviso de vencimiento del préstamo | Completa | 3 |
| 16 | Story | [HU-12] Suspensión por devolución tardía | Completa | 3 |
| 17 | Story | [HU-13] Aviso de reserva lista para recoger | Incompleta: no indica el plazo de recogida (48 h) ni el canal | 2 |

- La calidad **no** se marca en Jira (ni etiquetas ni texto), para no dar pistas al agente en la revisión (RF-18).
- **Impacto (RF-19):** HU-01 y HU-02 son los nodos centrales. Un cambio en la regla de 48 h afecta a HU-01 y HU-09, que la citan, y a HU-04 y HU-13, que solo la heredan por su vínculo con HU-01 (el agente debe deducirlo de los vínculos); un cambio en las renovaciones, a HU-02, HU-11 y HU-12.
- **Equivalencia con los fakes:** las filas 1 a 4 equivalen a `DEMO-1` a `DEMO-4` de `tests/fakes/dataset.py`. Si se importa en un proyecto vacío con clave `DEMO`, lo normal es que reciban esas claves, pero Jira no garantiza el orden de creación: compruébalo tras importar. El estado y los comentarios de los fakes (DEMO-1 «En curso», DEMO-2 «Hecho» con un comentario) no se importan: todo se crea en el estado inicial.
- **Reglas del dominio** (coinciden con los fakes y con el corpus): máximo 3 reservas activas; una reserva bloquea el ejemplar 48 horas; un préstamo dura 21 días y admite 2 renovaciones si no hay reservas pendientes. Las reglas añadidas (aviso tres días antes del vencimiento, un día de suspensión por día de retraso, edad mínima de 14 años) deben alinearse con el corpus de T-09 si este fija otros valores.

## Columnas del CSV

UTF-8, separado por comas, cabecera en la primera fila; los campos con saltos de línea van entre comillas dobles.

| Columna | Campo de Jira | Notas |
|---|---|---|
| `Issue ID` | Issue ID | Número que solo relaciona filas dentro del CSV; Jira asigna la clave real |
| `Parent` | Parent | `Issue ID` de la épica; vacío en las épicas |
| `Issue Type` | Issue Type | `Epic` / `Story` (hay que mapearlo, ver abajo) |
| `Summary` | Summary | Las HU llevan el prefijo `[HU-XX]` (R-05) |
| `Description` | Description | Formato wiki de Jira (`h2.`, `*negrita*`, listas `*`, `{code}`); el importador la convierte a ADF |
| `Priority` | Priority | `High` / `Medium` / `Low` (hay que mapearlo) |
| `Labels` (×2) | Labels | La primera siempre es `seed-villaficticia`; la segunda, el tema de la épica (`prestamo-digital`, `socios`, `catalogo`, `sanciones-avisos`) |
| `Link "Relates"` | Link: Relates | `Issue ID` de la incidencia relacionada; vacío si no hay vínculo |

## Pasos de importación en Jira Cloud

1. Entra en el proyecto de pruebas (T-08) con una cuenta que pueda crear incidencias y comprueba que el esquema del proyecto tiene los tipos **Épica** e **Historia**.
2. Abre el importador CSV completo: **⚙ Configuración → Sistema → Importación y exportación → Importación externa del sistema → CSV** (en inglés: *Settings → System → External System Import → CSV*). Los nombres de los menús cambian con las versiones de Jira Cloud; si no los encuentras, busca «CSV» en la configuración del sistema. Hay un importador simplificado sin permisos de administración (**Filtros → Ver todas las incidencias → ⋯ → Importar incidencias desde CSV**), pero puede no ofrecer `Parent` ni los vínculos: si lo usas, revisa la jerarquía y crea los vínculos a mano.
3. Sube `seed-villaficticia.csv`. En **Ajustes avanzados**, fija la codificación en **UTF-8** y el separador en **coma** (`,`).
4. Elige el proyecto de destino.
5. **Asigna las columnas** a campos de Jira según la tabla anterior (`Parent` puede aparecer como «Parent» o «Parent id»; las dos columnas `Labels` se asignan al mismo campo). Marca «Asignar valores de campo» (*Map field value*) en `Issue Type` y `Priority`.
6. **Asigna los valores** (siguiente apartado) y pulsa **Validar**. Revisa el aviso del validador: debe proponer 17 incidencias (4 épicas y 13 historias).
7. Pulsa **Empezar importación** y guarda el archivo de configuración que ofrece el asistente, por si hay que repetirla.
8. Comprueba el resultado con la JQL `labels = seed-villaficticia ORDER BY key` (17 incidencias), que cada historia cuelga de su épica y que existen los 6 vínculos «relates to».

### Valores que hay que mapear

| Columna | Valor en el CSV | Valor en un espacio en español (ejemplo) |
|---|---|---|
| `Issue Type` | `Epic` | `Épica` |
| `Issue Type` | `Story` | `Historia` |
| `Priority` | `High` | `Alta` (Must en MoSCoW) |
| `Priority` | `Medium` | `Media` (Should) |
| `Priority` | `Low` | `Baja` (Could) |

Usa los nombres que tenga tu esquema: el asistente muestra los disponibles en un desplegable. El estado no viene en el CSV, así que todas las incidencias se crean en el estado inicial del flujo («Por hacer»).

## Vínculos «relates to» a mano

Si el importador de tu espacio no ofrece el campo **Link: Relates** o la validación lo descarta, deja la columna sin asignar, importa y crea los vínculos a mano. Para cada fila de esta tabla, abre la incidencia de origen → **Vincular incidencia** (*Link issue*) → tipo **relates to** → busca la de destino por su resumen:

| Origen | Destino |
|---|---|
| [HU-02] Renovar un préstamo | [HU-01] Reservar un libro disponible |
| [HU-04] Cancelar una reserva | [HU-01] Reservar un libro disponible |
| [HU-09] Ver la disponibilidad de ejemplares | [HU-01] Reservar un libro disponible |
| [HU-13] Aviso de reserva lista para recoger | [HU-01] Reservar un libro disponible |
| [HU-11] Aviso de vencimiento del préstamo | [HU-02] Renovar un préstamo |
| [HU-12] Suspensión por devolución tardía | [HU-02] Renovar un préstamo |

«relates to» es simétrico: basta con crearlo en un sentido.

## Deshacer la importación

Busca `labels = seed-villaficticia`, selecciona todo en **Cambio masivo** (*Bulk change*) y elimina las incidencias. No afecta a nada que no lleve la etiqueta.
