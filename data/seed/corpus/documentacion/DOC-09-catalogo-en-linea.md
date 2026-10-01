---
id: DOC-09
title: Especificación del catálogo en línea
category: documentacion
version: 1
date: 2026-04-28
related: [DOC-02, DOC-08, DOC-10, DOC-13, DOC-14]
epics: [EP-CATALOGO]
---

# Especificación del catálogo en línea

Especificación funcional de la búsqueda y la consulta del catálogo en PortalVF y AppVF. Los datos bibliográficos y de ejemplares proceden de CatálogoVF (DOC-13).

## Objetivo

Que cualquier persona, sea o no socia, pueda encontrar un título, saber en qué sedes está disponible y, si es socia, reservarlo.

## Actores

- **Visitante:** consulta el catálogo sin iniciar sesión.
- **Persona socia:** además, puede reservar y guardar búsquedas.
- **CatálogoVF:** fuente de los registros bibliográficos y del estado de los ejemplares.

## Requisitos funcionales

### RF-CAT-01. Búsqueda simple

1. Un único campo de búsqueda por título, autoría, materia o código del ejemplar.
2. Los resultados se ordenan por relevancia y pueden ordenarse por fecha de publicación o por título.
3. Se muestran 20 resultados por página.
4. Si no hay resultados, se sugieren búsquedas parecidas y la búsqueda sin filtros.

### RF-CAT-02. Búsqueda avanzada

Permite combinar estos criterios:

| Criterio | Tipo | Ejemplo |
|---|---|---|
| Título | Texto | «El faro de Villaficticia» |
| Autoría | Texto | «Brumaverde» |
| Materia | Lista controlada | Novela histórica |
| Tipo de material | Lista | Libro, audiovisual, revista, libro electrónico |
| Sede | Lista | Sede Central, Sede Norte, Sede del Río |
| Año de publicación | Rango | 2015–2026 |
| Colección | Lista | General, infantil y juvenil, referencia |
| Solo disponibles | Casilla | Sí |

### RF-CAT-03. Ficha del título

1. Datos bibliográficos: título, autoría, edición, materia, resumen y portada, si existe.
2. Tabla de ejemplares por sede, con su estado (disponible, prestado, en traslado, reservado, no prestable) y, si está prestado, la fecha de vencimiento.
3. Número de reservas pendientes del título (cola de reservas), sin datos de las personas que reservan.
4. Botón «Reservar» si la persona socia ha iniciado sesión y el título es prestable. Las obras de referencia muestran «Solo consulta en sala» (RN-RES-09).
5. Si la persona socia ya tiene el título en préstamo o reservado, el botón se sustituye por el estado correspondiente.

### RF-CAT-04. Disponibilidad por sede

1. El filtro «Solo disponibles» muestra los títulos con al menos un ejemplar disponible en la sede elegida.
2. La disponibilidad se actualiza en menos de 5 minutos tras un préstamo o una devolución.
3. Un ejemplar «disponible para recoger» por una reserva cuenta como no disponible.

### RF-CAT-05. Novedades

1. Sección con los títulos incorporados en los últimos 30 días, filtrable por sede y tipo de material.
2. Se actualiza cada noche a partir de CatálogoVF.

### RF-CAT-06. Búsquedas guardadas

1. La persona socia puede guardar hasta 10 búsquedas.
2. Puede activar un aviso cuando aparezcan títulos nuevos que cumplan una búsqueda guardada (ver DOC-10). Esta función queda para una fase posterior.

## Requisitos no funcionales

- La búsqueda simple responde en menos de 1 segundo en el 95 % de los casos.
- La búsqueda ignora mayúsculas, tildes y artículos iniciales.
- El catálogo es accesible sin iniciar sesión y no registra búsquedas asociadas a personas socias.

## Integración

La consulta usa los servicios de lectura de CatálogoVF. La reserva usa la API interna de préstamo y reservas (DOC-14), con las reglas de DOC-02.

## Fuera de alcance

- Recomendaciones personalizadas basadas en el historial.
- Reseñas y valoraciones de las personas socias.
