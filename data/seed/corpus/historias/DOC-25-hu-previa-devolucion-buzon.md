---
id: DOC-25
title: HU previa · Registrar las devoluciones del buzón exterior
category: historias
version: 2
date: 2025-11-20
related: [DOC-01, DOC-07, DOC-03]
epics: [EP-PRESTAMO]
---

# HU previa · Registrar las devoluciones del buzón exterior

Historia de usuario del proyecto anterior de modernización del préstamo (referencia interna HU-ANT-07), ya implantada. Se conserva como antecedente para nuevas HU de devolución.

## Historia

**Como** personal de sala, **quiero** registrar en bloque los ejemplares recogidos del buzón exterior **para** que la devolución conste con la fecha en que se depositaron y no con la del registro.

## Criterios de aceptación

- **CA-01 · Fecha de devolución.** Dado un ejemplar recogido del buzón el día siguiente a su depósito, cuando se registra, entonces la devolución consta con la fecha de depósito (DOC-07).
- **CA-02 · Sin retraso por la recogida.** Dado un préstamo que vencía el día del depósito, cuando se registra al día siguiente, entonces no se genera suspensión por retraso (RN-SAN-01).
- **CA-03 · Ejemplar con reserva.** Dado un ejemplar devuelto con reservas pendientes, cuando se registra, entonces se asigna a la primera reserva de la cola (RN-RES-04).

## Reglas de negocio

- **RN-01.** Los ejemplares pueden devolverse en cualquier sede o en los buzones exteriores (DOC-01, artículo 6).
- **RN-02.** El retraso se calcula por día y ejemplar (RN-SAN-01, DOC-03).

## Decisiones

- Las devoluciones del buzón se registran el siguiente día de apertura (DOC-07). Se descartó registrar la hora exacta del depósito: los buzones no tienen lector.

## Estado

Implantada en la versión 4 de PrestaVF. Sin incidencias abiertas.

## Notas para nuevas HU

- Cualquier HU nueva sobre devoluciones debe mantener la fecha de depósito como fecha de devolución; cambiarla afectaría al cálculo de suspensiones (DOC-03) y a las reclamaciones por sanción indebida (DOC-07).
- La asignación del ejemplar a la cola de reservas se hace en el mismo registro, sin un paso adicional del personal de sala.
- Los casos de prueba de esta HU se ejecutaron en preproducción con datos sintéticos y quedaron como regresión del módulo de devoluciones.
