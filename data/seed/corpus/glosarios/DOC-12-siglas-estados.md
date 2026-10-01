---
id: DOC-12
title: Siglas y códigos de estado
category: glosarios
version: 2
date: 2026-07-20
related: [DOC-02, DOC-03, DOC-05, DOC-07, DOC-08, DOC-09, DOC-10, DOC-11, DOC-13, DOC-14]
epics: [EP-PRESTAMO, EP-CATALOGO]
---

# Siglas y códigos de estado

Referencia de las siglas usadas en la documentación del servicio digital y de los códigos de estado que manejan los sistemas. Los términos generales están en el Glosario (DOC-11).

## Siglas

| Sigla | Significado |
|---|---|
| AV | Aviso (catálogo de avisos de DOC-10) |
| CA | Criterio de aceptación |
| HU | Historia de usuario |
| REC | Reclamación (número de registro, DOC-07) |
| RN | Regla de negocio |
| RN-RES | Regla de negocio de reservas (DOC-02) |
| RN-SAN | Regla de negocio de sanciones (DOC-03) |
| RF-PD | Requisito funcional del módulo de préstamo digital (DOC-08) |
| RF-CAT | Requisito funcional del catálogo en línea (DOC-09) |
| SOC | Prefijo del número de persona socia (DOC-05) |
| VF | Villaficticia; sufijo de los sistemas del servicio digital |

## Sistemas

| Nombre | Función |
|---|---|
| CatálogoVF | Registros bibliográficos y ejemplares |
| PrestaVF | Préstamos, reservas y sanciones |
| SociosVF | Fichas y carnés de las personas socias |
| AvisosVF | Pasarela de avisos |
| PortalVF | Portal web para personas socias |
| AppVF | Aplicación móvil para personas socias |

La relación entre sistemas se describe en DOC-13.

## Estados del ejemplar

| Código | Estado | Descripción |
|---|---|---|
| EJ-DIS | Disponible | En estantería y prestable |
| EJ-PRE | Prestado | En préstamo a una persona socia |
| EJ-TRA | En traslado | Enviándose a otra sede para una reserva |
| EJ-BLQ | Bloqueado por reserva | En la estantería de reservas durante 48 horas |
| EJ-NOP | No prestable | Obra de referencia o ejemplar retirado |
| EJ-REP | En reparación | Retirado temporalmente por deterioro |
| EJ-PER | Perdido | Pendiente de reposición |

## Estados de la reserva

| Código | Estado | ¿Activa? | Transiciones posibles |
|---|---|---|---|
| RS-PEN | Pendiente | Sí | RS-DIS, RS-CAN |
| RS-DIS | Disponible para recoger | Sí | RS-REC, RS-CAD, RS-CAN |
| RS-REC | Recogida | No | — |
| RS-CAD | Caducada | No | — |
| RS-CAN | Cancelada | No | — |

Solo cuentan para el máximo de 3 reservas activas (RN-RES-02) las reservas en RS-PEN y RS-DIS.

## Estados del préstamo

| Código | Estado | Descripción |
|---|---|---|
| PR-ACT | Activo | Dentro de plazo |
| PR-REN | Renovado | Activo tras una o dos renovaciones |
| PR-VEN | Vencido | Pasada la fecha de vencimiento sin devolución |
| PR-DEV | Devuelto | Cerrado con la devolución |
| PR-PER | Declarado perdido | Cerrado con obligación de reposición |

## Estados del carné

| Código | Estado |
|---|---|
| CN-PVA | Pendiente de validación (alta en línea) |
| CN-VIG | Vigente |
| CN-SUS | Con suspensión activa |
| CN-BLQ | Bloqueado por retraso superior a 30 días (RN-SAN-06) |
| CN-CAD | Caducado |
| CN-BAJ | Baja |

## Uso de los códigos

Los códigos se usan en la API interna (DOC-14) y en los registros de PrestaVF. En las pantallas de PortalVF y AppVF se muestra siempre el nombre del estado, nunca el código.
