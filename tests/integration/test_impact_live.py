"""Análisis de impacto con un LLM real sobre el seed de Villaficticia (T-21: RF-19, RF-27, RNF-14).

El contexto de Jira se construye en memoria a partir de `data/seed/jira/seed-villaficticia.csv`
(claves ficticias `SEED-<Issue ID>`): no se lee ni se escribe en Jira. Se evoluciona HU-02
(renovar un préstamo) con un cambio que afecta a las reservas y se comprueba que las HU
afectadas son claves del contexto. Se salta si no hay proveedor LLM utilizable para
`analyze_impact`. Consume cuota del proveedor: ejecútala solo a propósito (`-m integration`).
"""

import csv
from pathlib import Path

import httpx
import pytest

from adapters.base import IssueDetail, IssueLink, TaskType
from core.config import AppConfig, build_config
from core.factories import build_llm_provider
from core.impact.analysis import ImpactAnalyzer, candidates
from core.impact.diff import diff_stories
from schemas.user_story import BusinessRule
from tests.fakes.dataset import renewal_story

pytestmark = pytest.mark.integration

TASK = TaskType.ANALYZE_IMPACT
CSV_PATH = Path(__file__).resolve().parents[2] / "data" / "seed" / "jira" / "seed-villaficticia.csv"
PREFIX = "SEED"
RENEWAL_ID = "3"  # [HU-02] Renovar un préstamo


def _local_reachable(config: AppConfig, provider: str) -> bool:
    try:
        httpx.get(f"{config.base_url_for(provider)}/models", timeout=2.0)
    except httpx.HTTPError:
        return False
    return True


@pytest.fixture
def live_config() -> AppConfig:
    config = build_config()
    usable = [
        ref
        for ref in config.task_chain(TASK)  # solo proveedores con clave o locales
        if "POR_DEFINIR" not in ref.model
        and (
            config.api_key_for(ref.provider) is not None
            or (
                config.models.providers[ref.provider].api_key_env is None
                and _local_reachable(config, ref.provider)
            )
        )
    ]
    if not usable:
        pytest.skip(f"No hay ningún proveedor LLM utilizable para '{TASK.value}'.")
    return config


def _seed_issues() -> dict[str, IssueDetail]:
    with CSV_PATH.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    header, body = rows[0], rows[1:]
    col = {name: header.index(name) for name in ("Issue ID", "Parent", "Issue Type", "Summary")}
    description, relates = header.index("Description"), header.index('Link "Relates"')
    issues: dict[str, IssueDetail] = {}
    for row in body:
        issue_id = row[col["Issue ID"]]
        parent = row[col["Parent"]]
        links = [
            IssueLink(link_type="relates to", key=f"{PREFIX}-{ref.strip()}")
            for ref in row[relates].split(",")
            if ref.strip()
        ]
        issues[issue_id] = IssueDetail(
            key=f"{PREFIX}-{issue_id}",
            summary=row[col["Summary"]],
            issue_type=row[col["Issue Type"]],
            status="Por hacer",
            description_text=row[description],
            parent_key=f"{PREFIX}-{parent}" if parent else None,
            links=links,
        )
    return issues


def _renewal_context() -> list[IssueDetail]:
    """HU-02 primero, luego su épica, sus vínculos y sus hermanas (como hace T-18)."""
    issues = _seed_issues()
    origin = issues[RENEWAL_ID]
    by_key = {i.key: i for i in issues.values()}
    context = [origin]
    if origin.parent_key:
        context.append(by_key[origin.parent_key])
    context += [by_key[link.key] for link in origin.links if link.key in by_key]
    context += [i for i in issues.values() if i.parent_key == origin.parent_key]
    return list({issue.key: issue for issue in context}.values())


def test_impact_affected_keys_come_from_context_when_live(live_config: AppConfig) -> None:
    """RF-19 · RF-27 · RNF-14: evolución real de HU-02; afectadas solo entre las candidatas."""
    jira = _renewal_context()
    origin_key = jira[0].key
    allowed = {issue.key for issue in candidates(jira, origin_key)}
    baseline = renewal_story(jira_key=origin_key)
    rules = [
        BusinessRule(id="RN-01", description="Máximo 2 renovaciones por préstamo."),
        BusinessRule(
            id="RN-02",
            description=(
                "Una renovación cancela las reservas pendientes del ejemplar y avisa a las "
                "personas socias que lo habían reservado (regla ficticia)."
            ),
        ),
    ]
    evolved = baseline.model_copy(update={"business_rules": rules})

    result = ImpactAnalyzer(build_llm_provider(live_config)).analyze(
        evolved, jira, baseline=baseline, origin_key=origin_key
    )

    assert result.diffs == diff_stories(baseline, evolved)
    assert {i.jira_key for i in result.affected} <= allowed
    assert origin_key not in {i.jira_key for i in result.affected}
    assert all(i.reason.strip() for i in result.affected)
    assert all(note.strip() for note in result.regression_notes)
