"""Genera `docs/api/openapi.yaml` desde el código: `uv run python -m api.export_openapi`."""

import sys
from pathlib import Path
from typing import Any

import yaml

from api import examples as ex
from api.app import create_app
from core.config import ROOT_DIR

OPENAPI_PATH = ROOT_DIR / "docs" / "api" / "openapi.yaml"


def openapi_document() -> dict[str, Any]:
    document = create_app().openapi()
    document["components"]["securitySchemes"] = {
        "sessionCookie": {"type": "apiKey", "in": "cookie", "name": "afqa_session"},
        "csrfHeader": {"type": "apiKey", "in": "header", "name": "X-CSRF-Token"},
    }
    document["security"] = [{"sessionCookie": [], "csrfHeader": []}]
    # PA-326: ejemplos con nombre, aparte de los `example` de cada respuesta (que no cambian).
    document["components"]["examples"] = {
        "ConversationQaInReview": {
            "summary": "Conversación de QA en revisión (GET /conversations/{id})",
            "description": "Suite sintética de DEMO-3 con `coverage_md` y `uncovered` (PA-326) "
            "y los 4 pasos de QA (PA-327).",
            "value": ex.dump(ex.CONVERSATION_QA_REVIEW),
        }
    }
    for path, item in document["paths"].items():
        for method, operation in item.items():
            if path.endswith("/auth/login"):
                operation["security"] = []  # sin sesión todavía (protección: Origin + SameSite)
            elif method == "get":
                operation["security"] = [{"sessionCookie": []}]  # los GET no llevan CSRF
            # El 422 usa la forma común de error, sin la entrada enviada.
            if "422" in operation.get("responses", {}):
                operation["responses"]["422"] = {
                    "description": "Petición no válida (sin devolver lo enviado).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                            "example": {
                                "error": {
                                    "code": "invalid_request",
                                    "message": "La petición no es válida: revisa password.",
                                    "retry_after": None,
                                }
                            },
                        }
                    },
                }
    for name in ("HTTPValidationError", "ValidationError"):
        document["components"]["schemas"].pop(name, None)
    return document


def render() -> str:
    header = (
        "# Contrato de la API (T-55). GENERADO: no editar a mano.\n"
        "# Regenerar con: uv run python -m api.export_openapi\n"
    )
    return header + yaml.safe_dump(
        openapi_document(), allow_unicode=True, sort_keys=False, width=100
    )


def main(path: Path = OPENAPI_PATH) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(), encoding="utf-8", newline="\n")
    sys.stdout.reconfigure(encoding="utf-8")  # consolas de Windows en cp1252
    print(f"Contrato escrito en {path.relative_to(ROOT_DIR)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
