"""Logging estructurado en JSON con structlog y enmascarado de secretos (RNF-02, RNF-23).

Campos convencionales de cada evento: `user`, `action`, `artifact_id`, `model`, `duration_ms`.
Nunca se registran secretos, cabeceras `Authorization` ni prompts completos.
"""

import logging
import re
import sys
from collections.abc import Iterable, MutableMapping
from typing import Any, TextIO

import structlog
from pydantic import SecretStr

MASK = "***"

# Claves cuyo valor se oculta siempre, sea cual sea su contenido (guiones → guiones bajos).
# `tokens_used`, `max_tokens` o `context_token_budget` no son secretos y no se ocultan.
_SENSITIVE_KEY = re.compile(
    r"^(.*_)?(pass(word|wd)?|pwd|secret|(access_|refresh_|api_|auth_|id_)?token|api_?key"
    r"|private_key|session(_id)?|authorization|auth|(set_)?cookie|credentials?|database_url|dsn"
    r"|email|cloud_id)$",
    re.IGNORECASE,
)

_SENSITIVE_WORDS = r"password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key"
# Nombre de clave dentro de un texto, con o sin prefijo: password, POSTGRES_PASSWORD, "api-key"…
_KEY_IN_TEXT = rf"(?<![A-Za-z0-9])(?:[A-Za-z0-9]+[_-])*(?:{_SENSITIVE_WORDS})[\"']?\s*[:=]\s*"

# Patrones reconocibles dentro de un texto, con su sustitución.
_TOKEN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), MASK),
    # Basic solo con aspecto de base64 (evita ocultar "Basic authentication").
    (re.compile(r"\bBasic\s+(?=[A-Za-z0-9+/]*[0-9+/=])[A-Za-z0-9+/]{12,}={0,2}"), MASK),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), MASK),  # JWT
    (re.compile(r"\b(sk|gsk|sk-or-v1|ghp|gho|xox[abp])[-_][A-Za-z0-9_-]{16,}"), MASK),
    (re.compile(r"\bATATT[A-Za-z0-9_=-]{20,}"), MASK),  # token de API de Atlassian
    # Contraseña en una URL de conexión (hasta la última @).
    (re.compile(r"(?i)(://[^:/@\s]+:)\S+(@)"), rf"\1{MASK}\2"),
    # Parámetros de query: ?api_key=…, &access_token=…
    (re.compile(r"(?i)([?&][\w-]*(?:token|key|secret|passw(?:or)?d)=)[^&\s#]+"), rf"\1{MASK}"),
    # Cabecera Authorization en texto: se oculta hasta el final de la línea.
    (re.compile(r"(?i)(\bauthorization[\"']?\s*[:=]\s*)(?![\"'])[^\r\n]+"), rf"\1{MASK}"),
    # Pares clave-valor con el valor entre comillas: se oculta hasta la comilla de cierre.
    (
        re.compile(rf"(?i)({_KEY_IN_TEXT}|\bauthorization[\"']?\s*[:=]\s*)([\"'])(?:(?!\2).)*\2"),
        rf"\1\2{MASK}\2",
    ),
    # Pares clave-valor sin comillas: POSTGRES_PASSWORD=…, token: …
    (re.compile(rf"(?i)({_KEY_IN_TEXT})(?![\"'])(?!\*\*\*)[^\s,;&}}\"']+"), rf"\1{MASK}"),
]


def _is_sensitive_key(key: object) -> bool:
    return isinstance(key, str) and bool(_SENSITIVE_KEY.match(key.replace("-", "_")))


class SecretMasker:
    """Procesador de structlog que oculta secretos conocidos y patrones de token."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        # Los más largos primero, para no dejar restos de un secreto que contiene a otro.
        self._secrets = sorted({s for s in secrets if s and len(s) >= 4}, key=len, reverse=True)

    def mask_text(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, MASK)
        for pattern, replacement in _TOKEN_PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    def _mask(self, value: Any) -> Any:
        if isinstance(value, SecretStr):
            return MASK
        if isinstance(value, str):
            return self.mask_text(value)
        if isinstance(value, bytes | bytearray):
            return self.mask_text(bytes(value).decode("utf-8", "replace"))
        if isinstance(value, dict):
            return {k: MASK if _is_sensitive_key(k) else self._mask(v) for k, v in value.items()}
        if isinstance(value, list | tuple | set):
            return type(value)(self._mask(v) for v in value)
        if isinstance(value, int | float | bool) or value is None:
            return value
        return self.mask_text(str(value))

    def __call__(
        self, logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        for key, value in list(event_dict.items()):
            if _is_sensitive_key(key):
                event_dict[key] = MASK
            else:
                event_dict[key] = self._mask(value)
        return event_dict


def configure_logging(
    level: str = "INFO", secrets: Iterable[str] = (), stream: TextIO | None = None
) -> None:
    """Configura structlog con salida JSON; `secrets` son valores que nunca deben aparecer."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            SecretMasker(secrets),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=stream or sys.stdout),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> structlog.typing.FilteringBoundLogger:
    return structlog.get_logger(name) if name else structlog.get_logger()
