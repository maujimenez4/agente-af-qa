---
id: DOC-03
title: Política de sanciones
category: politicas
version: 2
date: 2026-05-01
related: [DOC-01, DOC-02, DOC-07, DOC-10, DOC-20]
epics: [EP-AVISOS]
---

# Política de sanciones

Esta política define las consecuencias del incumplimiento de los reglamentos de préstamo (DOC-01) y de reservas (DOC-02) en la Biblioteca Municipal de Villaficticia. Las sanciones son exclusivamente suspensiones temporales de derechos; el servicio no aplica sanciones económicas, salvo la reposición de ejemplares perdidos.

## Control de versiones

| Versión | Fecha | Cambio |
|---|---|---|
| 1 | 2026-01-15 | Versión inicial |
| 2 | 2026-05-01 | Se añade RN-SAN-04 (reservas no recogidas), según el acta de la comisión del 15 de abril de 2026 (DOC-20) |

## Reglas de negocio

1. **RN-SAN-01.** Cada día de retraso en la devolución de un ejemplar genera **1 día de suspensión** del derecho de préstamo por cada ejemplar retrasado.
2. **RN-SAN-02.** La suspensión acumulada no puede superar los **60 días**.
3. **RN-SAN-03.** Durante una suspensión la persona socia no puede tomar nuevos préstamos, renovar ni reservar. Las reservas activas en el momento de la sanción se mantienen.
4. **RN-SAN-04.** Si una persona socia acumula **3 reservas no recogidas en 90 días**, no puede hacer nuevas reservas durante **15 días**. Sí puede tomar préstamos, en el mostrador o en autopréstamo, y renovar. Esta restricción de reservas no es una suspensión.
5. **RN-SAN-05.** La pérdida o el deterioro grave de un ejemplar obliga a reponerlo, o a entregar uno equivalente indicado por la biblioteca, en un plazo de 30 días. Hasta la reposición se aplica la suspensión de RN-SAN-03.
6. **RN-SAN-06.** Si un préstamo acumula más de 30 días de retraso, el carné queda bloqueado hasta la devolución del ejemplar, con independencia de la suspensión que corresponda después.
7. **RN-SAN-07.** La persona socia puede reclamar contra una sanción en un plazo de 10 días hábiles, por el procedimiento de DOC-07.

## Resumen de supuestos

| Supuesto | Consecuencia | Regla |
|---|---|---|
| Retraso de 4 días en 1 ejemplar | 4 días de suspensión | RN-SAN-01 |
| Retraso de 5 días en 3 ejemplares | 15 días de suspensión | RN-SAN-01 |
| Retraso de 40 días en 2 ejemplares | Bloqueo del carné hasta devolver y, después, 60 días de suspensión (máximo) | RN-SAN-02, RN-SAN-06 |
| Tercera reserva no recogida en 90 días | 15 días sin poder reservar | RN-SAN-04 |
| Ejemplar perdido | Reposición en 30 días y suspensión hasta reponer | RN-SAN-05 |

## Cálculo y aplicación

- La suspensión empieza a contar el día siguiente a la devolución del último ejemplar retrasado.
- Las devoluciones en buzón se consideran hechas en la fecha de depósito (artículo 6 de DOC-01).
- Los días de cierre de todas las sedes no cuentan como días de retraso.
- PrestaVF calcula la sanción de forma automática y AvisosVF la notifica a la persona socia (ver DOC-10).

## Cancelación de sanciones

El responsable de sala puede anular una sanción cuando se acredite un error del sistema o una causa de fuerza mayor. La anulación queda registrada en PrestaVF con el motivo.
