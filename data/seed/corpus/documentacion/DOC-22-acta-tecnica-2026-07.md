---
id: DOC-22
title: Acta técnica del servicio digital de julio de 2026
category: documentacion
version: 1
date: 2026-07-08
related: [DOC-07, DOC-10, DOC-13, DOC-15, DOC-21]
epics: [EP-AVISOS]
---

# Acta técnica del servicio digital de julio de 2026

## Datos de la reunión

- **Fecha:** 8 de julio de 2026
- **Lugar:** reunión en línea
- **Asistentes (por rol):** responsable del servicio digital, equipo técnico de PrestaVF, equipo técnico de AvisosVF, equipo técnico de SociosVF y un responsable de sala en representación de las sedes.

## Orden del día

1. Incidencias de entrega de avisos en el primer semestre.
2. Política de reintentos de AvisosVF.
3. Canal por defecto y mensajes de texto (acuerdo A-2606-4 del acta DOC-21).
4. Preparación del recordatorio de vencimiento.

## Desarrollo

### 1. Incidencias de entrega

El equipo de AvisosVF informa de que el 3 % de los avisos no se entregaron al primer intento, casi siempre por saturación temporal del servidor de correo. Actualmente AvisosVF hace un único reintento inmediato, que suele fallar por la misma causa. Dos reclamaciones de reservas caducadas se estimaron porque el aviso de disponibilidad no llegó a entregarse (ver criterios de DOC-07).

### 2. Política de reintentos

Se propone una política escalonada:

- hasta 3 reintentos, con esperas de 5, 15 y 60 minutos;
- envío por un segundo canal, si la persona socia lo tiene activo, tras el segundo fallo;
- marcar el aviso como «no entregado» y alertar al equipo técnico tras el tercer reintento fallido;
- no reintentar los errores permanentes, y marcar el canal como «a revisar».

El responsable de sala pregunta si el retraso de los reintentos afecta al plazo de 48 horas de recogida. Se aclara que el plazo empieza con la disponibilidad del ejemplar y no con la entrega del aviso; con la política propuesta, el peor caso de entrega es de 80 minutos, que se considera aceptable.

### 3. Canal por defecto y mensajes de texto

- Se fija el **correo electrónico** como canal por defecto para las personas socias sin preferencias configuradas.
- Se decide **no usar mensajes de texto** al móvil por su coste y porque la notificación de AppVF cubre la necesidad de inmediatez.

### 4. Recordatorio de vencimiento

El recordatorio de 3 días antes del vencimiento aprobado en DOC-21 generará un pico diario a las 9:00. Se acuerda enviarlo en lotes de 500 avisos por minuto.

## Acuerdos

| Nº | Acuerdo | Responsable | Plazo |
|---|---|---|---|
| AT-2607-1 | Implantar la política de reintentos (3 reintentos: 5, 15 y 60 minutos) | Equipo de AvisosVF | 15 de julio de 2026 |
| AT-2607-2 | Correo electrónico como canal por defecto | Equipo de SociosVF | 15 de julio de 2026 |
| AT-2607-3 | No usar mensajes de texto al móvil | Servicio digital | Inmediato |
| AT-2607-4 | Envío del recordatorio AV-02 en lotes de 500 por minuto | Equipo de AvisosVF | Con el módulo |
| AT-2607-5 | Actualizar DOC-10 y DOC-15 a la versión 2 | Servicio digital | 15 de julio de 2026 |

## Seguimiento

Revisión de los indicadores de entrega en la reunión técnica de octubre de 2026.
