---
id: DOC-28
title: Casos de prueba de reservas
category: pruebas
version: 1
date: 2026-07-30
related: [DOC-02, DOC-06, DOC-27]
epics: [EP-PRESTAMO]
---

# Casos de prueba de reservas

Suite de regresión de las reservas en PortalVF y AppVF, según la estrategia DOC-27. Los datos son sintéticos.

## Casos

| CP | Título | Tipo | Prioridad | Verifica |
|---|---|---|---|---|
| CP-01 | Reservar con menos de 3 reservas activas | Positivo | Alta | RN-RES-02 |
| CP-02 | Rechazo de la cuarta reserva activa | Negativo | Alta | RN-RES-02 |
| CP-03 | Bloqueo de 48 horas al quedar disponible | Positivo | Alta | RN-RES-05 |
| CP-04 | Caducidad tras 48 horas sin recogida | Excepción | Media | RN-RES-06 |
| CP-05 | Cancelar una reserva sin penalización | Alterno | Media | RN-RES-07 |
| CP-06 | Rechazo al reservar un título que ya se tiene en préstamo | Negativo | Media | RN-RES-09 |

## Escenarios

```gherkin
Escenario: CP-02 · Rechazo de la cuarta reserva activa
  Dado que la persona socia SOC-0002 tiene 3 reservas activas
  Cuando reserva un título más
  Entonces la reserva se rechaza
  Y se muestra el motivo «Has alcanzado el máximo de 3 reservas activas»

Escenario: CP-04 · Caducidad tras 48 horas sin recogida
  Dado que la reserva de SOC-0003 está «disponible para recoger» desde hace 48 horas
  Cuando PrestaVF revisa las reservas
  Entonces la reserva pasa a «caducada»
  Y el ejemplar se asigna a la siguiente reserva de la cola
```

## Datos

| Persona socia | Reservas activas | Situación |
|---|---|---|
| SOC-0001 | 1 | Sin sanción |
| SOC-0002 | 3 | Sin sanción |
| SOC-0003 | 1 | Reserva disponible desde hace 48 horas |

## Matriz de cobertura

| Regla | CP |
|---|---|
| RN-RES-02 | CP-01, CP-02 |
| RN-RES-05 | CP-03 |
| RN-RES-06 | CP-04 |
| RN-RES-07 | CP-05 |
| RN-RES-09 | CP-06 |
