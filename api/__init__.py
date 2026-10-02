"""API HTTP del agente para el frontend propio (T-55, D-04 revisada).

El contrato (`docs/api/openapi.yaml`) se genera desde este paquete con
`uv run python -m api.export_openapi`. La API solo compone el núcleo (`core/`) a través del
contenedor; nunca habla con Jira ni con el LLM por su cuenta.
"""
