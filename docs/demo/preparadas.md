# Conversaciones preparadas para la demo

**Pendiente:** todavía no se ha ejecutado la preparación contra el modelo local. Este archivo lo genera y sobrescribe `uv run python -m eval.demo_prepare --real` (ver `docs/demo/GUION.md`, «Preparación»), con una fila por conversación: nombre, usuario, id, estado, estado esperado, modelo y segundos.

Para ver su forma sin red ni LLM: `uv run python -m eval.demo_prepare --fake` (escribe en una carpeta temporal).
