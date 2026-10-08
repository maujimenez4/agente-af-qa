# Configuración de modelos

El agente elige el modelo de cada tarea a partir de un archivo YAML de esta carpeta. Cada tarea es una **cadena ordenada**: el primero es el principal y los demás, respaldos (RF-44). Solo modelos open-weight y gratuitos (D-14).

| Archivo | Qué usa | Cuándo |
|---|---|---|
| `models.yaml` | **Mixta** (por defecto, PA-443): Groq (`gpt-oss-120b` y `gpt-oss-20b`) para HU, evolución, estructura, calidad, impacto y memoria, con respaldo local; **QA en local** (`qwen3:1.7b`, respaldo `phi4-mini`) | La demo |
| `models.todo-local.yaml` | **Todo local** (Ollama en CPU): ninguna llamada sale del equipo | Sin red o sin `GROQ_API_KEY` |
| `models.groq.yaml` | **Todo Groq** con respaldo local, también QA | Para comparar; la suite apenas cabe en el nivel gratuito y su iteración no cabe |

`models.local.yaml` es una variante personal y está en `.gitignore`: no se versiona.

> **Datos que salen del equipo.** Con `GROQ_API_KEY`, la configuración mixta y la de todo Groq envían a Groq (un tercero) la HU y el contexto de Jira y del RAG **del proyecto que se elija**: el código no lo limita a un proyecto. Úsalas solo con proyectos de datos sintéticos (AFQP en la demo). Con datos reales, usa `models.todo-local.yaml`, donde ninguna llamada sale del equipo.

## Cambiar de configuración
En el `.env` (nunca en el repositorio):

```
MODELS_CONFIG_PATH=config/models.todo-local.yaml
```

Sin la variable se usa `config/models.yaml`. Hay que reiniciar la API, Streamlit o el servidor MCP para que se lea. Las configuraciones con Groq necesitan `GROQ_API_KEY` en el `.env`; sin ella, las tareas de Groq pasan directamente a su respaldo local.

## Límites por proveedor (PA-443)
El bloque `limits` global vale para todos. Cada proveedor puede cambiar lo suyo en `providers.<nombre>.limits`, y lo que no cambia lo hereda:

| Campo | Para qué |
|---|---|
| `context_window` | Ventana del modelo. Lo que cabe en el prompt de una tarea es lo más restrictivo de su cadena (ventana − tope de salida), para que quepa también si se pasa al respaldo |
| `context_token_budget` | Contexto (Jira y RAG) que se reúne para una tarea: el del primer proveedor de su cadena, o el del modelo elegido en la UI |
| `max_output_tokens` | Topes de salida por tarea. `{}` quita todos los topes (gpt-oss razona y su razonamiento cuenta como salida) |
| `max_wait_s` y `max_retries_on_429` | Cuánto se espera un `Retry-After` ante un 429 antes de pasar al siguiente de la cadena |
| `request_timeout_s` | Tiempo máximo de cada llamada |

La HU de origen siempre se envía entera (PA-442): el presupuesto solo recorta las fuentes opcionales, y si ni así cabe, la operación falla con «no cabe». Un 413 del proveedor («no cabe en el minuto») pasa al respaldo sin reintentar.
