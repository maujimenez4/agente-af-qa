"""Datos sintéticos coherentes para los fakes: una épica, tres HU y dos documentos.

Dominio ficticio: el servicio de préstamo digital de la «Biblioteca Municipal de Villaficticia».
Ningún dato corresponde a personas, organizaciones ni proyectos reales.
"""

from adapters.base import IssueDetail, IssueLink, IssueSummary, User
from schemas.common import Priority
from schemas.user_story import AcceptanceCriterion, BusinessRule, UserStory

PROJECT_KEY = "DEMO"
PROJECT_NAME = "Servicio digital de Villaficticia (ficticio)"
EPIC_KEY = "DEMO-1"
STORY_KEYS = ("DEMO-2", "DEMO-3", "DEMO-4")

EPIC = IssueDetail(
    key=EPIC_KEY,
    summary="Préstamo digital de libros",
    issue_type="Epic",
    status="En curso",
    description_text=(
        "Permitir a las personas socias de la Biblioteca Municipal de Villaficticia reservar, "
        "renovar y consultar sus préstamos desde la web."
    ),
    labels=["prestamo-digital"],
)

STORIES: dict[str, IssueDetail] = {
    "DEMO-2": IssueDetail(
        key="DEMO-2",
        summary="[HU-01] Reservar un libro disponible",
        issue_type="Story",
        status="Hecho",
        parent_key=EPIC_KEY,
        description_text=(
            "Como persona socia quiero reservar un libro disponible para recogerlo en el "
            "mostrador. Máximo 3 reservas activas por persona socia."
        ),
        links=[IssueLink(link_type="relates to", key="DEMO-3")],
        comments=["Validado con el equipo de sala (comentario ficticio)."],
    ),
    "DEMO-3": IssueDetail(
        key="DEMO-3",
        summary="[HU-02] Renovar un préstamo",
        issue_type="Story",
        status="Por hacer",
        parent_key=EPIC_KEY,
        description_text=(
            "Como persona socia quiero renovar un préstamo antes de su vencimiento. "
            "Solo se permiten 2 renovaciones y no si el libro tiene reservas pendientes."
        ),
        links=[IssueLink(link_type="relates to", key="DEMO-2")],
    ),
    "DEMO-4": IssueDetail(
        key="DEMO-4",
        summary="[HU-03] Consultar el historial de préstamos",
        issue_type="Story",
        status="Por hacer",
        parent_key=EPIC_KEY,
        description_text=(
            "Como persona socia quiero consultar mis préstamos de los últimos 12 meses."
        ),
    ),
}

DOCUMENTS: dict[str, dict[str, str]] = {
    "doc-reglamento": {
        "title": "Reglamento de préstamo (ficticio)",
        "category": "politicas",
        "content": (
            "Artículo 4. Cada persona socia puede tener hasta 3 reservas activas. "
            "Artículo 7. Un préstamo dura 21 días y admite 2 renovaciones si no hay reservas "
            "pendientes sobre el ejemplar."
        ),
    },
    "doc-glosario": {
        "title": "Glosario del servicio de préstamo (ficticio)",
        "category": "glosarios",
        "content": (
            "Reserva: bloqueo temporal de un ejemplar disponible durante 48 horas. "
            "Renovación: ampliación del plazo de un préstamo activo."
        ),
    },
}

# Usuarios sintéticos de demo; contraseñas claramente ficticias.
DEMO_USERS: dict[str, tuple[str, User]] = {
    "af-demo": ("demo-password-af", User(username="af-demo", role="functional")),
    "qa-demo": ("demo-password-qa", User(username="qa-demo", role="qa")),
    "admin-demo": ("demo-password-admin", User(username="admin-demo", role="admin")),
}


def summary_of(issue: IssueDetail) -> IssueSummary:
    return IssueSummary(
        key=issue.key, summary=issue.summary, issue_type=issue.issue_type, status=issue.status
    )


def renewal_story(jira_key: str | None = "DEMO-3") -> UserStory:
    """HU sintética completa, coherente con DEMO-3 y con el reglamento ficticio."""
    return UserStory(
        internal_id="HU-02",
        jira_key=jira_key,
        title="Renovar un préstamo",
        role="persona socia de la biblioteca",
        action="renovar un préstamo activo desde la web",
        benefit="no tener que acudir al mostrador para ampliar el plazo",
        description="La persona socia renueva un préstamo activo antes de su vencimiento.",
        business_goal="Reducir las visitas al mostrador por renovaciones.",
        scope_includes=["Renovación desde la ficha del préstamo"],
        scope_excludes=["Renovación de materiales audiovisuales"],
        acceptance_criteria=[
            AcceptanceCriterion(
                id="CA-01",
                title="Renovación permitida",
                given=["un préstamo activo con menos de 2 renovaciones", "sin reservas pendientes"],
                when=["la persona socia pulsa «Renovar»"],
                then=["el vencimiento se amplía 21 días"],
            ),
            AcceptanceCriterion(
                id="CA-02",
                title="Renovación rechazada por reservas",
                given=["un préstamo activo con reservas pendientes"],
                when=["la persona socia pulsa «Renovar»"],
                then=["se muestra el aviso «El ejemplar tiene reservas pendientes»"],
            ),
        ],
        business_rules=[
            BusinessRule(id="RN-01", description="Máximo 2 renovaciones por préstamo."),
            BusinessRule(id="RN-02", description="No se renueva si hay reservas pendientes."),
        ],
        assumptions=["La persona socia ha iniciado sesión."],
        constraints=["Plazo de préstamo de 21 días (reglamento, art. 7)."],
        dependencies=["DEMO-2"],
        alternate_flows=["Renovación desde el correo de aviso de vencimiento."],
        exceptions=["El servicio de catálogo no responde."],
        related_features=["Reservas"],
        priority=Priority.MUST,
    )
