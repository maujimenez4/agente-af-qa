"""Datos fijos de las pruebas (PA-458): no dependen de la configuración real de la demo."""

from pathlib import Path

# Copia fija de `config/models.yaml` para las pruebas; solo `test_config.py` lee el YAML real.
MODELS_FIXTURE = Path(__file__).with_name("models.yaml")
