"""Lista filtrable y segura de incidencias persistidas."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from gtfs_explorer.domain.ports import PagedResult, PageRequest
from gtfs_explorer.domain.validation import (
    ValidationCategory,
    ValidationIssueFilter,
    ValidationIssueSummary,
    ValidationSeverity,
)
from gtfs_explorer.presentation.desktop.i18n import t

ValidationExecutor = Callable[
    [ValidationIssueFilter, PageRequest], PagedResult[ValidationIssueSummary]
]
NavigateToRaw = Callable[[str, str | None, str | None], None]
ShowHelp = Callable[[str], None]
ExportReport = Callable[[str, ValidationIssueFilter], None]


class ValidationWidget(QWidget):
    """Presenta texto como texto y carga el detalle únicamente al seleccionar."""

    def __init__(
        self,
        execute: ValidationExecutor,
        parent: QWidget | None = None,
        *,
        navigate_to_raw: NavigateToRaw | None = None,
        show_help: ShowHelp | None = None,
        export_report: ExportReport | None = None,
    ) -> None:
        super().__init__(parent)
        self._execute = execute
        self._issues: tuple[ValidationIssueSummary, ...] = ()
        self._offset = 0
        self._total = 0
        self._navigate_to_raw = navigate_to_raw
        self._show_help_callback = show_help
        self._export_report = export_report
        self._build_layout()

    def refresh(self) -> None:
        self._offset = 0
        self._load()

    def clear(self) -> None:
        self._issues = ()
        self._offset = self._total = 0
        self._table.setRowCount(0)
        self._detail.clear()
        self._count.setText("Sin incidencias cargadas.")
        self._update_actions()

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Validación: incidencias formales y recomendaciones separadas."))
        controls = QHBoxLayout()
        self._severity = QComboBox()
        self._severity.setAccessibleName(t("validation.severity"))
        self._severity.addItem("Todas las severidades", None)
        for value in ValidationSeverity:
            self._severity.addItem(value.value, value)
        self._category = QComboBox()
        self._category.setAccessibleName(t("validation.category"))
        self._category.addItem("Todas las categorías", None)
        for category_value in ValidationCategory:
            self._category.addItem(category_value.value, category_value)
        apply = QPushButton(t("validation.apply"))
        apply.clicked.connect(self.refresh)
        self._previous = QPushButton(t("validation.previous"))
        self._previous.clicked.connect(self._previous_page)
        self._next = QPushButton(t("validation.next"))
        self._next.clicked.connect(self._next_page)
        self._go_to_raw = QPushButton(t("validation.raw"))
        self._go_to_raw.clicked.connect(self._navigate_selected)
        self._help = QPushButton(t("validation.help"))
        self._help.clicked.connect(self._show_help)
        self._export = QPushButton(t("validation.export"))
        self._export.clicked.connect(self._export_current_report)
        for widget in (
            self._severity,
            self._category,
            apply,
            self._previous,
            self._next,
            self._go_to_raw,
            self._help,
            self._export,
        ):
            controls.addWidget(widget)
        layout.addLayout(controls)
        self._count = QLabel("Sin incidencias cargadas.")
        layout.addWidget(self._count)
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ("Severidad", "Categoría", "Origen", "Regla", "Archivo", "Fila", "Entidad")
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAccessibleName(t("validation.table"))
        self._table.itemSelectionChanged.connect(self._show_detail)
        layout.addWidget(self._table)
        self._detail = QTextBrowser()
        self._detail.setOpenExternalLinks(False)
        self._detail.setAccessibleName(t("validation.detail"))
        layout.addWidget(self._detail)
        self.setTabOrder(self._severity, self._category)
        self.setTabOrder(self._category, apply)
        self.setTabOrder(apply, self._previous)
        self.setTabOrder(self._previous, self._next)
        self.setTabOrder(self._next, self._go_to_raw)
        self.setTabOrder(self._go_to_raw, self._help)
        self.setTabOrder(self._help, self._export)
        self.setTabOrder(self._export, self._table)
        self.setTabOrder(self._table, self._detail)
        self._update_actions()

    def _filter(self) -> ValidationIssueFilter:
        severity: object = self._severity.currentData()
        category: object = self._category.currentData()
        return ValidationIssueFilter(
            frozenset({severity}) if isinstance(severity, ValidationSeverity) else None,
            frozenset({category}) if isinstance(category, ValidationCategory) else None,
        )

    def _load(self) -> None:
        try:
            page = self._execute(self._filter(), PageRequest(offset=self._offset, limit=100))
        except Exception as error:
            self._count.setText(f"No se han podido cargar las incidencias: {error}")
            return
        self._issues, self._total = page.items, page.total
        self._table.setRowCount(len(self._issues))
        for row, issue in enumerate(self._issues):
            values = (
                issue.severity.value,
                issue.category.value,
                "MobilityData" if issue.rule_origin == "mobilitydata" else "Interno",
                issue.rule_code,
                issue.file_name or "",
                str(issue.row_number or ""),
                issue.entity.entity_id if issue.entity else "",
            )
            for column, value in enumerate(values):
                self._table.setItem(row, column, QTableWidgetItem(value))
        self._count.setText(
            f"Mostrando {self._offset + len(self._issues)} de {self._total} incidencias."
        )
        self._previous.setEnabled(self._offset > 0)
        self._next.setEnabled(self._offset + len(self._issues) < self._total)
        self._detail.clear()
        self._update_actions()

    def _previous_page(self) -> None:
        self._offset = max(0, self._offset - 100)
        self._load()

    def _next_page(self) -> None:
        self._offset += 100
        self._load()

    def _show_detail(self) -> None:
        row = self._table.currentRow()
        if not 0 <= row < len(self._issues):
            return
        issue = self._issues[row]
        fields = (
            ("Origen de regla", issue.rule_origin),
            ("Clave de mensaje", issue.message_key),
            ("Ayuda local", issue.help_id),
            ("Repeticiones", str(issue.occurrence_count)),
        )
        text = "\n".join(f"{label}: {value}" for label, value in fields)
        if issue.file_name:
            text += (
                f"\nUbicación: {issue.file_name}, fila {issue.row_number or '-'}, "
                f"campo {issue.field_name or '-'}"
            )
        if issue.entity:
            text += f"\nEntidad: {issue.entity.entity_type} / {issue.entity.entity_id}"
        if issue.message_parameters:
            text += "\nParámetros: " + ", ".join(
                f"{key}={value}" for key, value in sorted(issue.message_parameters.items())
            )
        self._detail.setPlainText(text)
        self._update_actions()

    def _selected_issue(self) -> ValidationIssueSummary | None:
        row = self._table.currentRow()
        return self._issues[row] if 0 <= row < len(self._issues) else None

    def _update_actions(self) -> None:
        issue = self._selected_issue()
        self._go_to_raw.setEnabled(
            issue is not None and issue.file_name is not None and self._navigate_to_raw is not None
        )
        self._help.setEnabled(issue is not None and self._show_help_callback is not None)
        self._export.setEnabled(bool(self._issues) and self._export_report is not None)

    def _navigate_selected(self) -> None:
        issue = self._selected_issue()
        if issue is not None and issue.file_name and self._navigate_to_raw is not None:
            self._navigate_to_raw(
                issue.file_name, issue.field_name, issue.entity.entity_id if issue.entity else None
            )

    def _show_help(self) -> None:
        issue = self._selected_issue()
        if issue is not None and self._show_help_callback is not None:
            self._show_help_callback(issue.help_id)

    def _export_current_report(self) -> None:
        if self._issues and self._export_report is not None:
            self._export_report(self._issues[0].batch_id, self._filter())
