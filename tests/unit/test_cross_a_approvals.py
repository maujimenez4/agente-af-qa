"""Prueba cruzada T-35 (RNF-19): el área B prueba el núcleo de aprobación del área A.

Objeto de prueba: `core/approvals.py`, `core/state_machine.py`, `core/audit.py` y
`core/artifact_state.py`. Cubre el principio 1 de CLAUDE.md (nada se publica sin aprobación
humana), RF-34 (estados del artefacto, CA-00-07), RF-35 (auditoría) y las filas del anexo §11 de
la SPEC-00 «Aprobación humana», «Auditoría», «Proyecto en la conversación» y «Versión de
partida» (persistencia en `artifact_state`), en los bordes que las pruebas existentes no fijan:
huella frente a cada campo de la operación, aprobación de otra versión u otro usuario, registro
dañado o manipulado (tipos inesperados), doble consumo, dos instancias sobre el mismo almacén,
ofertas rechazadas, tipos inesperados en la máquina de estados y lo que llega a `audit_log`.

Sin servicios reales: almacenes en memoria y motores espía; la única prueba con PostgreSQL va
marcada `integration` y se salta sin BD. Datos 100 % ficticios (biblioteca de Villaficticia,
proyecto DEMO). Los defectos confirmados van como `xfail(strict=True)`; el resto fija el
comportamiento actual.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine

from adapters.errors import InvalidTransitionError
from core.approvals import (
    ApprovalError,
    ApprovalLedger,
    PublishTarget,
    content_fingerprint,
    review_fingerprint,
)
from core.artifact_state import ARTIFACT_STATE, InMemoryArtifactStateStore, SqlArtifactStateStore
from core.audit import AuditEntry, InMemoryAuditTrail, SqlAuditTrail
from core.state_machine import can_transition, ensure_transition, transition
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType, SourceRef
from schemas.impact import ImpactAnalysis, ImpactItem, StoryDiff
from tests.fakes import dataset
from tests.fakes.llm import renewal_test_suite
from tests.pg_temp import temporary_database

S = ArtifactStatus
USER = "af-villaficticia"
OTHER_USER = "qa-villaficticia"
ORIGIN = "DEMO-3"
TARGET = PublishTarget(
    mode="functional",
    origin_kind="story",
    origin_key=ORIGIN,
    project_key="DEMO",
    user=USER,
    thread_id="hilo-ficticio-1",
)


# --- utilidades --------------------------------------------------------------------------


def _artifact(
    version: int = 1,
    *,
    artifact_id: UUID | None = None,
    title: str | None = None,
    status: ArtifactStatus = S.IN_REVIEW,
) -> Artifact:
    story = dataset.renewal_story()
    if title is not None:
        story = story.model_copy(update={"title": title})
    return Artifact(
        id=artifact_id or uuid4(),
        type=ArtifactType.USER_STORY,
        status=status,
        version=version,
        origin_key=ORIGIN,
        content=story,
        created_by=USER,
    )


def _next(artifact: Artifact, title: str) -> Artifact:
    """Versión siguiente del mismo artefacto con otro título (iteración)."""
    return _artifact(artifact.version + 1, artifact_id=artifact.id, title=title)


def _impact(reason: str = "Comparte la regla RN-01 (ficticia).") -> ImpactAnalysis:
    return ImpactAnalysis(
        diffs=[StoryDiff(field="title", before="Renovar", after="Renovar un préstamo")],
        affected=[ImpactItem(jira_key="DEMO-5", reason=reason, kind="story")],
        regression_notes=["Revisar la renovación desde el correo (ficticio)."],
    )


def _approved(ledger: ApprovalLedger, artifact: Artifact, target: PublishTarget = TARGET) -> Any:
    ledger.offer(artifact, target)
    return ledger.record(artifact, target)


def _vigente(ledger: ApprovalLedger, artifact: Artifact, target: PublishTarget = TARGET) -> bool:
    """¿Hay aprobación utilizable? Un `ApprovalError` (fallo cerrado) cuenta como «no»."""
    try:
        return ledger.find(artifact, target) is not None
    except ApprovalError:
        return False


def _stored_ledger(store: InMemoryArtifactStateStore, artifact: Artifact) -> dict[str, Any]:
    state = store.load(str(artifact.id))
    assert state is not None
    return state["ledger"]


class RawStateStore:
    """Almacén que devuelve el JSON tal cual, como haría una columna JSONB manipulada."""

    def __init__(self, raw: Any = None) -> None:
        self.raw: dict[str, Any] = {}
        self.saved: list[tuple[str, Any]] = []
        self._default = raw

    def load(self, artifact_id: str) -> Any:
        return self.raw.get(artifact_id, self._default)

    def save(self, artifact_id: str, state: Any) -> None:
        self.saved.append((artifact_id, state))
        self.raw[artifact_id] = state


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def mappings(self) -> Any:
        return self._value or []


class SpyEngine:
    """Engine espía: guarda las sentencias y devuelve un valor fijo (sin red)."""

    def __init__(self, value: Any = None) -> None:
        self.value = value
        self.statements: list[Any] = []

    @contextmanager
    def begin(self) -> Iterator["SpyEngine"]:
        yield self

    def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result(self.value)


def _params(statement: Any) -> dict[str, Any]:
    return dict(statement.compile(dialect=postgresql.dialect()).params)


# --- Huella (anexo §11 «Aprobación humana» y «Proyecto en la conversación») ---------------


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("mode", "qa"),
        ("origin_kind", "need"),
        ("origin_key", "DEMO-4"),
        ("project_key", "OTRO"),
        ("user", OTHER_USER),
        ("thread_id", "hilo-ficticio-2"),
    ],
)
def test_review_fingerprint_changes_when_any_target_field_changes(
    field_name: str, value: str
) -> None:
    """Principio 1 · T-50: la huella aprobada cubre modo, origen, proyecto, usuario e hilo."""
    artifact = _artifact()
    other = replace(TARGET, **{field_name: value})
    assert review_fingerprint(artifact, other) != review_fingerprint(artifact, TARGET)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda a: a.model_copy(update={"id": uuid4()}), id="id"),
        pytest.param(lambda a: a.model_copy(update={"impact": _impact()}), id="impacto"),
        pytest.param(
            lambda a: a.model_copy(
                update={
                    "content": a.content.model_copy(
                        update={
                            "acceptance_criteria": [
                                a.content.acceptance_criteria[0].model_copy(
                                    update={"then": ["el vencimiento se amplía 30 días"]}
                                ),
                                *a.content.acceptance_criteria[1:],
                            ]
                        }
                    )
                }
            ),
            id="then-de-un-CA",
        ),
        pytest.param(
            lambda a: a.model_copy(
                update={
                    "content": a.content.model_copy(
                        update={"sources": [SourceRef(kind="jira", ref="DEMO-9")]}
                    )
                }
            ),
            id="fuentes",
        ),
        pytest.param(
            lambda a: a.model_copy(
                update={"content": a.content.model_copy(update={"jira_key": "DEMO-8"})}
            ),
            id="jira_key-del-contenido",
        ),
    ],
)
def test_content_fingerprint_changes_when_nested_relevant_field_changes(change: Any) -> None:
    """Principio 1: cualquier cambio en lo revisado (anidado o impacto) invalida la huella."""
    artifact = _artifact()
    assert content_fingerprint(change(artifact)) != content_fingerprint(artifact)


def test_content_fingerprint_changes_when_impact_reason_changes() -> None:
    """T-50: los vínculos del impacto entran en la huella; cambiar el motivo la cambia."""
    base = _artifact().model_copy(update={"impact": _impact()})
    other = base.model_copy(update={"impact": _impact("Motivo distinto (ficticio).")})
    assert content_fingerprint(base) != content_fingerprint(other)


def test_content_fingerprint_changes_when_type_and_content_change() -> None:
    """Principio 1: una suite de QA y una HU del mismo id/versión no comparten huella."""
    story = _artifact()
    suite = Artifact(
        id=story.id,
        type=ArtifactType.TEST_SUITE,
        status=S.IN_REVIEW,
        version=1,
        origin_key=ORIGIN,
        content=renewal_test_suite(ORIGIN),
        created_by=USER,
    )
    assert content_fingerprint(story) != content_fingerprint(suite)


@pytest.mark.parametrize(
    "update",
    [
        {"created_by": OTHER_USER},
        {"model_used": "modelo-ficticio:7b"},
        {"prompt_version": "9.9"},
        {"status": S.APPROVED},
    ],
)
def test_content_fingerprint_ignores_metadata_when_only_metadata_changes(
    update: dict[str, Any],
) -> None:
    """Anexo §11: la huella cubre lo revisado; metadatos y estado no invalidan la aprobación."""
    artifact = _artifact()
    assert content_fingerprint(artifact.model_copy(update=update)) == content_fingerprint(artifact)


def test_content_fingerprint_is_deterministic_when_rebuilt_and_large() -> None:
    """Límite: misma entrada → misma huella (64 hex) aunque el texto sea muy largo."""
    artifact_id = uuid4()
    long_title = "Renovación ñandú «ficticia» " * 4000
    first = _artifact(artifact_id=artifact_id, title=long_title)
    second = _artifact(artifact_id=artifact_id, title=long_title)
    fingerprint = content_fingerprint(first)
    assert fingerprint == content_fingerprint(second)
    assert len(fingerprint) == 64
    assert set(fingerprint) <= set("0123456789abcdef")


def test_review_fingerprint_does_not_embed_target_or_content_when_computed() -> None:
    """RNF de secretos/datos: la huella es un hash, no lleva el título ni el usuario."""
    artifact = _artifact()
    fingerprint = review_fingerprint(artifact, TARGET)
    assert USER not in fingerprint
    assert artifact.content.title not in fingerprint


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (
            replace(TARGET, mode="qa"),
            {
                "operation": "publicar casos de prueba",
                "project": "DEMO",
                "jira_key": ORIGIN,
                "epic_key": None,
            },
        ),
        (
            replace(TARGET, origin_kind="epic", origin_key="DEMO-1"),
            {"operation": "crear HU", "project": "DEMO", "jira_key": None, "epic_key": "DEMO-1"},
        ),
        (
            replace(TARGET, origin_kind="need", origin_key=None),
            {"operation": "crear HU", "project": "DEMO", "jira_key": None, "epic_key": None},
        ),
    ],
)
def test_describe_shows_operation_and_project_when_target_varies(
    target: PublishTarget, expected: dict[str, Any]
) -> None:
    """Anexo §11 «Reanudación»: la UI muestra la operación y el proyecto antes de aprobar."""
    assert target.describe() == expected


# --- Ciclo oferta → aprobación → consumo (principio 1, anexo §11) ------------------------


def test_record_rejects_approval_when_user_differs() -> None:
    """Principio 1: otra persona (otro `user` en la operación) no puede aprobar."""
    ledger = ApprovalLedger()
    artifact = _artifact()
    ledger.offer(artifact, TARGET)
    with pytest.raises(ApprovalError):
        ledger.record(artifact, replace(TARGET, user=OTHER_USER))
    assert ledger.is_offered(artifact, TARGET)  # la oferta legítima sigue en pie


def test_record_rejects_approval_when_version_is_older_than_offered() -> None:
    """Principio 1: solo se aprueba la última versión ofrecida, no una anterior."""
    ledger = ApprovalLedger()
    v1 = _artifact()
    ledger.offer(v1, TARGET)
    v2 = _next(v1, "Versión 2 ficticia")
    ledger.offer(v2, TARGET)
    with pytest.raises(ApprovalError, match="no corresponde"):
        ledger.record(v1, TARGET)
    assert ledger.record(v2, TARGET).version == 2


def test_record_rejects_approval_when_content_tampered_with_same_version() -> None:
    """Principio 1: misma versión con contenido alterado tras la oferta → rechazo."""
    ledger = ApprovalLedger()
    artifact = _artifact()
    ledger.offer(artifact, TARGET)
    tampered = artifact.model_copy(
        update={"content": artifact.content.model_copy(update={"title": "Manipulado"})}
    )
    with pytest.raises(ApprovalError):
        ledger.record(tampered, TARGET)


def test_record_rejects_approval_when_nothing_offered_for_artifact() -> None:
    """Principio 1 (error): sin oferta previa no hay aprobación posible."""
    with pytest.raises(ApprovalError):
        ApprovalLedger().record(_artifact(), TARGET)


def test_offer_rejects_project_change_when_iterating() -> None:
    """T-50: el proyecto aprobado no cambia entre iteraciones (destino fijo)."""
    ledger = ApprovalLedger()
    artifact = _artifact()
    ledger.offer(artifact, TARGET)
    with pytest.raises(ApprovalError, match="destino"):
        ledger.offer(_next(artifact, "Iterada"), replace(TARGET, project_key="OTRO"))


def test_find_returns_none_when_project_differs() -> None:
    """T-50: lo aprobado es lo publicado, también el proyecto."""
    ledger = ApprovalLedger()
    artifact = _artifact()
    _approved(ledger, artifact)
    assert ledger.find(artifact, replace(TARGET, project_key="OTRO")) is None
    assert ledger.find(artifact, TARGET) is not None


def test_find_ignores_status_when_artifact_state_is_altered() -> None:
    """Anexo §11: decir `APPROVED` en el estado no basta; sin registro no hay aprobación."""
    ledger = ApprovalLedger()
    artifact = _artifact(status=S.APPROVED)
    ledger.offer(artifact, TARGET)
    assert ledger.find(artifact, TARGET) is None


def test_was_published_is_false_when_only_approved_or_simulated() -> None:
    """Anexo §11: `memorize` exige publicación registrada; aprobar no es publicar."""
    ledger = ApprovalLedger()
    artifact = _artifact()
    _approved(ledger, artifact)
    assert not ledger.was_published(artifact)


def test_reoffer_after_publish_cannot_reapprove_when_version_consumed_after_restart() -> None:
    """Un solo uso: tras consumir y reiniciar, la misma versión no se reaprueba."""
    store = InMemoryArtifactStateStore()
    ledger = ApprovalLedger(store=store)
    artifact = _artifact()
    ledger.consume(_approved(ledger, artifact), artifact)
    fresh = ApprovalLedger(store=store)
    fresh.offer(artifact, TARGET)
    with pytest.raises(ApprovalError, match="ya se publicó"):
        fresh.record(artifact, TARGET)
    assert fresh.find(artifact, TARGET) is None


def test_ledger_keeps_only_latest_pending_approval_when_many_iterations() -> None:
    """Límite de tamaño: 60 iteraciones aprobadas sin publicar dejan una sola pendiente."""
    store = InMemoryArtifactStateStore()
    ledger = ApprovalLedger(store=store)
    artifact = _artifact()
    for n in range(60):
        _approved(ledger, artifact)
        artifact = _next(artifact, f"Iteración {n} ficticia")
    ledger.offer(artifact, TARGET)
    approvals = _stored_ledger(store, artifact)["approvals"]
    assert approvals == []  # la última oferta descarta todas las pendientes anteriores
    assert ledger.record(artifact, TARGET).version == 61


def test_persisted_ledger_contains_only_references_when_saved() -> None:
    """RF-35 / anexo §11: el registro guarda huellas y operación, nunca el contenido."""
    store = InMemoryArtifactStateStore()
    ledger = ApprovalLedger(store=store)
    artifact = _artifact()
    _approved(ledger, artifact)
    serialized = repr(store.load(str(artifact.id)))
    assert artifact.content.title not in serialized
    assert artifact.content.acceptance_criteria[0].then[0] not in serialized


# --- Registro dañado o manipulado: falla cerrado con ApprovalError -----------------------


def _seed_valid(store: InMemoryArtifactStateStore, artifact: Artifact) -> dict[str, Any]:
    _approved(ApprovalLedger(store=store), artifact)
    state = store.load(str(artifact.id))
    assert state is not None
    return state


@pytest.mark.parametrize(
    "damage",
    [
        pytest.param(lambda lg: lg["target"].pop("project_key"), id="target-sin-project_key"),
        pytest.param(lambda lg: lg["target"].update(extra="x"), id="target-campo-extra"),
        pytest.param(lambda lg: lg.update(target="texto"), id="target-no-dict"),
        pytest.param(lambda lg: lg.update(approvals=None), id="approvals-null"),
        pytest.param(lambda lg: lg.update(approvals=["texto"]), id="approval-no-dict"),
        pytest.param(lambda lg: lg["approvals"][0].pop("fingerprint"), id="sin-fingerprint"),
        pytest.param(lambda lg: lg["approvals"][0].update(version="uno"), id="version-texto"),
        pytest.param(lambda lg: lg["approvals"][0].update(at="ayer"), id="fecha-invalida"),
        pytest.param(lambda lg: lg["approvals"][0].update(at=12345), id="fecha-numero"),
        pytest.param(
            lambda lg: lg["approvals"][0]["target"].pop("project_key"),
            id="approval-target-sin-project_key",
        ),
    ],
)
def test_ledger_fails_closed_when_stored_ledger_is_damaged(damage: Any) -> None:
    """Anexo §11: un registro dañado falla cerrado (`ApprovalError`) y no se sobrescribe."""
    store = InMemoryArtifactStateStore()
    artifact = _artifact()
    state = _seed_valid(store, artifact)
    damage(state["ledger"])
    store.save(str(artifact.id), state)
    before = repr(store.load(str(artifact.id)))

    ledger = ApprovalLedger(store=store)
    with pytest.raises(ApprovalError, match="dañado"):
        ledger.find(artifact, TARGET)
    with pytest.raises(ApprovalError, match="dañado"):
        ledger.offer(artifact, TARGET)  # sigue fallando: no se marca como cargado
    assert repr(store.load(str(artifact.id))) == before


def test_ledger_ignores_foreign_approval_when_artifact_id_differs() -> None:
    """Manipulación: una aprobación de otro artefacto copiada en el registro no concede nada."""
    store = InMemoryArtifactStateStore()
    victim = _artifact()
    donor = _artifact()
    donor_state = _seed_valid(store, donor)
    store.save(str(victim.id), {"ledger": donor_state["ledger"]})
    assert not _vigente(ApprovalLedger(store=store), victim)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-171): un ledger o estado que no es un dict (texto, lista, número) "
        "lanza AttributeError en vez de ApprovalError (core/approvals.py:176-181)"
    ),
)
@pytest.mark.parametrize("raw_ledger", ["texto-corrupto", ["DEMO"], 42, True])
def test_ledger_raises_approval_error_when_ledger_is_not_a_dict(raw_ledger: Any) -> None:
    """Anexo §11: JSON del registro con tipo inesperado → `ApprovalError` (fallo cerrado)."""
    store = InMemoryArtifactStateStore()
    artifact = _artifact()
    store.save(str(artifact.id), {"ledger": raw_ledger})
    with pytest.raises(ApprovalError):
        ApprovalLedger(store=store).find(artifact, TARGET)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-171): un estado JSONB que no es objeto (texto, lista) lanza "
        "AttributeError en vez de ApprovalError (core/approvals.py:176)"
    ),
)
@pytest.mark.parametrize("raw_state", ['"texto"', ["ledger"]])
def test_ledger_raises_approval_error_when_state_json_is_not_an_object(raw_state: Any) -> None:
    """Anexo §11: `artifact_state.state` corrupto → `ApprovalError` (fallo cerrado)."""
    artifact = _artifact()
    with pytest.raises(ApprovalError):
        ApprovalLedger(store=RawStateStore(raw_state)).find(artifact, TARGET)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-171): SqlArtifactStateStore devuelve el JSONB sin validar y el "
        "ledger lanza AttributeError en vez de ApprovalError (core/approvals.py:176; "
        "core/artifact_state.py:51-58)"
    ),
)
def test_sql_backed_ledger_raises_approval_error_when_jsonb_is_a_string() -> None:
    """Anexo §11: columna `state` con un JSON escalar → `ApprovalError` (sin BD: engine espía)."""
    store = SqlArtifactStateStore(SpyEngine(value="texto-corrupto"))  # type: ignore[arg-type]
    with pytest.raises(ApprovalError):
        ApprovalLedger(store=store).find(_artifact(), TARGET)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-171): un ledger falso pero de tipo erróneo ([], '', 0) se trata como "
        "ausente y la oferta lo sobrescribe sin avisar (core/approvals.py:177, 208-210)"
    ),
)
@pytest.mark.parametrize("raw_ledger", [[], "", 0])
def test_ledger_fails_closed_when_ledger_is_falsy_of_wrong_type(raw_ledger: Any) -> None:
    """Anexo §11: un registro de tipo inesperado falla cerrado y no se sobrescribe."""
    store = RawStateStore()
    artifact = _artifact()
    store.raw[str(artifact.id)] = {"ledger": raw_ledger}
    with pytest.raises(ApprovalError):
        ApprovalLedger(store=store).offer(artifact, TARGET)
    assert store.saved == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-172): una aprobación persistida sin el campo `consumed` se carga como "
        "vigente (falla abierto) y vuelve a permitir publicar (core/approvals.py:226)"
    ),
)
def test_ledger_does_not_grant_approval_when_consumed_flag_is_missing() -> None:
    """Principio 1 · un solo uso: borrar `consumed` del registro no reactiva la aprobación."""
    store = InMemoryArtifactStateStore()
    ledger = ApprovalLedger(store=store)
    artifact = _artifact()
    ledger.consume(_approved(ledger, artifact), artifact)
    state = store.load(str(artifact.id))
    assert state is not None
    state["ledger"]["approvals"][0].pop("consumed")
    store.save(str(artifact.id), state)

    assert not _vigente(ApprovalLedger(store=store), artifact)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-172): con dos entradas de la misma versión (consumida y sin consumir) "
        "gana la última y la aprobación vuelve a estar vigente (core/approvals.py:192-194)"
    ),
)
def test_ledger_does_not_grant_approval_when_version_entry_is_duplicated() -> None:
    """Principio 1 · un solo uso: duplicar la entrada consumida sin `consumed` no reabre nada."""
    store = InMemoryArtifactStateStore()
    ledger = ApprovalLedger(store=store)
    artifact = _artifact()
    ledger.consume(_approved(ledger, artifact), artifact)
    state = store.load(str(artifact.id))
    assert state is not None
    used = state["ledger"]["approvals"][0]
    state["ledger"]["approvals"].append({**used, "consumed": False, "published_fingerprint": None})
    store.save(str(artifact.id), state)

    assert not _vigente(ApprovalLedger(store=store), artifact)


# --- Doble consumo y concurrencia --------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-173): consume() no comprueba que la aprobación siga vigente; un "
        "segundo consumo se acepta y sobrescribe la huella publicada (core/approvals.py:153-159)"
    ),
)
def test_consume_rejects_second_use_when_approval_already_consumed() -> None:
    """Principio 1 · un solo uso: el segundo `consume` de la misma aprobación falla."""
    ledger = ApprovalLedger()
    artifact = _artifact()
    approval = _approved(ledger, artifact)
    ledger.consume(approval, artifact)
    other = artifact.model_copy(
        update={"content": artifact.content.model_copy(update={"title": "Otra publicación"})}
    )
    with pytest.raises(ApprovalError):
        ledger.consume(approval, other)
    assert ledger.was_published(artifact)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-173): consume() acepta una aprobación ya descartada por una oferta "
        "posterior y la reinserta como publicada (core/approvals.py:153-159)"
    ),
)
def test_consume_rejects_stale_approval_when_newer_version_offered() -> None:
    """Principio 1: la aprobación de la v1 invalidada por la oferta de la v2 no se consume."""
    ledger = ApprovalLedger()
    v1 = _artifact()
    stale = _approved(ledger, v1)
    ledger.offer(_next(v1, "Versión 2 ficticia"), TARGET)
    with pytest.raises(ApprovalError):
        ledger.consume(stale, v1)
    assert not ledger.was_published(v1)


def test_find_returns_none_when_same_instance_consumed_before() -> None:
    """Un solo uso (positivo): en la misma instancia, tras consumir no hay aprobación."""
    ledger = ApprovalLedger()
    artifact = _artifact()
    first = _approved(ledger, artifact)
    assert ledger.find(artifact, TARGET) == first
    ledger.consume(first, artifact)
    assert ledger.find(artifact, TARGET) is None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-174): el ledger carga el almacén una sola vez (_loaded) y nunca lo "
        "relee; otra instancia sobre el mismo almacén sigue viendo vigente una aprobación ya "
        "consumida (core/approvals.py:172-195)"
    ),
)
def test_find_returns_none_in_second_instance_when_first_consumed() -> None:
    """Concurrencia: dos procesos sobre el mismo `artifact_state` no publican dos veces."""
    store = InMemoryArtifactStateStore()
    first = ApprovalLedger(store=store)
    artifact = _artifact()
    _approved(first, artifact)
    second = ApprovalLedger(store=store)
    assert second.find(artifact, TARGET) is not None  # ambos ven la aprobación
    first.consume(first.find(artifact, TARGET), artifact)  # type: ignore[arg-type]
    assert second.find(artifact, TARGET) is None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-174): _persist escribe la caché local completa; una instancia con "
        "caché antigua borra la marca de publicación guardada por otra (pérdida de "
        "actualización, core/approvals.py:197-210)"
    ),
)
def test_consumed_mark_survives_when_stale_instance_persists_later() -> None:
    """Concurrencia: la publicación registrada no se pierde por otra instancia desfasada."""
    store = InMemoryArtifactStateStore()
    first = ApprovalLedger(store=store)
    artifact = _artifact()
    _approved(first, artifact)
    stale = ApprovalLedger(store=store)
    stale.find(artifact, TARGET)  # carga la caché antes de la publicación
    first.consume(first.find(artifact, TARGET), artifact)  # type: ignore[arg-type]
    stale.offer(_next(artifact, "Iterada desde otra pestaña"), TARGET)
    assert ApprovalLedger(store=store).was_published(artifact)


# --- Destino fijo y ofertas rechazadas ---------------------------------------------------


def test_rejected_offer_is_not_persisted_when_origin_mismatch() -> None:
    """Anexo §11: una oferta rechazada no deja rastro en el almacén."""
    store = InMemoryArtifactStateStore()
    artifact = _artifact()
    with pytest.raises(ApprovalError):
        ApprovalLedger(store=store).offer(artifact, replace(TARGET, origin_key="DEMO-9"))
    assert store.load(str(artifact.id)) is None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-175): offer() fija el destino con setdefault antes de validar; una "
        "oferta rechazada deja fijado el destino erróneo y bloquea la oferta correcta "
        "(core/approvals.py:102-104)"
    ),
)
def test_valid_offer_succeeds_when_previous_offer_was_rejected() -> None:
    """Anexo §11: el destino queda fijado en la primera oferta *aceptada*, no en una rechazada."""
    ledger = ApprovalLedger()
    artifact = _artifact()
    with pytest.raises(ApprovalError):
        ledger.offer(artifact, replace(TARGET, origin_key="DEMO-9"))
    assert len(ledger.offer(artifact, TARGET)) == 64
    assert ledger.is_offered(artifact, TARGET)


# --- Máquina de estados (RF-34, CA-00-07) ------------------------------------------------


def test_can_transition_accepts_str_enum_values_when_valid() -> None:
    """RF-34: los valores `StrEnum` equivalen a sus cadenas en la tabla de transiciones."""
    assert can_transition(S("draft"), S("in_review"))
    assert not can_transition(S("approved"), S("draft"))


def test_transition_from_approved_only_to_published_when_any_target() -> None:
    """CA-00-07: un artefacto aprobado no vuelve a borrador, revisión ni se descarta."""
    approved = _artifact(status=S.APPROVED)
    for target in (S.DRAFT, S.IN_REVIEW, S.DISCARDED, S.APPROVED):
        with pytest.raises(InvalidTransitionError):
            transition(approved, target)
    assert transition(approved, S.PUBLISHED).status is S.PUBLISHED


def test_transition_error_message_is_spanish_when_rejected() -> None:
    """Convención: mensaje en español con los dos estados, para la UI."""
    with pytest.raises(InvalidTransitionError, match="No se puede pasar") as info:
        ensure_transition(S.PUBLISHED, S.DRAFT)
    assert (info.value.current, info.value.target) == ("published", "draft")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-176): con estados que no son ArtifactStatus (cadena, None) la máquina "
        "lanza KeyError/AttributeError en vez de InvalidTransitionError "
        "(core/state_machine.py:30-36)"
    ),
)
@pytest.mark.parametrize(
    ("current", "target"),
    [("bogus", S.DRAFT), ("draft", "published"), (S.DRAFT, "bogus"), (S.DRAFT, None)],
)
def test_ensure_transition_raises_invalid_transition_when_types_unexpected(
    current: Any, target: Any
) -> None:
    """CA-00-07 (tipos inesperados): siempre `InvalidTransitionError`, nunca otro error."""
    with pytest.raises(InvalidTransitionError):
        ensure_transition(current, target)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-176): transition() copia el destino sin validarlo; con una cadena "
        "el artefacto queda con status str en vez de ArtifactStatus (core/state_machine.py:39-42)"
    ),
)
def test_transition_keeps_enum_status_when_target_given_as_string() -> None:
    """RF-34: el estado resultante es siempre un `ArtifactStatus`."""
    result = transition(_artifact(status=S.IN_REVIEW), "approved")  # type: ignore[arg-type]
    assert isinstance(result.status, ArtifactStatus)


# --- Auditoría (RF-35) -------------------------------------------------------------------


def _entry(**update: Any) -> AuditEntry:
    data: dict[str, Any] = {
        "artifact_id": uuid4(),
        "action": "approve",
        "user": USER,
        "jira_keys": [ORIGIN],
        "model": "modelo-ficticio:7b",
        "detail": {"version": 2, "fingerprint": "f" * 64, "operation": "actualizar HU"},
    }
    data.update(update)
    return AuditEntry(**data)


def test_audit_entry_drops_unknown_fields_when_prompt_or_content_passed() -> None:
    """RF-35 · anexo §11: campos ajenos (prompt, contenido) no llegan a la entrada."""
    entry = _entry(prompt="Eres un analista ficticio…", content={"title": "HU ficticia"})
    dumped = entry.model_dump()
    assert "prompt" not in dumped
    assert "content" not in dumped


@pytest.mark.parametrize(
    "update",
    [{"jira_keys": "DEMO-3"}, {"detail": ["no", "es", "dict"]}, {"artifact_id": "no-uuid"}],
)
def test_audit_entry_rejects_wrong_types_when_built(update: dict[str, Any]) -> None:
    """RF-35 (tipos inesperados): claves como lista, detalle como objeto, id como UUID."""
    with pytest.raises(ValueError):
        _entry(**update)


def test_sql_trail_inserts_only_entry_fields_when_recording() -> None:
    """RF-35: el INSERT lleva usuario, acción, claves, modelo y metadatos; la fecha, la BD."""
    engine = SpyEngine()
    entry = _entry()
    SqlAuditTrail(engine).record(entry)  # type: ignore[arg-type]
    (statement,) = engine.statements
    params = _params(statement)
    assert set(params) == {"artifact_id", "action", "user", "jira_keys", "model", "detail"}
    assert params["artifact_id"] == entry.artifact_id
    assert params["jira_keys"] == [ORIGIN]
    assert params["detail"] == entry.detail


def test_sql_trail_returns_entries_when_rows_come_back() -> None:
    """RF-35: lo leído de `audit_log` se valida como `AuditEntry` y conserva el orden."""
    artifact_id = uuid4()
    rows = [
        {
            "artifact_id": artifact_id,
            "action": action,
            "user": USER,
            "jira_keys": [ORIGIN],
            "model": None,
            "detail": {"version": n},
        }
        for n, action in enumerate(["create", "approve", "publish"], start=1)
    ]
    entries = SqlAuditTrail(SpyEngine(value=rows)).entries(artifact_id)  # type: ignore[arg-type]
    assert [e.action for e in entries] == ["create", "approve", "publish"]
    assert all(e.artifact_id == artifact_id for e in entries)


def test_sql_trail_raises_validation_error_when_row_action_is_manipulated() -> None:
    """RF-35 (manipulación): una acción fuera del catálogo leída de la BD no se acepta."""
    row = {
        "artifact_id": uuid4(),
        "action": "delete",
        "user": USER,
        "jira_keys": [],
        "model": None,
        "detail": {},
    }
    with pytest.raises(ValueError):
        SqlAuditTrail(SpyEngine(value=[row])).entries(row["artifact_id"])  # type: ignore[arg-type]


def test_in_memory_trail_returns_empty_when_artifact_unknown() -> None:
    """RF-35 (límite): sin entradas para el artefacto → lista vacía."""
    trail = InMemoryAuditTrail()
    trail.record(_entry())
    assert trail.entries(uuid4()) == []


# --- artifact_state (anexo §11 «Versión de partida», persistencia) -----------------------


def test_in_memory_store_is_not_changed_when_saved_dict_is_mutated_later() -> None:
    """Persistencia: mutar el dict pasado a `save` no cambia lo guardado."""
    store = InMemoryArtifactStateStore()
    artifact_id = str(uuid4())
    state: dict[str, Any] = {"baseline": {"title": "HU ficticia"}}
    store.save(artifact_id, state)
    state["ledger"] = {"offer": "x"}
    assert store.load(artifact_id) == {"baseline": {"title": "HU ficticia"}}


def test_sql_store_builds_upsert_when_saving() -> None:
    """Persistencia: `save` es un upsert por `artifact_id` con el estado completo."""
    engine = SpyEngine()
    artifact_id = str(uuid4())
    SqlArtifactStateStore(engine).save(artifact_id, {"ledger": None})  # type: ignore[arg-type]
    (statement,) = engine.statements
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (artifact_id) DO UPDATE" in sql
    assert _params(statement)["artifact_id"] == UUID(artifact_id)


def test_sql_store_rejects_non_uuid_id_when_loading() -> None:
    """Tipos inesperados: un id que no es UUID se rechaza antes de tocar la BD."""
    engine = SpyEngine()
    with pytest.raises(ValueError):
        SqlArtifactStateStore(engine).load("no-es-un-uuid")  # type: ignore[arg-type]
    assert engine.statements == []


def test_ledger_keeps_baseline_key_when_persisting() -> None:
    """Versión de partida: el ledger escribe su clave sin tocar `baseline`."""
    store = InMemoryArtifactStateStore()
    artifact = _artifact()
    store.save(str(artifact.id), {"baseline": {"title": "HU de partida ficticia"}})
    _approved(ApprovalLedger(store=store), artifact)
    state = store.load(str(artifact.id))
    assert state is not None
    assert state["baseline"] == {"title": "HU de partida ficticia"}
    assert asdict(TARGET) == state["ledger"]["target"]


# --- Integración con PostgreSQL ------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine() -> Iterator[Engine]:
    with temporary_database("cross_a_approvals") as (_url, engine):
        yield engine


@pytest.mark.integration
@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-171): un JSONB escalar en artifact_state.state hace que el ledger "
        "lance AttributeError en vez de ApprovalError (core/approvals.py:176)"
    ),
)
def test_sql_ledger_fails_closed_when_jsonb_state_is_scalar(pg_engine: Engine) -> None:
    """Anexo §11 (BD real): estado corrupto en PostgreSQL → `ApprovalError`."""
    artifact = _artifact()
    with pg_engine.begin() as conn:
        conn.execute(
            sa.insert(ARTIFACT_STATE).values(artifact_id=artifact.id, state="texto-corrupto")
        )
    ledger = ApprovalLedger(store=SqlArtifactStateStore(pg_engine))
    with pytest.raises(ApprovalError):
        ledger.find(artifact, TARGET)
