# Agente de IA de Análisis Funcional y QA

MVP de un agente que genera y evoluciona Historias de Usuario y artefactos de QA desde Jira Cloud y una base de conocimiento RAG, con aprobación humana antes de publicar en Jira.

## Contenido
| Archivo | Para qué sirve |
|---|---|
| `CLAUDE.md` | Contexto, principios, áreas y convenciones que leen todas las sesiones de Claude Code |
| `docs/specs/SPEC-00-fundacional.md` | Contratos: esquemas, interfaces, grafo, base de datos y configuración |
| `docs/KANBAN.md` | 46 tareas en 10 + 5 días, con sincronización diaria |
| `docs/decisiones/` | Declaraciones del proyecto (v0.3) e investigación tecnológica (v0.2) |
| `docs/prompts/` | Prompts para arrancar cada sesión de Claude Code |
| `.claude/agents/` | Subagentes `test-writer`, `security-reviewer` y `spec-checker` |
| `config/models.yaml` | Asignación de modelos por tarea (sin secretos) |
| `.env.example` | Plantilla de variables de entorno (solo placeholders) |

## Cómo trabajar (una persona, tres sesiones)

**Día 1 · Sesión principal**
```bash
git init && git add . && git commit -m "T-00: paquete de arranque"
cp .env.example .env        # rellénalo tú; nunca se versiona
claude                      # en main → pega docs/prompts/PROMPT-01-dia1.md
```
Mientras Claude construye la base, haz tú la T-08 (Jira, token y claves de LLM).

**Días 2–9 · Dos worktrees en paralelo**
```bash
claude --worktree area-a    # Integraciones y núcleo
claude --worktree area-b    # Conocimiento y UI
```
En cada worktree nuevo, ejecuta `uv sync` antes de nada. Al final de cada día: fusiona en `main` con las pruebas en verde, verifica el hito de sincronización del Kanban y haz rebase de los worktrees.

**Día 10 · Prueba cruzada y v1.0.** **Días 11–15 · v1.1 y demo final.**

## Principios
La IA propone, el usuario valida y Jira conserva solo resultados aprobados. Sin secretos en el código. Solo datos sintéticos.
