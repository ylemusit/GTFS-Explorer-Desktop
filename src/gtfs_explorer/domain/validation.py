"""Contrato estable de reglas y problemas de validación."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class ValidationSeverity(StrEnum):
    FATAL = "FATAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    NOTICE = "NOTICE"


class ValidationCategory(StrEnum):
    CONTAINER = "CONTAINER"
    SCHEMA = "SCHEMA"
    FIELD = "FIELD"
    REFERENCE = "REFERENCE"
    TIMETABLE = "TIMETABLE"
    CALENDAR = "CALENDAR"
    GEOMETRY = "GEOMETRY"
    BEST_PRACTICE = "BEST_PRACTICE"
    ENGINE = "ENGINE"


class ValidationState(StrEnum):
    IMPORT_FAILED = "IMPORT_FAILED"
    INVALID = "INVALID"
    VALID_WITH_WARNINGS = "VALID_WITH_WARNINGS"
    VALID = "VALID"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class LocalizedMessage:
    """Clave estable y parámetros serializables que la interfaz puede localizar."""

    key: str
    parameters: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationEntity:
    entity_type: str
    entity_id: str


@dataclass(frozen=True)
class ValidationIssue:
    """Problema trazable emitido por una regla, sin puntuación agregada."""

    rule_code: str
    severity: ValidationSeverity
    category: ValidationCategory
    message: LocalizedMessage
    file_name: str | None = None
    row_number: int | None = None
    field_name: str | None = None
    entity: ValidationEntity | None = None
    validator: str = "gtfs-explorer"
    help_id: str | None = None

    def __post_init__(self) -> None:
        if not self.rule_code:
            raise ValueError("El código de regla es obligatorio.")
        if self.row_number is not None and self.row_number < 1:
            raise ValueError("La fila debe ser positiva.")
        if self.help_id is None:
            object.__setattr__(self, "help_id", f"validation/{self.rule_code}")


@dataclass(frozen=True)
class ValidationIssueSummary:
    """Incidencia persistida lista para presentar, sin SQL ni texto HTML."""

    batch_id: str
    position: int
    rule_code: str
    rule_origin: str
    severity: ValidationSeverity
    category: ValidationCategory
    file_name: str | None
    row_number: int | None
    field_name: str | None
    entity: ValidationEntity | None
    message_key: str
    message_parameters: Mapping[str, str | int | float | bool | None]
    help_id: str
    occurrence_count: int


@dataclass(frozen=True)
class ValidationIssueFilter:
    """Filtro tipado de la vista de validación."""

    severities: frozenset[ValidationSeverity] | None = None
    categories: frozenset[ValidationCategory] | None = None


@dataclass(frozen=True)
class ValidationContext:
    feed_id: str
    batch_id: str


class ValidationRule(Protocol):
    @property
    def code(self) -> str: ...

    @property
    def severity(self) -> ValidationSeverity: ...

    @property
    def category(self) -> ValidationCategory: ...

    def evaluate(self, context: ValidationContext) -> Iterable[ValidationIssue]: ...


class DuplicateRuleCodeError(ValueError):
    """El registro impide que dos implementaciones compartan código público."""


class ValidationRuleRegistry:
    """Registro explícito de reglas; el orden de ejecución no depende del alta."""

    def __init__(self) -> None:
        self._rules: dict[str, ValidationRule] = {}

    def register(self, rule: ValidationRule) -> None:
        if not rule.code:
            raise ValueError("El código de regla es obligatorio.")
        if rule.code in self._rules:
            raise DuplicateRuleCodeError(f"Código de regla duplicado: {rule.code}")
        self._rules[rule.code] = rule

    def ordered_rules(self) -> tuple[ValidationRule, ...]:
        return tuple(self._rules[code] for code in sorted(self._rules))


CancellationCheck = Callable[[], bool]
