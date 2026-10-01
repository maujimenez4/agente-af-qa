"""Medición de RNF-11: la memoria .md reduce los tokens ≥ 60 % frente al artefacto (T-33).

Se compara la HU completa, tal como entra en el contexto del LLM (JSON, igual que
`core.functional.context.render_context`), con su memoria `Memory.to_markdown()`. Los tokens se
estiman con `core.context.budget.estimate_tokens`. Solo lectura: no escribe archivos, no indexa y
no llama a Jira.

- `--mode fake` (por defecto): HU del dataset de los fakes con `FakeMemoryGenerator`, sin LLM.
- `--mode real`: además, las HU del seed (`data/seed/jira/`), estructuradas con `StoryWriter` y
  resumidas con `LLMMemoryGenerator`, con los modelos de `config/models.yaml`. Llama al LLM:
  ejecútalo solo con el seed ficticio y con permiso (modelos locales lentos en CPU).

Uso: `uv run python -m eval.memory_tokens [--mode fake|real] [--limit N]`.
"""

import argparse
import csv
import json
from collections.abc import Iterable
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from adapters.base import IssueDetail, MemoryGenerator
from core.config import ROOT_DIR
from core.context.budget import estimate_tokens
from core.functional.context import StoryContext
from core.functional.writer import StoryWriter
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType, SourceRef
from schemas.user_story import UserStory

REDUCTION_TARGET = 0.60  # RNF-11
SEED_CSV = ROOT_DIR / "data" / "seed" / "jira" / "seed-villaficticia.csv"
SEED_KEY_PREFIX = "VF"  # claves ficticias: Jira asigna las reales al importar


class TokenRow(BaseModel):
    key: str
    origin: str  # «dataset» o «seed»
    artifact_tokens: int
    memory_tokens: int

    @property
    def reduction(self) -> float:
        return 1 - self.memory_tokens / self.artifact_tokens if self.artifact_tokens else 0.0

    @property
    def meets_target(self) -> bool:
        return self.reduction >= REDUCTION_TARGET


class TokenReport(BaseModel):
    rows: list[TokenRow]

    @property
    def total_reduction(self) -> float:
        before = sum(r.artifact_tokens for r in self.rows)
        after = sum(r.memory_tokens for r in self.rows)
        return 1 - after / before if before else 0.0

    @property
    def meets_target(self) -> bool:
        return bool(self.rows) and self.total_reduction >= REDUCTION_TARGET


def artifact_text(artifact: Artifact) -> str:
    """El artefacto como lo recibe el LLM en el contexto."""
    return json.dumps(artifact.content.model_dump(mode="json"), ensure_ascii=False)


def measure(artifact: Artifact, generator: MemoryGenerator, origin: str) -> TokenRow:
    memory = generator.generate(artifact)
    return TokenRow(
        key=memory.jira_key,
        origin=origin,
        artifact_tokens=estimate_tokens(artifact_text(artifact)),
        memory_tokens=estimate_tokens(memory.to_markdown()),
    )


def build_report(
    artifacts: Iterable[tuple[Artifact, str]], generator: MemoryGenerator
) -> TokenReport:
    return TokenReport(rows=[measure(a, generator, origin) for a, origin in artifacts])


def published_story(story: UserStory, key: str) -> Artifact:
    return Artifact(
        id=uuid4(),
        type=ArtifactType.USER_STORY,
        status=ArtifactStatus.PUBLISHED,
        version=1,
        origin_key=key,
        content=story.model_copy(update={"jira_key": key}),
        created_by="eval",
    )


def dataset_artifacts() -> list[tuple[Artifact, str]]:
    """HU estructuradas del dataset de los fakes (solo en pruebas y evaluación)."""
    from tests.fakes import dataset

    story = dataset.renewal_story().model_copy(
        update={"sources": [SourceRef(kind="rag", ref=ref) for ref in dataset.DOCUMENTS]}
    )
    return [(published_story(story, story.jira_key or "DEMO-3"), "dataset")]


def seed_issues(path: Path = SEED_CSV) -> list[IssueDetail]:
    """HU (no épicas) del CSV del seed como incidencias de Jira, sin llamar a Jira."""
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    header, body = rows[0], rows[1:]
    column = {name: header.index(name) for name in ("Issue ID", "Parent", "Issue Type")}
    column |= {name: header.index(name) for name in ("Summary", "Description")}
    issues: list[IssueDetail] = []
    for row in body:
        if row[column["Issue Type"]] != "Story":
            continue
        parent = row[column["Parent"]]
        issues.append(
            IssueDetail(
                key=f"{SEED_KEY_PREFIX}-{row[column['Issue ID']]}",
                summary=row[column["Summary"]],
                issue_type="Story",
                status="Por hacer",
                description_text=row[column["Description"]],
                parent_key=f"{SEED_KEY_PREFIX}-{parent}" if parent else None,
            )
        )
    return issues


def seed_artifacts(writer: StoryWriter, issues: list[IssueDetail]) -> list[tuple[Artifact, str]]:
    """Cada incidencia del seed pasada a la plantilla de HU con el LLM (`structure_story`)."""
    artifacts: list[tuple[Artifact, str]] = []
    for issue in issues:
        ctx = StoryContext(origin_kind="story", origin_key=issue.key, jira=[issue])
        artifacts.append((published_story(writer.structure(ctx).story, issue.key), "seed"))
    return artifacts


def format_report(report: TokenReport) -> str:
    lines = [
        "| Clave | Origen | Tokens HU | Tokens memoria | Reducción | ≥ 60 % |",
        "|---|---|---:|---:|---:|---|",
    ]
    for r in report.rows:
        mark = "sí" if r.meets_target else "no"
        lines.append(
            f"| {r.key} | {r.origin} | {r.artifact_tokens} | {r.memory_tokens} "
            f"| {r.reduction:.0%} | {mark} |"
        )
    verdict = "CUMPLE" if report.meets_target else "NO CUMPLE"
    lines += ["", f"Reducción total: {report.total_reduction:.0%} · RNF-11 {verdict}", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import sys

    parser = argparse.ArgumentParser(prog="python -m eval.memory_tokens", description=__doc__)
    parser.add_argument("--mode", choices=("fake", "real"), default="fake")
    parser.add_argument("--limit", type=int, default=None, help="máximo de HU del seed (real)")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit debe ser un entero positivo")

    if args.mode == "fake":
        from tests.fakes.memory_generator import FakeMemoryGenerator

        report = build_report(dataset_artifacts(), FakeMemoryGenerator())
    else:
        from core.config import build_config
        from core.factories import build_llm_provider
        from core.memory.generator import LLMMemoryGenerator

        llm = build_llm_provider(build_config())
        issues = seed_issues()[: args.limit]
        artifacts = [*dataset_artifacts(), *seed_artifacts(StoryWriter(llm), issues)]
        report = build_report(artifacts, LLMMemoryGenerator(llm))
    sys.stdout.reconfigure(encoding="utf-8")  # consolas de Windows en cp1252
    sys.stdout.write(format_report(report))
    return 0 if report.meets_target else 1


if __name__ == "__main__":
    raise SystemExit(main())
