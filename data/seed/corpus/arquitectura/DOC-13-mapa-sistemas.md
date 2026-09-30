---
id: DOC-13
title: Mapa de sistemas del servicio digital
category: arquitectura
version: 2
date: 2026-07-20
related: [DOC-01, DOC-02, DOC-03, DOC-12, DOC-14, DOC-15, DOC-18, DOC-22]
epics: [EP-PRESTAMO, EP-SOCIOS, EP-CATALOGO, EP-AVISOS]
---

# Mapa de sistemas del servicio digital

Visión general de los sistemas que forman el servicio digital de la Biblioteca Municipal de Villaficticia, sus responsabilidades y cómo se comunican. Todos los nombres de sistemas y dominios son ficticios.

## Principios de arquitectura

1. **Un sistema, una responsabilidad.** Cada dato tiene un único sistema propietario.
2. **Integración por API interna.** Los canales (PortalVF, AppVF, autopréstamo) nunca acceden directamente a las bases de datos de los sistemas de negocio.
3. **Eventos para los avisos.** Los sistemas de negocio publican eventos y AvisosVF los transforma en avisos.
4. **Reglas en un solo lugar.** Las reglas de préstamo, reservas y sanciones (DOC-01, DOC-02, DOC-03) se aplican solo en PrestaVF. Los canales muestran los mensajes que devuelve la API.

## Sistemas

### CatálogoVF

- **Responsabilidad:** registros bibliográficos, ejemplares, sedes y estado físico de cada ejemplar.
- **Datos propios:** títulos, ejemplares, ubicaciones.
- **Expone:** servicios de búsqueda y de consulta de fichas y disponibilidad.

### PrestaVF

- **Responsabilidad:** préstamos, renovaciones, reservas, colas y sanciones.
- **Datos propios:** préstamos activos, historial (si está activo), reservas, sanciones.
- **Expone:** la API interna de préstamo y reservas (DOC-14).
- **Publica eventos:** reserva disponible, reserva caducada, préstamo próximo a vencer, préstamo vencido, sanción aplicada.

### SociosVF

- **Responsabilidad:** fichas de personas socias, carnés, preferencias de aviso y autenticación de los canales.
- **Datos propios:** identificación, contacto, estado del carné, preferencias.
- **Expone:** servicio de consulta de ficha y de validación del carné; emite las sesiones de PortalVF y AppVF.

### AvisosVF

- **Responsabilidad:** pasarela de avisos. Recibe eventos, aplica las preferencias de la persona socia, compone el mensaje y lo envía por el canal adecuado.
- **Datos propios:** plantillas de avisos y registro de envíos (6 meses).
- **Integración:** ver DOC-15.

### PortalVF y AppVF

- **Responsabilidad:** canales de autoservicio para las personas socias y para visitantes (solo catálogo).
- **Datos propios:** ninguno de negocio; solo la sesión.

### Puntos de autopréstamo

Terminales en cada sede que usan la API interna con una identidad de servicio propia por terminal (DOC-18).

## Flujo de ejemplo: renovar un préstamo

1. La persona socia pulsa «Renovar» en AppVF.
2. AppVF llama a la API interna de PrestaVF con la sesión emitida por SociosVF.
3. PrestaVF comprueba el estado del carné en SociosVF.
4. PrestaVF aplica el artículo 5 de DOC-01: máximo de 2 renovaciones, sin reservas pendientes, sin suspensión activa y sin vencimiento.
5. Si se permite, calcula la nueva fecha (vencimiento vigente más 21 días) y responde a AppVF.
6. Si no, responde con el código de error correspondiente (DOC-14) y AppVF muestra el mensaje.

## Entornos

| Entorno | Dominio base | Datos |
|---|---|---|
| Desarrollo | `dev.villaficticia.invalid` | Sintéticos |
| Pruebas | `test.villaficticia.invalid` | Sintéticos |
| Producción | `villaficticia.invalid` | Reales (ficticios en este corpus) |

## Riesgos conocidos

- **Dependencia de SociosVF:** si no responde, no se pueden hacer préstamos ni reservas. Mitigación: los puntos de autopréstamo guardan en caché la validación del carné durante 15 minutos.
- **Retraso en la disponibilidad:** CatálogoVF se sincroniza con PrestaVF cada pocos minutos, así que el catálogo puede mostrar durante un breve tiempo un ejemplar ya prestado.
- **Saturación de AvisosVF:** el envío de recordatorios de vencimiento de las 9:00 genera picos; se reparte en lotes de 500 avisos por minuto (DOC-15, acuerdo AT-2607-4 de DOC-22).
