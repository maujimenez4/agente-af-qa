"""Fake de LLMProvider: respuestas estructuradas deterministas a partir del dataset sintético."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from adapters.base import LLMResult, Message, StructuredResult, TaskType
from schemas.common import Priority, SourceRef
from schemas.impact import ImpactAnalysis, ImpactItem, StoryDiff
from schemas.memory import Memory
from schemas.quality import InvestCheck, QualityFinding, QualityReport
from schemas.test_case import TestCase, TestCaseType, TestStep, TestSuite
from schemas.user_story import UserStory
from tests.fakes import dataset

Builder = Callable[[list[Message]], BaseModel]


def renewal_test_suite(story_key: str = "DEMO-3") -> TestSuite:
    """Suite sintética que cubre los CA y RN de `dataset.renewal_story()`."""
    return TestSuite(
        story_jira_key=story_key,
        cases=[
            TestCase(
                internal_id="CP-01",
                title="Renovar un préstamo sin reservas",
                criterion_ids=["CA-01"],
                rule_ids=["RN-01"],
                type=TestCaseType.POSITIVE,
                preconditions=["Préstamo activo con 0 renovaciones"],
                steps=[TestStep(action="Pulsar «Renovar»", expected="Vencimiento +21 días")],
                priority=Priority.MUST,
            ),
            TestCase(
                internal_id="CP-02",
                title="Rechazar la renovación con reservas pendientes",
                criterion_ids=["CA-02"],
                rule_ids=["RN-02"],
                type=TestCaseType.NEGATIVE,
                preconditions=["Préstamo activo con una reserva pendiente"],
                steps=[TestStep(action="Pulsar «Renovar»", expected="Aviso de reservas")],
                priority=Priority.MUST,
            ),
        ],
        strategy_md="# Estrategia (ficticia)\n\nPruebas funcionales manuales sobre la web.",
    )


_SOURCE_TAG = re.compile(r'<fuente ref="([^"]+)" tipo="(jira|rag|memory)"')


def _story_citing_context(messages: list[Message]) -> UserStory:
    """HU del dataset que cita la primera fuente recibida (si el contexto trae fuentes)."""
    story = dataset.renewal_story(jira_key=None)
    for message in messages:
        # Solo el contexto (mensajes de usuario); el prompt de sistema trae ejemplos de etiquetas.
        if message.role == "user" and (match := _SOURCE_TAG.search(message.content)):
            ref, kind = match.group(1), match.group(2)
            return story.model_copy(update={"sources": [SourceRef(kind=kind, ref=ref)]})
    return story


def _suite_citing_context(messages: list[Message]) -> TestSuite:
    """Suite del dataset que cita la primera fuente recibida, como `_story_citing_context`."""
    suite = renewal_test_suite()
    for message in messages:
        if message.role == "user" and (match := _SOURCE_TAG.search(message.content)):
            ref, kind = match.group(1), match.group(2)
            return suite.model_copy(update={"sources": [SourceRef(kind=kind, ref=ref)]})
    return suite


def renewal_quality_report() -> QualityReport:
    """Informe de calidad sintético sobre `dataset.renewal_story()` (T-48)."""
    return QualityReport(
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
    )


def _quality_citing_context(messages: list[Message]) -> QualityReport:
    report = renewal_quality_report()
    for message in messages:
        if message.role == "user" and (match := _SOURCE_TAG.search(message.content)):
            ref, kind = match.group(1), match.group(2)
            return report.model_copy(update={"sources": [SourceRef(kind=kind, ref=ref)]})
    return report


def _default_builders() -> dict[type[BaseModel], Builder]:
    return {
        UserStory: _story_citing_context,
        TestSuite: _suite_citing_context,
        QualityReport: _quality_citing_context,
        ImpactAnalysis: lambda _messages: ImpactAnalysis(
            diffs=[StoryDiff(field="title", before="Renovar", after="Renovar un préstamo")],
            affected=[
                ImpactItem(jira_key="DEMO-2", reason="Comparte la RN de reservas", kind="rule")
            ],
            regression_notes=["Revisar el flujo de reservas."],
        ),
        Memory: lambda _messages: Memory(
            artifact_type="user_story",
            jira_key="DEMO-3",
            version=1,
            objective="Renovar préstamos desde la web.",
            scope="Renovación desde la ficha del préstamo.",
            business_rules=["RN-01", "RN-02"],
            decisions=[],
            dependencies=["DEMO-2"],
            changes=[],
            acceptance_criteria=["CA-01", "CA-02"],
            references=["doc-reglamento"],
        ),
    }


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class FakeLLMProvider:
    """Registra cada llamada en `calls`. `builders` permite sustituir la respuesta por esquema."""

    provider: str = "fake"
    model: str = "fake-model"
    builders: dict[type[BaseModel], Builder] = field(default_factory=_default_builders)
    error: Exception | None = None  # si se fija, cada llamada lo lanza (p. ej. RateLimitError)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def _usage(self, messages: list[Message], output: str) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "input_tokens": sum(_tokens(m.content) for m in messages),
            "output_tokens": _tokens(output),
            "latency_ms": 1,
        }

    def generate(self, messages: list[Message], task: TaskType) -> LLMResult:
        self.calls.append({"task": task, "schema": None, "messages": list(messages)})
        if self.error:
            raise self.error
        content = f"Respuesta ficticia para {task.value}."
        return LLMResult(content=content, **self._usage(messages, content))

    def generate_structured[T: BaseModel](
        self, messages: list[Message], schema: type[T], task: TaskType
    ) -> StructuredResult[T]:
        self.calls.append({"task": task, "schema": schema, "messages": list(messages)})
        if self.error:
            raise self.error
        try:
            builder = self.builders[schema]
        except KeyError:
            raise NotImplementedError(
                f"FakeLLMProvider sin respuesta para {schema.__name__}"
            ) from None
        # Se valida con el esquema pedido, como hará el proveedor real (RNF-28).
        content = schema.model_validate(builder(messages).model_dump())
        return StructuredResult[schema](
            content=content, **self._usage(messages, content.model_dump_json())
        )
