"""Tabla paginada, filtrable y segura de incidencias persistidas."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from gtfs_explorer.domain.overview import ValidationOverview
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
ValidationFilesExecutor = Callable[[], tuple[str, ...]]
ValidationSummaryExecutor = Callable[[], ValidationOverview | None]
NavigateToRaw = Callable[[str, str | None, str | None], None]
ShowHelp = Callable[[str], None]
ExportReport = Callable[[str, ValidationIssueFilter], None]

VALIDATION_PAGE_SIZE = 100
_ISSUE_ROLE = Qt.ItemDataRole.UserRole
_PRIVATE_PARAMETER_KEYS = frozenset(
    {"password", "project_path", "path", "traceback", "user", "username", "token"}
)
_ABSOLUTE_PATH = re.compile(r"(?i)(?:^[a-z]:[\\/]|^\\\\|^/(?:home|private|tmp|users)/)")
_SEVERITY_ORDER = {
    ValidationSeverity.FATAL: 0,
    ValidationSeverity.ERROR: 1,
    ValidationSeverity.WARNING: 2,
    ValidationSeverity.NOTICE: 3,
}
_SEVERITY_BRUSHES = {
    ValidationSeverity.FATAL: QBrush(QColor("#8b1e3f")),
    ValidationSeverity.ERROR: QBrush(QColor("#9a3412")),
    ValidationSeverity.WARNING: QBrush(QColor("#854d0e")),
    ValidationSeverity.NOTICE: QBrush(QColor("#1d4ed8")),
}


class _ValidationTableItem(QTableWidgetItem):
    """Item con ordenación estable, incluido el número de fila física."""

    def __init__(self, text: str, sort_key: tuple[str, str]) -> None:
        super().__init__(text)
        self._sort_key = sort_key

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, _ValidationTableItem):
            return self._sort_key < other._sort_key
        return super().__lt__(other)


class ValidationWidget(QWidget):
    """Permite localizar incidencias sin cargar una celda por cada registro del feed."""

    def __init__(
        self,
        execute: ValidationExecutor,
        parent: QWidget | None = None,
        *,
        list_files: ValidationFilesExecutor | None = None,
        query_summary: ValidationSummaryExecutor | None = None,
        navigate_to_raw: NavigateToRaw | None = None,
        show_help: ShowHelp | None = None,
        export_report: ExportReport | None = None,
    ) -> None:
        super().__init__(parent)
        self._execute = execute
        self._list_files = list_files
        self._query_summary = query_summary
        self._issues: tuple[ValidationIssueSummary, ...] = ()
        self._issue_index: dict[str, ValidationIssueSummary] = {}
        self._known_files: set[str] = set()
        self._offset = 0
        self._total = 0
        self._sort_column: int | None = None
        self._navigate_to_raw = navigate_to_raw
        self._show_help_callback = show_help
        self._export_report = export_report
        self._build_layout()

    @property
    def selected_issue(self) -> ValidationIssueSummary | None:
        """DTO seleccionado, independiente del orden o del índice visual de la tabla."""
        return self._selected_issue()

    def refresh(self) -> None:
        self._offset = 0
        self._load()

    def clear(self) -> None:
        self._issues = ()
        self._issue_index.clear()
        self._known_files.clear()
        self._offset = self._total = 0
        self._sort_column = None
        self._severity.blockSignals(True)
        self._severity.setCurrentIndex(0)
        self._severity.blockSignals(False)
        self._category.blockSignals(True)
        self._category.setCurrentIndex(0)
        self._category.blockSignals(False)
        self._file_filter.blockSignals(True)
        self._populate_file_filter(())
        self._file_filter.blockSignals(False)
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._table.setRowCount(0)
        self._table.clearSelection()
        self._table.setCurrentCell(-1, -1)
        self._detail.clear()
        self._summary.setText("Sin corrida de validación cargada.")
        self._count.setText("Sin incidencias cargadas.")
        self._update_actions()

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        intro = QLabel(t("validation.introduction"))
        intro.setObjectName("validationIntro")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        controls = QGridLayout()
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
        self._file_filter = QComboBox()
        self._file_filter.setAccessibleName(t("validation.file"))
        self._populate_file_filter(())
        self._search = QLineEdit()
        self._search.setAccessibleName(t("validation.search"))
        self._search.setPlaceholderText(t("validation.search_placeholder"))
        self._search.returnPressed.connect(self.refresh)
        apply = QPushButton(t("validation.apply"))
        apply.setObjectName("validationApply")
        apply.setAccessibleName(t("validation.apply"))
        apply.setAccessibleDescription(t("validation.apply_description"))
        apply.setToolTip(t("validation.apply"))
        apply.clicked.connect(self.refresh)
        self._previous = QPushButton(t("validation.previous"))
        self._previous.setAccessibleName(t("validation.previous"))
        self._previous.setToolTip(t("validation.previous"))
        self._previous.clicked.connect(self._previous_page)
        self._next = QPushButton(t("validation.next"))
        self._next.setAccessibleName(t("validation.next"))
        self._next.setToolTip(t("validation.next"))
        self._next.clicked.connect(self._next_page)
        self._go_to_raw = QPushButton(t("validation.raw"))
        self._go_to_raw.setAccessibleName(t("validation.raw"))
        self._go_to_raw.setToolTip(t("validation.raw"))
        self._go_to_raw.clicked.connect(self._navigate_selected)
        self._help = QPushButton(t("validation.help"))
        self._help.setAccessibleName(t("validation.help"))
        self._help.setToolTip(t("validation.help"))
        self._help.clicked.connect(self._show_help)
        self._export = QPushButton(t("validation.export"))
        self._export.setAccessibleName(t("validation.export"))
        self._export.setToolTip(t("validation.export"))
        self._export.clicked.connect(self._export_current_report)
        filter_controls = (
            self._severity,
            self._category,
            self._file_filter,
            self._search,
            apply,
        )
        action_controls = (
            self._previous,
            self._next,
            self._go_to_raw,
            self._help,
            self._export,
        )
        for column, widget in enumerate(filter_controls):
            controls.addWidget(widget, 0, column)
        for column, widget in enumerate(action_controls):
            controls.addWidget(widget, 1, column)
        layout.addLayout(controls)

        self._summary = QLabel("Sin corrida de validación cargada.")
        self._summary.setObjectName("validationRunSummary")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        self._count = QLabel("Sin incidencias cargadas.")
        self._count.setObjectName("validationResultCount")
        layout.addWidget(self._count)

        self._table = QTableWidget(0, 9)
        self._table.setHorizontalHeaderLabels(
            (
                "Severidad",
                "Categoría",
                "Origen",
                "Regla",
                "Archivo",
                "Fila fuente",
                "Campo",
                "Entidad",
                "Mensaje",
            )
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setWordWrap(False)
        self._table.setSortingEnabled(True)
        self._table.setAccessibleName(t("validation.table"))
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        header.sectionClicked.connect(self._remember_sort_column)
        for column, width in enumerate((92, 108, 100, 190, 112, 92, 150, 180, 220)):
            self._table.setColumnWidth(column, width)
        self._table.itemSelectionChanged.connect(self._show_detail)
        layout.addWidget(self._table)

        self._detail = QTextBrowser()
        self._detail.setOpenExternalLinks(False)
        self._detail.setMaximumHeight(190)
        self._detail.setAccessibleName(t("validation.detail"))
        layout.addWidget(self._detail)
        self.setTabOrder(self._severity, self._category)
        self.setTabOrder(self._category, self._file_filter)
        self.setTabOrder(self._file_filter, self._search)
        self.setTabOrder(self._search, apply)
        self.setTabOrder(apply, self._previous)
        self.setTabOrder(self._previous, self._next)
        self.setTabOrder(self._next, self._go_to_raw)
        self.setTabOrder(self._go_to_raw, self._help)
        self.setTabOrder(self._help, self._export)
        self.setTabOrder(self._export, self._table)
        self.setTabOrder(self._table, self._detail)
        self._update_actions()

    def _filter(self) -> ValidationIssueFilter:
        severity = _selected_severity(self._severity.currentData())
        category = _selected_category(self._category.currentData())
        file_name: object = self._file_filter.currentData()
        search_text = self._search.text().strip() or None
        return ValidationIssueFilter(
            severities=frozenset({severity}) if severity is not None else None,
            categories=frozenset({category}) if category is not None else None,
            file_name=file_name if isinstance(file_name, str) else None,
            search_text=search_text,
        )

    def _load(self) -> None:
        self._clear_result()
        self._refresh_file_filter()
        self._load_summary()
        try:
            page = self._execute(
                self._filter(),
                PageRequest(offset=self._offset, limit=VALIDATION_PAGE_SIZE),
            )
        except Exception:
            self._count.setText("No se han podido cargar las incidencias de validación.")
            self._update_actions()
            return
        self._issues, self._total = page.items, page.total
        self._remember_page_files()
        self._fill_table()
        if self._total:
            first = self._offset + 1
            last = self._offset + len(self._issues)
            self._count.setText(f"Mostrando {first}–{last} de {self._total} incidencias.")
        else:
            self._count.setText("No hay incidencias para los filtros actuales.")
        self._previous.setEnabled(self._offset > 0)
        self._next.setEnabled(self._offset + len(self._issues) < self._total)
        self._update_actions()

    def _clear_result(self) -> None:
        self._issues = ()
        self._issue_index.clear()
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        self._table.clearSelection()
        self._table.setCurrentCell(-1, -1)
        self._detail.clear()

    def _load_summary(self) -> None:
        if self._query_summary is None:
            self._summary.setText("Resumen de corrida no disponible en esta vista.")
            return
        try:
            summary = self._query_summary()
        except Exception:
            self._summary.setText("Resumen de corrida no disponible.")
            return
        if summary is None or summary.run_count == 0:
            self._summary.setText("Sin corrida de validación para el feed actual.")
            return
        statuses = ", ".join(summary.statuses) or "Sin estado"
        self._summary.setText(
            f"Estado: {statuses} · {summary.run_count} ejecución(es) · "
            f"{summary.total_issue_count} incidencias registradas."
        )

    def _refresh_file_filter(self) -> None:
        files = tuple(self._known_files)
        if self._list_files is not None:
            try:
                files = self._list_files()
            except Exception:
                # La lista es auxiliar: la consulta principal sigue siendo utilizable.
                pass
        self._populate_file_filter(files)

    def _populate_file_filter(self, files: tuple[str, ...] | set[str]) -> None:
        if not hasattr(self, "_file_filter"):
            return
        selected = self._file_filter.currentData()
        self._file_filter.clear()
        self._file_filter.addItem("Todos los archivos", None)
        for filename in sorted(set(files), key=str.casefold):
            self._file_filter.addItem(_safe_filename(filename), filename)
        if isinstance(selected, str):
            index = self._file_filter.findData(selected)
            self._file_filter.setCurrentIndex(max(0, index))

    def _remember_page_files(self) -> None:
        page_files = {issue.file_name for issue in self._issues if issue.file_name}
        if not page_files:
            return
        self._known_files.update(page_files)
        if self._list_files is None:
            self._populate_file_filter(self._known_files)

    def _fill_table(self) -> None:
        sort_column = self._sort_column
        sort_order = self._table.horizontalHeader().sortIndicatorOrder()
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(self._issues))
        for row, issue in enumerate(self._issues):
            issue_key = _issue_key(issue)
            self._issue_index[issue_key] = issue
            values = (
                issue.severity.value,
                issue.category.value,
                _origin_label(issue.rule_origin),
                issue.rule_code,
                _safe_filename(issue.file_name) if issue.file_name else "Alcance global",
                str(issue.row_number) if issue.row_number is not None else "Sin fila física",
                issue.field_name or "—",
                _entity_label(issue),
                _message_label(issue.message_key),
            )
            sort_keys = (
                ("0", f"{_SEVERITY_ORDER[issue.severity]:02d}"),
                _text_sort_key(issue.category.value),
                _text_sort_key(issue.rule_origin),
                _text_sort_key(issue.rule_code),
                _text_sort_key(issue.file_name),
                _number_sort_key(issue.row_number),
                _text_sort_key(issue.field_name),
                _text_sort_key(issue.entity.entity_id if issue.entity else None),
                _text_sort_key(issue.message_key),
            )
            tooltips = (
                issue.severity.value,
                issue.category.value,
                issue.rule_origin,
                issue.rule_code,
                _safe_filename(issue.file_name) if issue.file_name else "Alcance global",
                (
                    str(issue.row_number)
                    if issue.row_number is not None
                    else "Sin fila física aplicable"
                ),
                issue.field_name or "Sin campo GTFS asociado",
                _entity_label(issue),
                issue.message_key,
            )
            for column, (value, sort_key, tooltip) in enumerate(zip(values, sort_keys, tooltips)):
                item = _ValidationTableItem(value, sort_key)
                item.setData(_ISSUE_ROLE, issue_key)
                item.setToolTip(tooltip)
                if column == 0:
                    item.setForeground(_SEVERITY_BRUSHES[issue.severity])
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self._table.setItem(row, column, item)
        self._table.setSortingEnabled(True)
        if sort_column is not None:
            self._table.sortItems(sort_column, sort_order)

    def _remember_sort_column(self, section: int) -> None:
        self._sort_column = section

    def _previous_page(self) -> None:
        self._offset = max(0, self._offset - VALIDATION_PAGE_SIZE)
        self._load()

    def _next_page(self) -> None:
        self._offset += VALIDATION_PAGE_SIZE
        self._load()

    def _show_detail(self) -> None:
        issue = self._selected_issue()
        if issue is None:
            self._detail.clear()
            self._update_actions()
            return
        fields = [
            ("Severidad", issue.severity.value),
            ("Categoría", issue.category.value),
            ("Origen de regla", issue.rule_origin),
            ("Regla", issue.rule_code),
            ("Mensaje", issue.message_key),
            ("Archivo", _safe_filename(issue.file_name) if issue.file_name else "Alcance global"),
            (
                "Fila fuente",
                (
                    str(issue.row_number)
                    if issue.row_number is not None
                    else "Sin fila física aplicable"
                ),
            ),
            ("Campo", issue.field_name or "Sin campo GTFS asociado"),
        ]
        if issue.entity:
            fields.append(("Entidad", _entity_label(issue)))
        fields.extend(
            (
                ("Ayuda local", issue.help_id),
                ("Repeticiones", str(issue.occurrence_count)),
            )
        )
        text = "\n".join(f"{label}: {value}" for label, value in fields)
        parameters = _safe_parameters(issue.message_parameters)
        if parameters:
            text += "\nParámetros: " + ", ".join(
                f"{key}={value}" for key, value in sorted(parameters.items())
            )
        self._detail.setPlainText(text)
        self._update_actions()

    def _selected_issue(self) -> ValidationIssueSummary | None:
        row = self._table.currentRow()
        if not 0 <= row < self._table.rowCount():
            return None
        item = self._table.item(row, 0)
        if item is None:
            return None
        key = item.data(_ISSUE_ROLE)
        return self._issue_index.get(str(key)) if key is not None else None

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
        issue = self._selected_issue() or (self._issues[0] if self._issues else None)
        if issue is not None and self._export_report is not None:
            self._export_report(issue.batch_id, self._filter())


def _issue_key(issue: ValidationIssueSummary) -> str:
    return f"{issue.batch_id}\x1f{issue.position}"


def _safe_filename(value: str | None) -> str:
    if not value:
        return ""
    return Path(value).name or "[nombre de archivo no disponible]"


def _safe_context_value(key: str, value: object) -> str:
    if key.casefold() in _PRIVATE_PARAMETER_KEYS:
        return "[dato local omitido]"
    text = "" if value is None else str(value)
    if _ABSOLUTE_PATH.search(text):
        return "[ubicación local omitida]"
    return " ".join(text.replace("\r", " ").replace("\n", " ").split())


def _safe_parameters(parameters: object) -> dict[str, str]:
    if not isinstance(parameters, dict):
        return {}
    return {
        str(key): _safe_context_value(str(key), value)
        for key, value in parameters.items()
        if str(key).casefold() not in _PRIVATE_PARAMETER_KEYS
    }


def _origin_label(origin: str) -> str:
    return {
        "mobilitydata": "MobilityData",
        "internal": "Interno",
        "gtfs-explorer": "Interno",
    }.get(origin, origin)


def _selected_severity(value: object) -> ValidationSeverity | None:
    if isinstance(value, ValidationSeverity):
        return value
    if isinstance(value, str):
        try:
            return ValidationSeverity(value)
        except ValueError:
            return None
    return None


def _selected_category(value: object) -> ValidationCategory | None:
    if isinstance(value, ValidationCategory):
        return value
    if isinstance(value, str):
        try:
            return ValidationCategory(value)
        except ValueError:
            return None
    return None


def _entity_label(issue: ValidationIssueSummary) -> str:
    if issue.entity is None:
        return "—"
    entity_id = _safe_context_value("entity_id", issue.entity.entity_id)
    return f"{issue.entity.entity_type} / {entity_id}"


def _message_label(message_key: str) -> str:
    """Hace legible la clave existente sin inventar una explicación de la regla."""
    return message_key.removeprefix("validation.").replace("_", " ")


def _text_sort_key(value: object) -> tuple[str, str]:
    if value is None or value == "":
        return ("1", "")
    return ("0", str(value).casefold())


def _number_sort_key(value: int | None) -> tuple[str, str]:
    if value is None:
        return ("1", "")
    return ("0", f"{value:020d}")
