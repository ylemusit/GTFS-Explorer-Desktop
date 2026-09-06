"""Vista accesible y deliberadamente sobria del resumen del feed."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gtfs_explorer.domain.overview import FeedOverview
from gtfs_explorer.presentation.desktop.i18n import t
from gtfs_explorer.product import IDENTITY


class FeedOverviewWidget(QWidget):
    """Muestra métricas y procedencia sin confundir ausencia con cero."""

    def __init__(
        self, on_show_validation: Callable[[], None], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._current_overview: FeedOverview | None = None
        layout = QVBoxLayout(self)
        identity = QGroupBox(t("overview.project_open"))
        self._identity_group = identity
        identity_layout = QFormLayout(identity)
        self._project_name = QLabel(t("overview.no_project"))
        self._project_name.setObjectName("projectIdentityName")
        self._project_name.setWordWrap(True)
        self._project_workspace = QLabel("—")
        self._project_workspace.setObjectName("projectIdentityWorkspace")
        self._project_workspace.setWordWrap(True)
        self._project_name_label = QLabel(t("overview.project_name_label"))
        self._project_name_label.setBuddy(self._project_name)
        self._project_workspace_label = QLabel(t("overview.workspace_label"))
        self._project_workspace_label.setBuddy(self._project_workspace)
        identity_layout.addRow(self._project_name_label, self._project_name)
        identity_layout.addRow(self._project_workspace_label, self._project_workspace)
        layout.addWidget(identity)

        self._headline = QLabel(t("overview.empty_headline"))
        self._headline.setObjectName("overviewHeadline")
        self._headline.setWordWrap(True)
        layout.addWidget(self._headline)

        feed_state = QGroupBox(t("overview.feed_state"))
        self._feed_state_group = feed_state
        feed_state_layout = QFormLayout(feed_state)
        self._feed_name = QLabel("—")
        self._feed_name.setObjectName("feedStateName")
        self._feed_import_status = QLabel(t("overview.no_feed"))
        self._feed_import_status.setObjectName("feedImportStatus")
        self._feed_validation_status = QLabel(t("overview.not_run"))
        self._feed_validation_status.setObjectName("feedValidationStatus")
        self._feed_issue_count = QLabel("—")
        self._feed_issue_count.setObjectName("feedIssueCount")
        for label in (
            self._feed_name,
            self._feed_import_status,
            self._feed_validation_status,
            self._feed_issue_count,
        ):
            label.setWordWrap(True)
        self._feed_name_label = QLabel(t("overview.feed_label"))
        self._feed_name_label.setBuddy(self._feed_name)
        self._feed_import_label = QLabel(t("overview.import_label"))
        self._feed_import_label.setBuddy(self._feed_import_status)
        self._feed_validation_label = QLabel(t("overview.validation_label"))
        self._feed_validation_label.setBuddy(self._feed_validation_status)
        self._feed_issue_label = QLabel(t("overview.issues_label"))
        self._feed_issue_label.setBuddy(self._feed_issue_count)
        feed_state_layout.addRow(self._feed_name_label, self._feed_name)
        feed_state_layout.addRow(self._feed_import_label, self._feed_import_status)
        feed_state_layout.addRow(self._feed_validation_label, self._feed_validation_status)
        feed_state_layout.addRow(self._feed_issue_label, self._feed_issue_count)
        layout.addWidget(feed_state)

        metrics = QGroupBox(t("overview.metrics"))
        self._metrics_group = metrics
        metrics_layout = QVBoxLayout(metrics)
        self._metrics = QFormLayout()
        metrics_layout.addLayout(self._metrics)
        self._metrics_note = QLabel()
        self._metrics_note.setWordWrap(True)
        metrics_layout.addWidget(self._metrics_note)
        layout.addWidget(metrics)

        details = QGroupBox(t("overview.period_and_validation"))
        self._details_group = details
        self._details = QFormLayout(details)
        self._period = QLabel(t("overview.no_service_dates"))
        self._validation = QLabel(t("overview.no_validation_runs"))
        self._period_label = QLabel(t("overview.service_period_label"))
        self._period_label.setBuddy(self._period)
        self._details_validation_label = QLabel(t("overview.validation_label"))
        self._details_validation_label.setBuddy(self._validation)
        self._details.addRow(self._period_label, self._period)
        self._details.addRow(self._details_validation_label, self._validation)
        show_validation = QPushButton(t("overview.show_validation"))
        self._show_validation_button = show_validation
        show_validation.setAccessibleName(t("overview.show_validation"))
        show_validation.clicked.connect(on_show_validation)
        self._details.addRow(show_validation)
        layout.addWidget(details)

        files = QGroupBox(t("overview.files"))
        self._files_group = files
        files_layout = QVBoxLayout(files)
        self._files = QTableWidget(0, 3)
        self._files.setObjectName("overviewFiles")
        self._files.setHorizontalHeaderLabels(
            (
                t("overview.file_header"),
                t("overview.specification_header"),
                t("overview.rows_header"),
            )
        )
        self._files.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._files.setAccessibleName(t("overview.files_accessible"))
        files_layout.addWidget(self._files)
        layout.addWidget(files)

        self._welcome = QGroupBox(
            f"{IDENTITY.name} · {t('identity.edition', edition=IDENTITY.edition)}"
        )
        welcome_layout = QVBoxLayout(self._welcome)
        welcome_title = QLabel(t("overview.welcome_title"))
        self._welcome_title = welcome_title
        welcome_title.setObjectName("welcomeTitle")
        welcome_title.setStyleSheet("font-size: 18px; font-weight: 700;")
        welcome_layout.addWidget(welcome_title)
        welcome_text = QLabel(
            t("overview.welcome_description")
            + "\n\n"
            + t("identity.created_by", author=IDENTITY.author)
            + "\n"
            + t(
                "identity.copyright",
                year=IDENTITY.copyright_year,
                author=IDENTITY.author,
                rights_notice=IDENTITY.rights_notice,
            )
        )
        self._welcome_text = welcome_text
        welcome_text.setWordWrap(True)
        welcome_text.setObjectName("welcomeCredits")
        welcome_layout.addWidget(welcome_text)
        welcome_hint = QLabel(t("overview.welcome_hint"))
        self._welcome_hint = welcome_hint
        layout.insertWidget(0, self._welcome)
        welcome_layout.addWidget(welcome_hint)
        self._welcome.setAccessibleName(t("identity.introduction", product_name=IDENTITY.name))

    def show_project_identity(self, name: str, workspace: str) -> None:
        """Muestra la identidad del workspace actualmente abierto."""
        self._project_name.setText(name)
        self._project_name.setToolTip(name)
        self._project_workspace.setText(workspace)
        self._project_workspace.setToolTip(workspace)

    def clear_project_identity(self) -> None:
        """Elimina toda identidad del proyecto cerrado."""
        self._project_name.setText(t("overview.no_project"))
        self._project_name.setToolTip("")
        self._project_workspace.setText("—")
        self._project_workspace.setToolTip("")

    def clear(self) -> None:
        self._current_overview = None
        self._welcome.show()
        self._headline.setText(t("overview.empty_headline"))
        self._feed_name.setText("—")
        self._feed_import_status.setText(t("overview.no_feed"))
        self._feed_validation_status.setText(t("overview.not_run"))
        self._feed_issue_count.setText("—")
        self._period.setText(t("overview.no_service_dates"))
        self._validation.setText(t("overview.no_validation_runs"))
        self._files.setRowCount(0)
        self._clear_metrics()

    def show_overview(self, overview: FeedOverview) -> None:
        self._current_overview = overview if overview.feed is not None else None
        self._welcome.hide()
        if overview.feed is None:
            self.clear()
            self._headline.setText(t("overview.project_without_feed"))
            return
        self._feed_name.setText(overview.feed.source_name)
        self._feed_import_status.setText(_import_status_text(overview.feed.status.value))
        validation = overview.validation
        validation_status = _validation_status_text(overview.feed.status.value, validation.statuses)
        self._feed_validation_status.setText(validation_status)
        self._feed_issue_count.setText(
            str(validation.total_issue_count)
            if validation.run_count
            else t("overview.not_available")
        )
        self._headline.setText(t("overview.technical_status"))
        self._clear_metrics()
        if overview.feed.status.value == "IMPORTED":
            self._metrics_note.clear()
            for metric in overview.metrics:
                self._metrics.addRow(
                    f"{metric.label} ({metric.source}):",
                    QLabel(f"{metric.value} {metric.unit}"),
                )
        else:
            self._metrics_note.setText(t("overview.metrics_unavailable"))
        self._period.setText(
            t("overview.no_service_dates")
            if overview.period is None
            else (
                f"{overview.period.start_date.isoformat()} a {overview.period.end_date.isoformat()}"
            )
        )
        self._validation.setText(
            t("overview.no_validation_runs")
            if validation.run_count == 0
            else (
                f"{validation.run_count} ejecución(es), "
                f"{validation.total_issue_count} incidencia(s); "
                f"estados: {', '.join(validation.statuses)}"
            )
        )
        self._files.setRowCount(len(overview.files))
        for index, file in enumerate(overview.files):
            values = (
                file.name,
                t("overview.known") if file.known_to_schedule_spec else t("overview.unknown"),
                t("overview.not_loaded") if file.row_count is None else str(file.row_count),
            )
            for column, value in enumerate(values):
                self._files.setItem(index, column, QTableWidgetItem(value))
        self._files.resizeColumnsToContents()

    def retranslate_ui(self) -> None:
        """Actualiza etiquetas y conserva el resumen cargado."""
        self._identity_group.setTitle(t("overview.project_open"))
        self._project_name_label.setText(t("overview.project_name_label"))
        self._project_workspace_label.setText(t("overview.workspace_label"))
        self._feed_state_group.setTitle(t("overview.feed_state"))
        self._feed_name_label.setText(t("overview.feed_label"))
        self._feed_import_label.setText(t("overview.import_label"))
        self._feed_validation_label.setText(t("overview.validation_label"))
        self._feed_issue_label.setText(t("overview.issues_label"))
        self._metrics_group.setTitle(t("overview.metrics"))
        self._details_group.setTitle(t("overview.period_and_validation"))
        self._period_label.setText(t("overview.service_period_label"))
        self._details_validation_label.setText(t("overview.validation_label"))
        self._show_validation_button.setText(t("overview.show_validation"))
        self._show_validation_button.setAccessibleName(t("overview.show_validation"))
        self._files_group.setTitle(t("overview.files"))
        self._files.setHorizontalHeaderLabels(
            (
                t("overview.file_header"),
                t("overview.specification_header"),
                t("overview.rows_header"),
            )
        )
        self._files.setAccessibleName(t("overview.files_accessible"))
        self._welcome.setTitle(
            f"{IDENTITY.name} · {t('identity.edition', edition=IDENTITY.edition)}"
        )
        self._welcome_title.setText(t("overview.welcome_title"))
        self._welcome_text.setText(
            t("overview.welcome_description")
            + "\n\n"
            + t("identity.created_by", author=IDENTITY.author)
            + "\n"
            + t(
                "identity.copyright",
                year=IDENTITY.copyright_year,
                author=IDENTITY.author,
                rights_notice=IDENTITY.rights_notice,
            )
        )
        self._welcome_hint.setText(t("overview.welcome_hint"))
        if self._current_overview is not None:
            self.show_overview(self._current_overview)
        else:
            self.clear()

    def _clear_metrics(self) -> None:
        while self._metrics.rowCount():
            self._metrics.removeRow(0)


def _import_status_text(status: str) -> str:
    return {
        "IMPORTED": t("overview.import_completed"),
        "CANCELLED": t("overview.import_cancelled"),
        "FAILED": t("overview.import_failed"),
    }.get(status, status)


def _validation_status_text(feed_status: str, statuses: tuple[str, ...]) -> str:
    if feed_status == "FAILED":
        return t("overview.not_available")
    if not statuses or all(status == "CANCELLED" for status in statuses):
        return t("overview.not_run")
    return ", ".join(statuses)
