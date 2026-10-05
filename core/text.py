"""Utilidades de texto comunes del núcleo, sin dependencias de otros módulos (PA-227)."""


def escape_data(text: str) -> str:
    """Neutraliza los delimitadores dentro de los datos que van a un prompt (inyección).

    Sustituye `&`, `<`, `>` y `"` por sus entidades, con `&` primero, para que un texto no
    fiable no pueda cerrar etiquetas como `<documento>` ni atributos como `clave="…"`.
    """
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
