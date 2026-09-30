# Corpus piloto sintético · Biblioteca Municipal de Villaficticia

Corpus base del RAG del MVP (D-06, T-09). Describe el servicio digital de una biblioteca municipal **ficticia**: préstamo, reservas, renovaciones, personas socias, catálogo, sanciones y notificaciones. Todos los nombres de lugares, sistemas y dominios son inventados; no contiene datos personales.

Este índice lo usa T-15 para sembrar Jira de forma coherente con el corpus.

## Estructura

- Ruta de cada documento: `data/seed/corpus/<categoría>/<id>-<titulo-corto>.md`.
- Cabecera YAML con `id`, `title`, `category`, `version`, `date`, `related` y `epics`.
- La categoría `memoria` está reservada para las memorias que genera el agente y no se usa aquí.

## Reglas clave del dominio

No deben contradecirse. El dataset de los fakes de prueba (T-06) y el seed de Jira (T-15) deben usar estos mismos valores:

| Regla | Valor vigente | Fuente |
|---|---|---|
| Reservas activas por persona socia | Máximo 3 | DOC-02, RN-RES-02 |
| Bloqueo de un ejemplar reservado | 48 horas | DOC-02, RN-RES-05 (desde DOC-19) |
| Duración del préstamo | 21 días | DOC-01, artículo 4 |
| Renovaciones por préstamo | 2 | DOC-01, artículo 5 |
| Renovación con reservas pendientes | No permitida | DOC-01, artículo 5; DOC-02, RN-RES-08 (ratificada en DOC-20) |
| Ejemplares simultáneos | Máximo 8, de ellos 3 audiovisuales | DOC-01, artículo 3 |
| Suspensión por retraso | 1 día por día y ejemplar, máximo 60 | DOC-03, RN-SAN-01 y RN-SAN-02 |
| Reservas no recogidas | 3 en 90 días suponen 15 días sin reservar | DOC-03, RN-SAN-04 (desde DOC-20) |
| Historial de préstamos | Opcional, 12 meses | DOC-04 (desde DOC-21) |
| Recordatorio de vencimiento | 3 días antes | DOC-10, AV-02 (desde DOC-21) |

## Documentos

| Id | Título | Categoría | Temas |
|---|---|---|---|
| DOC-01 | Reglamento de préstamo | normativa | EP-PRESTAMO |
| DOC-02 | Reglamento de reservas | normativa | EP-PRESTAMO |
| DOC-03 | Política de sanciones | normativa | EP-AVISOS |
| DOC-04 | Política de protección de datos de personas socias | normativa | EP-SOCIOS, EP-PRESTAMO |
| DOC-05 | Alta y renovación del carné de persona socia | procesos | EP-SOCIOS |
| DOC-06 | Circuito de reserva y recogida | procesos | EP-PRESTAMO, EP-AVISOS |
| DOC-07 | Devolución, retrasos y reclamaciones | procesos | EP-PRESTAMO, EP-AVISOS |
| DOC-08 | Especificación del módulo de préstamo digital | especificaciones | EP-PRESTAMO |
| DOC-09 | Especificación del catálogo en línea | especificaciones | EP-CATALOGO |
| DOC-10 | Especificación del módulo de notificaciones | especificaciones | EP-AVISOS |
| DOC-11 | Glosario del servicio bibliotecario | glosario | EP-PRESTAMO, EP-SOCIOS, EP-CATALOGO, EP-AVISOS |
| DOC-12 | Siglas y códigos de estado | glosario | EP-PRESTAMO, EP-CATALOGO |
| DOC-13 | Mapa de sistemas del servicio digital | arquitectura | EP-PRESTAMO, EP-SOCIOS, EP-CATALOGO, EP-AVISOS |
| DOC-14 | API interna de préstamo y reservas | arquitectura | EP-PRESTAMO |
| DOC-15 | Integración con la pasarela AvisosVF | arquitectura | EP-AVISOS |
| DOC-16 | Guía del portal para personas socias | manuales | EP-PRESTAMO, EP-SOCIOS, EP-CATALOGO |
| DOC-17 | Manual de mostrador para personal de sala | manuales | EP-PRESTAMO, EP-SOCIOS |
| DOC-18 | Guía de autopréstamo | manuales | EP-PRESTAMO |
| DOC-19 | Acta de la Comisión de Servicios Bibliotecarios de febrero de 2026 | actas | EP-PRESTAMO |
| DOC-20 | Acta de la Comisión de Servicios Bibliotecarios de abril de 2026 | actas | EP-PRESTAMO, EP-AVISOS |
| DOC-21 | Acta de la Comisión de Servicios Bibliotecarios de junio de 2026 | actas | EP-PRESTAMO, EP-AVISOS |
| DOC-22 | Acta técnica del servicio digital de julio de 2026 | actas | EP-AVISOS |

Documentos por categoría: normativa 4 · procesos 3 · especificaciones 3 · glosario 2 · arquitectura 3 · manuales 3 · actas 4 (22 en total).

## Temas de épica para el seed de Jira (T-15)

Cada épica lista sus ideas de HU y los documentos que las sustentan. Las claves `DEMO-N` son las que deberán usar el dataset de los fakes de prueba (T-06) y el seed del sandbox (T-15).

### EP-PRESTAMO · Préstamo digital (`DEMO-1`)

Gestión de préstamos y reservas desde PortalVF y AppVF. Fuentes: DOC-01, DOC-02, DOC-06, DOC-08, DOC-14.

1. **Reservar un ejemplar** (`DEMO-2`): como persona socia, quiero reservar un título y elegir la sede de recogida para asegurarme de conseguirlo. Reglas: máximo 3 reservas activas y bloqueo de 48 horas.
2. **Renovar un préstamo** (`DEMO-3`): como persona socia, quiero renovar un préstamo desde el portal para no tener que ir a la biblioteca. Reglas: 21 días, 2 renovaciones, sin renovación con reservas pendientes.
3. **Consultar el historial de préstamos** (`DEMO-4`): como persona socia, quiero consultar los préstamos que ya he devuelto para recordar qué he leído. Reglas: historial opcional de 12 meses (DOC-04).
4. **Ver los préstamos activos y sus vencimientos**: como persona socia, quiero ver qué tengo en préstamo y cuándo vence cada ejemplar para devolverlo a tiempo.

### EP-SOCIOS · Gestión de personas socias

Alta, renovación y baja del carné, y preferencias. Fuentes: DOC-04, DOC-05, DOC-16, DOC-17.

1. **Solicitar el carné en línea**: como vecino o vecina, quiero pedir el carné desde el portal y validarlo en una sede en 10 días.
2. **Renovar el carné**: como persona socia, quiero renovar mi carné antes de que caduque para no perder el acceso al préstamo.
3. **Configurar las preferencias de aviso**: como persona socia, quiero elegir los canales y los avisos opcionales que recibo.
4. **Solicitar la baja y la supresión de datos**: como persona socia, quiero darme de baja y que se borren mis datos en los plazos de la política.

### EP-CATALOGO · Catálogo en línea

Búsqueda y consulta de títulos y disponibilidad. Fuentes: DOC-09, DOC-12, DOC-13.

1. **Búsqueda avanzada**: como visitante, quiero combinar criterios (autoría, materia, tipo, año) para encontrar un título concreto.
2. **Disponibilidad por sede**: como persona socia, quiero filtrar los títulos disponibles en mi sede para llevármelos hoy.
3. **Ficha del título con su cola de reservas**: como persona socia, quiero ver cuántas reservas tiene un título antes de reservarlo.

### EP-AVISOS · Notificaciones y sanciones

Avisos a las personas socias y gestión de sanciones. Fuentes: DOC-03, DOC-07, DOC-10, DOC-15, DOC-22.

1. **Recordatorio de vencimiento**: como persona socia, quiero recibir un aviso 3 días antes del vencimiento para renovar o devolver a tiempo.
2. **Aviso de reserva disponible**: como persona socia, quiero que se me avise cuando mi reserva esté lista, con la fecha y hora límite de recogida.
3. **Aviso y consulta de sanciones**: como persona socia, quiero saber qué sanción tengo, hasta cuándo y cómo reclamar.
4. **Reintentos de avisos no entregados**: como responsable del servicio digital, quiero que los avisos fallidos se reintenten y queden registrados para poder resolver reclamaciones.
