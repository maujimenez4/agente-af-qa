---
id: DOC-27
title: Estrategia de pruebas del módulo de préstamo digital
category: pruebas
version: 1
date: 2026-07-28
related: [DOC-01, DOC-08, DOC-14]
epics: [EP-PRESTAMO]
---

# Estrategia de pruebas del módulo de préstamo digital

Estrategia de referencia para probar el préstamo, la renovación y la reserva en PortalVF y AppVF. Se aplica a cada entrega del módulo de préstamo digital (DOC-08).

## Alcance

- **Dentro:** consulta de préstamos activos, renovación, reserva y cancelación de reserva en PortalVF y AppVF, y la API interna de préstamo y reservas (DOC-14).
- **Fuera:** el autopréstamo en sede, la gestión de sanciones y el préstamo interbibliotecario.

## Niveles

| Nivel | Qué se prueba | Responsable |
|---|---|---|
| Funcional | Cada criterio de aceptación de las HU de la entrega | QA |
| Integración | Llamadas de PortalVF y AppVF a la API de préstamo y reservas | QA y desarrollo |
| Regresión | Reglas de renovación y reservas ya implantadas | QA |
| Aceptación | Recorridos completos con personal de sala | Responsable del servicio |

## Entornos y datos

- **Entorno:** preproducción, con PrestaVF y SociosVF de pruebas.
- **Datos:** solo sintéticos. Personas socias `SOC-0001` a `SOC-0050`, préstamos `PR-500` en adelante. Nunca datos de personas reales.

## Criterios

- **Entrada:** HU aprobadas y entorno de preproducción disponible.
- **Salida:** todos los casos de prioridad alta pasan y no hay defectos abiertos de prioridad alta.

## Riesgos conocidos

1. Que la app no aplique el máximo de 2 renovaciones (DOC-01, artículo 5).
2. Que se permita renovar con reservas pendientes (RN-RES-08).
3. Diferencias de horario entre sedes en el cálculo del vencimiento.

## Matriz de cobertura

Cada criterio de aceptación tiene al menos un caso; la matriz CA/RN × CP se adjunta a la HU. Ver un ejemplo en DOC-28.

## Priorización

1. Primero, los casos de las reglas con más impacto en la persona socia: máximo de renovaciones, renovación con reservas pendientes y bloqueo de 48 horas de una reserva (DOC-02).
2. Después, los casos alternos y de excepción de cada HU.
3. Por último, la regresión de las HU implantadas que comparten reglas con la entrega.
