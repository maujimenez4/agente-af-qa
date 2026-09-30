"""Protocolos de los adaptadores y tipos auxiliares (SPEC-00 §4)."""

from enum import StrEnum


class TaskType(StrEnum):
    """Tipos de tarea del LLM; sus valores coinciden con las claves de `config/models.yaml`."""

    GENERATE_STORY = "generate_story"
    EVOLVE_STORY = "evolve_story"
    REVIEW_STORY = "review_story"
    ANALYZE_IMPACT = "analyze_impact"
    GENERATE_TESTS = "generate_tests"
    SYNTHESIZE_MEMORY = "synthesize_memory"
    CLASSIFY_SOURCE = "classify_source"
    NL_TO_JQL = "nl_to_jql"
