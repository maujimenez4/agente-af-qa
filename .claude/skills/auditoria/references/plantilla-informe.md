# Auditoría del proyecto · AAAA-MM-DD

- **Rama y commit:** `PreProduccion` @ `abc1234`
- **Alcance:** repositorio completo (o: `core/rag`, `api`)
- **Capas:** 1 (automática) + dimensiones: principios, corrección, seguridad, llm-rag, pruebas, frontend
- **Ejecutada por:** sesión <nombre> · rango de propuestas PA-XXX…PA-YYY

## Resumen

| Gravedad | Capa 1 | Capa 2 | Total |
|---|---|---|---|
| Alta | 0 | 1 | 1 |
| Media | 4 | 2 | 6 |
| Baja | 0 | 3 | 3 |

Refutados en la segunda pasada: 2 (no figuran abajo).

Lo más importante, en tres frases como mucho: qué hallazgo alto hay y qué riesgo cubre.

## Capa 1 · Comprobaciones automáticas

Recuento por regla (`uv run python .claude/skills/auditoria/checks.py`):

| Regla | Gravedad | Hallazgos |
|---|---|---|
| jira-write | alta | 0 |
| core-concrete-import | alta | 0 |
| silent-except | media | 4 |
| … | … | … |

| Gravedad | Regla | Archivo:línea | Problema | Por qué importa | Corrección propuesta |
|---|---|---|---|---|---|
| media | silent-except | `api/service.py:738` | `except Exception` devuelve `[]` sin registrar | Un fallo de la auditoría se ve como «sin fallos» | Registrar `error_type` con `log.warning` |

## Capa 2 · Seguridad

| Gravedad | Archivo:línea | Problema | Por qué importa | Corrección propuesta | Veredicto |
|---|---|---|---|---|---|
| alta | `core/context/service.py:120` | El texto de Jira entra en el prompt sin delimitar | Inyección de órdenes al modelo | Envolver en `<documento>` y neutralizar los delimitadores | confirmado |

(Una sección por dimensión lanzada; «Sin hallazgos» si no queda ninguno tras la refutación.)

## Propuestas para el Kanban

Altas y medias, con el siguiente número libre del rango de quien ejecuta. **Pendiente de confirmación:** no se añaden al Kanban ni se corrige nada sin el visto bueno.

| PA | Gravedad | Propuesta | Origen |
|---|---|---|---|
| PA-XXX | alta | … | Auditoría AAAA-MM-DD · seguridad |
