"""Ejemplos sintéticos del contrato (T-55): los usa la API simulada (Prism) del frontend.

Se construyen con los propios modelos, así que siempre son válidos frente al contrato. Datos
100 % ficticios: biblioteca de Villaficticia, proyecto `DEMO`, usuarios de demo.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from adapters.base import IssueSummary, ProjectSummary
from api.models import (
    ContextBudgetOut,
    ConversationOut,
    ErrorBody,
    ErrorResponse,
    ExecutionCaseOut,
    ExecutionOut,
    ExecutionOutcome,
    ExecutionResultOut,
    HandoffOut,
    IssueCard,
    ModelChoiceOut,
    ProgressStep,
    ProjectsOut,
    PublishOutcome,
    QualityReviewOut,
    QualityReviewSummary,
    ReviewPayload,
    SessionOut,
    SettingsOut,
    SourcesOut,
    TaskModelsOut,
    UncoveredRefs,
    UserOut,
    VersionOut,
)
from api.service import QA_STEP_LABELS
from core.conversations import ConversationSummary
from core.guided_start import SourcePreview, StartOption, StartProposal
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType, Priority, SourceRef
from schemas.impact import ImpactAnalysis, ImpactItem, StoryDiff
from schemas.quality import InvestCheck, QualityFinding, QualityReport
from schemas.test_case import TestCase, TestCaseType, TestStep, TestSuite
from schemas.user_story import AcceptanceCriterion, BusinessRule, UserStory

NOW = datetime(2026, 10, 2, 10, 30, tzinfo=UTC)
ARTIFACT_ID = UUID("6f1c2a9e-3b7d-4c11-9a40-2d8e5f7b1c03")
THREAD_ID = "8b0f3c2e-7d41-4a5e-9c6b-1e2f3a4b5c6d"
FINGERPRINT = "4f" * 32

STORY = UserStory(
    internal_id="HU-02",
    jira_key="DEMO-3",
    title="Renovar un préstamo",
    role="persona socia de la biblioteca",
    action="renovar un préstamo activo desde la web o la app",
    benefit="no tener que acudir al mostrador para ampliar el plazo",
    description="La persona socia renueva un préstamo activo antes de su vencimiento.",
    business_goal="Reducir las visitas al mostrador por renovaciones.",
    scope_includes=["Renovación desde la ficha del préstamo", "Renovación desde la app"],
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
    changes_from_previous=["CA-02: se añade el aviso de reservas pendientes (fuente DOC-01)."],
    priority=Priority.MUST,
    sources=[
        SourceRef(kind="rag", ref="DOC-01", excerpt="Cada préstamo admite hasta 2 renovaciones."),
        SourceRef(kind="jira", ref="DEMO-3", excerpt="Renovar un préstamo"),
    ],
)
IMPACT = ImpactAnalysis(
    diffs=[
        StoryDiff(
            field="acceptance_criteria[CA-02]",  # formato real de core/impact/diff.py (PA-341)
            before=None,
            after="Renovación rechazada por reservas",
        )
    ],
    affected=[ImpactItem(jira_key="DEMO-2", reason="Comparte la regla de reservas", kind="rule")],
    regression_notes=["Revisar el flujo de reservas."],
)
ARTIFACT = Artifact(
    id=ARTIFACT_ID,
    type=ArtifactType.USER_STORY,
    status=ArtifactStatus.IN_REVIEW,
    version=2,
    origin_key="DEMO-3",
    content=STORY,
    impact=IMPACT,
    created_by="af-demo",
    model_used="local/qwen3:4b-instruct",
    prompt_version="2",
)
PLAN = [
    {"op": "update_story", "project": "DEMO", "key": "DEMO-3"},
    {"op": "comment", "key": "DEMO-3"},
    {"op": "link", "from": "DEMO-3", "to": "DEMO-2", "type": "relates to"},
]

SESSION = SessionOut(
    user=UserOut(
        username="af-demo",
        role="functional",
        permissions=["view_context", "generate_story", "publish_story", "view_memory"],
    ),
    csrf_token="csrf-token-ficticio-0123456789abcdef",  # noqa: S106 (ejemplo ficticio)
)
PROJECTS = ProjectsOut(
    projects=[
        ProjectSummary(key="DEMO", name="Biblioteca"),
        ProjectSummary(key="SOCI", name="Gestión de personas socias"),
    ],
    preselected="DEMO",
)
EPICS = [
    IssueSummary(key="DEMO-1", summary="Préstamo digital", issue_type="Epic", status="Abierta")
]
STORIES = [
    IssueSummary(key="DEMO-2", summary="Reservar un libro", issue_type="Story", status="Hecho"),
    IssueSummary(key="DEMO-3", summary="Renovar un préstamo", issue_type="Story", status="Abierta"),
]
CARD = IssueCard(
    key="DEMO-3",
    project="DEMO",
    summary="Renovar un préstamo",
    issue_type="Story",
    status="Abierta",
    epic_key="DEMO-1",
    criteria_count=2,
    rules_count=2,
    test_cases=0,
    published_by_agent=False,
)
PROPOSAL = StartProposal(
    project="DEMO",
    project_changed=False,
    recognized=[],
    similar=[STORIES[1]],
    options=[
        StartOption(
            kind="evolve",
            label="Evolucionar DEMO-3",
            origin={"kind": "story", "key": "DEMO-3", "project": "DEMO"},
            issue=STORIES[1],
        ),
        StartOption(
            kind="new_need",
            label="Crear HU nueva",
            origin={
                "kind": "need",
                "text": "Renovar un préstamo desde la app (ficticio).",
                "project": "DEMO",
            },
        ),
    ],
)
SOURCES = [
    SourcePreview(
        ref="DEMO-3", kind="jira", title="Renovar un préstamo", category="Story", required=True
    ),
    SourcePreview(ref="DOC-01", kind="rag", title="Reglamento de préstamo", category="politicas"),
    SourcePreview(
        ref="memoria-DEMO-2", kind="memory", title="Memoria de DEMO-2", category="memoria"
    ),
]
REVIEW = ReviewPayload(
    artifact=ARTIFACT,
    version=2,
    target={
        "operation": "actualizar HU",
        "project": "DEMO",
        "jira_key": "DEMO-3",
        "epic_key": None,
    },
    fingerprint=FINGERPRINT,
    impact=IMPACT,
    plan=PLAN,
    decisions=["iterate", "edit", "approve", "discard"],
)
STEPS_DONE = [
    ProgressStep(node="load_origin", label="Cargar el origen", state="done"),
    ProgressStep(node="retrieve_context", label="Recuperar contexto", state="done"),
    ProgressStep(node="generate", label="Generar la propuesta", state="done"),
]
CONVERSATION = ConversationOut(
    id=THREAD_ID,
    title="Evolucionar DEMO-3",
    project="DEMO",
    flow="evolve",
    mode="functional",
    state="in_review",
    progress=STEPS_DONE,
    review=REVIEW,
    versions=[VersionOut(version=2, artifact=ARTIFACT, created_at=NOW)],
    feedback=["Mismas reglas que en la web."],
    updated_at=NOW,
    # PA-316: la HU tal como está en Jira (versión de partida), para el selector de versiones.
    # Sin el CA-02, que `IMPACT.diffs` da por nuevo en esta versión.
    jira_baseline=STORY.model_copy(
        update={"changes_from_previous": [], "acceptance_criteria": STORY.acceptance_criteria[:1]}
    ),
)
CONVERSATION_GENERATING = CONVERSATION.model_copy(
    update={
        "state": "generating",
        "review": None,
        "versions": [],
        "jira_baseline": None,  # PA-316: antes de la primera versión aún no hay
        "progress": [
            ProgressStep(node="load_origin", label="Cargar el origen", state="done"),
            ProgressStep(node="retrieve_context", label="Recuperar contexto", state="running"),
            ProgressStep(node="generate", label="Generar la propuesta", state="pending"),
        ],
    }
)
# PA-314: pedida la detención; termina el paso en curso («Deteniendo…»).
CONVERSATION_CANCELLING = CONVERSATION_GENERATING.model_copy(update={"cancel_requested": True})
CONVERSATION_SIMULATED = CONVERSATION.model_copy(
    update={
        "state": "simulated",
        "review": None,
        "jira_baseline": None,  # PA-316: terminada, ya no se itera
        "result": PublishOutcome(simulated=True, plan=PLAN, approved_by="af-demo", approved_at=NOW),
    }
)
CONVERSATION_DISCARDED = CONVERSATION.model_copy(
    update={"state": "discarded", "review": None, "jira_baseline": None}
)


def qa_steps(*done: str, running: str | None = None) -> list[ProgressStep]:
    """PA-327: los pasos de QA (4: en QA no se guarda memoria) con sus etiquetas reales."""
    return [
        ProgressStep(
            node=node,  # type: ignore[arg-type]
            label=label,
            state="done" if node in done else "running" if node == running else "pending",
        )
        for node, label in QA_STEP_LABELS.items()
    ]


QA_THREAD_ID = "d4f6b8c0-3e5a-4b7c-9d1e-2f3a4b5c6d7e"
CONVERSATION_QA = CONVERSATION_GENERATING.model_copy(
    update={
        "id": QA_THREAD_ID,
        "title": "Preparar pruebas de DEMO-3",
        "flow": "tests",
        "mode": "qa",
        "feedback": [],
        "progress": qa_steps("load_origin", running="retrieve_context"),
    }
)


def _case(
    internal_id: str,
    title: str,
    criteria: list[str],
    rules: list[str],
    kind: TestCaseType,
    steps: list[TestStep],
    gherkin: str,
) -> TestCase:
    return TestCase(
        internal_id=internal_id,
        title=title,
        criterion_ids=criteria,
        rule_ids=rules,
        type=kind,
        preconditions=["La persona socia ficticia SOC-0001 ha iniciado sesión."],
        steps=steps,
        gherkin=gherkin,
        priority=Priority.MUST,
    )


# PA-326: suite sintética de DEMO-3 (la HU de `STORY`): 4 casos sobre CA-01/CA-02 y RN-01/RN-02.
SUITE = TestSuite(
    story_jira_key="DEMO-3",
    cases=[
        _case(
            "CP-01",
            "Renovar un préstamo sin reservas ni renovaciones previas",
            ["CA-01"],
            ["RN-01"],
            TestCaseType.POSITIVE,
            [
                TestStep(
                    action="Abrir la ficha del préstamo PR-0001",
                    data="PR-0001",
                    expected="Se muestra el botón «Renovar»",
                ),
                TestStep(action="Pulsar «Renovar»", expected="El vencimiento se amplía 21 días"),
            ],
            "Dado un préstamo activo sin renovaciones ni reservas\n"
            "Cuando la persona socia pulsa «Renovar»\nEntonces el vencimiento se amplía 21 días",
        ),
        _case(
            "CP-02",
            "Rechazar la renovación de un préstamo con reservas pendientes",
            ["CA-02"],
            ["RN-02"],
            TestCaseType.NEGATIVE,
            [
                TestStep(
                    action="Abrir la ficha del préstamo PR-0002 (con 1 reserva)",
                    data="PR-0002",
                    expected="Se muestra el botón «Renovar»",
                ),
                TestStep(
                    action="Pulsar «Renovar»",
                    expected="Aviso «El ejemplar tiene reservas pendientes»",
                ),
            ],
            "Dado un préstamo activo con reservas pendientes\n"
            "Cuando la persona socia pulsa «Renovar»\n"
            "Entonces se muestra el aviso «El ejemplar tiene reservas pendientes»",
        ),
        _case(
            "CP-03",
            "Rechazar una tercera renovación",
            ["CA-01"],
            ["RN-01"],
            TestCaseType.EXCEPTION,
            [
                TestStep(
                    action="Abrir la ficha del préstamo PR-0003 (2 renovaciones)",
                    data="PR-0003",
                    expected="El botón «Renovar» no está disponible",
                ),
            ],
            "Dado un préstamo activo con 2 renovaciones\n"
            "Cuando la persona socia abre su ficha\nEntonces no puede renovarlo",
        ),
        _case(
            "CP-04",
            "Renovar desde el correo de aviso de vencimiento",
            ["CA-01"],
            [],
            TestCaseType.ALTERNATE,
            [
                TestStep(
                    action="Abrir el enlace «Renovar» del correo de aviso ficticio",
                    expected="El vencimiento se amplía 21 días",
                ),
            ],
            "Dado un aviso de vencimiento de un préstamo renovable\n"
            "Cuando la persona socia usa el enlace «Renovar»\n"
            "Entonces el vencimiento se amplía 21 días",
        ),
    ],
    strategy_md="# Estrategia de pruebas · DEMO-3\n\n- Alcance: renovación de préstamos.\n"
    "- Niveles: funcional y de integración con el catálogo.\n- Entorno: preproducción.\n",
    synthetic_data=[
        {"prestamo": "PR-0001", "renovaciones": "0", "reservas": "0"},
        {"prestamo": "PR-0002", "renovaciones": "0", "reservas": "1"},
        {"prestamo": "PR-0003", "renovaciones": "2", "reservas": "0"},
    ],
    risks=["El catálogo puede no responder al renovar."],
    dependencies=["DEMO-2"],
    impact_areas=["Reservas"],
    sources=[SourceRef(kind="jira", ref="DEMO-3", excerpt="Renovar un préstamo")],
)
SUITE_ARTIFACT = Artifact(
    id=UUID("9a3c5e7f-1b2d-4e6f-8a0b-1c2d3e4f5a6b"),
    type=ArtifactType.TEST_SUITE,
    status=ArtifactStatus.IN_REVIEW,
    version=1,
    origin_key="DEMO-3",
    content=SUITE,
    created_by="qa-demo",
    model_used="local/qwen3:4b-instruct",
    prompt_version="3",
)
# PA-326: conversación de QA en revisión → `components.examples.ConversationQaInReview`.
CONVERSATION_QA_REVIEW = ConversationOut(
    id=QA_THREAD_ID,
    title="Preparar pruebas de DEMO-3",
    project="DEMO",
    flow="tests",
    mode="qa",
    state="in_review",
    progress=qa_steps("load_origin", "retrieve_context", "generate"),
    review=ReviewPayload(
        artifact=SUITE_ARTIFACT,
        version=1,
        target={
            "operation": "publicar casos de prueba",
            "project": "DEMO",
            "jira_key": "DEMO-3",
            "epic_key": None,
        },
        fingerprint="7c" * 32,
        plan=[{"op": "publish_suite", "project": "DEMO", "story": "DEMO-3", "cases": "4"}],
        decisions=["iterate", "edit", "approve", "discard"],
        coverage_md=SUITE.coverage_md(),
        uncovered=UncoveredRefs(criteria=[], rules=[]),  # listas vacías: todo cubierto
    ),
    versions=[VersionOut(version=1, artifact=SUITE_ARTIFACT, created_at=NOW)],
    feedback=[],
    updated_at=NOW,
)
CONVERSATIONS = [
    ConversationSummary(
        thread_id=THREAD_ID,
        username="af-demo",
        project_key="DEMO",
        mode="functional",
        origin_kind="story",
        origin_key="DEMO-3",
        title="Evolucionar DEMO-3",
        status="in_review",
        artifact_id=str(ARTIFACT_ID),
        version=2,
        created_at=NOW,
        updated_at=NOW,
    )
]
QUALITY_REPORT = QualityReport(
    summary="La HU es valiosa y pequeña; hay un criterio ambiguo y un hueco (ficticio).",
    invest=[
        InvestCheck(
            letter=letter,
            verdict="improvable" if letter == "T" else "ok",
            reason=f"Motivo ficticio de {letter}.",
        )
        for letter in ("I", "N", "V", "E", "S", "T")
    ],
    findings=[
        QualityFinding(
            kind="ambiguity",
            target_id="CA-02",
            explanation="«Avisar pronto» no se puede probar.",
            proposal="Avisar en menos de 15 minutos.",
        ),
        QualityFinding(
            kind="gap",
            explanation="No dice qué pasa si la renovación falla.",
            proposal="Añadir un criterio de error.",
        ),
    ],
    open_questions=["¿Hay un máximo de renovaciones por año? (ficticio)"],
    sources=[SourceRef(kind="rag", ref="DOC-01")],
)
QUALITY = QualityReviewOut(
    id="b2d4f6a8-1c3e-4f5a-8b9c-0d1e2f3a4b5c",
    issue_key="DEMO-3",
    state="done",
    report=QUALITY_REPORT,
    evolve_feedback=["CA-02: Avisar en menos de 15 minutos.", "Añadir un criterio de error."],
    report_markdown=QUALITY_REPORT.to_markdown("DEMO-3"),
    created_at=NOW,
    updated_at=NOW,
)
QUALITY_LIST = [
    QualityReviewSummary(
        id=QUALITY.id,
        issue_key="DEMO-3",
        project="DEMO",
        title="Revisar la calidad de DEMO-3",
        state="done",
        created_at=NOW,
        updated_at=NOW,
    )
]
EXECUTION_ID = "5d7f9b1c-3e5a-4c7e-9a1b-2c3d4e5f6a7b"
EXECUTION_CASES = [
    ExecutionCaseOut(
        key="DEMO-501", summary="[CP-01] Renovar dentro del plazo", status="Por hacer"
    ),
    ExecutionCaseOut(key="DEMO-502", summary="[CP-02] Renovar con una reserva", status="Por hacer"),
]
EXECUTION_RESULTS = [
    ExecutionResultOut(case_key="DEMO-501", status="paso", evidence_md=""),
    ExecutionResultOut(
        case_key="DEMO-502", status="fallo", evidence_md="El botón no se desactiva (ficticio)."
    ),
]
EXECUTION = ExecutionOut(
    id=EXECUTION_ID,
    story_key="DEMO-3",
    project="DEMO",
    state="in_review",
    cases=EXECUTION_CASES,
    results=EXECUTION_RESULTS,
    environment="preproducción",
    plan=[
        {
            "op": "record_execution",
            "key": "DEMO-501",
            "status": "paso",
            "label": "Pasó",
            "evidence": "no",
        },
        {
            "op": "record_execution",
            "key": "DEMO-502",
            "status": "fallo",
            "label": "Falló",
            "evidence": "sí",
        },
    ],
    fingerprint=FINGERPRINT,
)
EXECUTION_RECORDED = EXECUTION.model_copy(
    update={
        "state": "recorded",
        "plan": [],
        "fingerprint": None,
        "outcome": ExecutionOutcome(
            recorded=["DEMO-501", "DEMO-502"], approved_by="qa-demo", approved_at=NOW
        ),
    }
)
# PA-330: los tokens de cada fuente suman `used`; `fixed` es 0 porque el origen es una HU.
SOURCES_OUT = SourcesOut(
    sources=[
        source.model_copy(update={"tokens": tokens})
        for source, tokens in zip(SOURCES, (1200, 800, 350), strict=True)
    ],
    budget=ContextBudgetOut(
        used=2350, limit=6000, dropped_sources=0, truncated_sources=1, fixed=0, total=6000
    ),
)
HANDOFFS = [
    HandoffOut(
        id="c3e5a7b92d4f4a6b8c0d1e2f3a4b5c6d",
        title="Renovar un préstamo",
        project="DEMO",
        story_key="DEMO-3",
        version=2,
        from_user="af-demo",
        created_at=NOW,
    )
]
SETTINGS = SettingsOut(
    publish_mode="simulation",
    jira_browse_url="https://villaficticia-ejemplo.atlassian.net/browse/",
    tasks=[
        TaskModelsOut(
            task="generate_story",
            chain=[ModelChoiceOut(provider="local", model="qwen3:4b-instruct")],
        )
    ],
)


def error(code: str, message: str, retry_after: float | None = None) -> dict[str, Any]:
    return ErrorResponse(
        error=ErrorBody(code=code, message=message, retry_after=retry_after)
    ).model_dump(mode="json")


def dump(value: Any) -> Any:
    """Ejemplo en JSON (modelo, o lista de modelos)."""
    if isinstance(value, list):
        return [v.model_dump(mode="json") for v in value]
    return value.model_dump(mode="json")
