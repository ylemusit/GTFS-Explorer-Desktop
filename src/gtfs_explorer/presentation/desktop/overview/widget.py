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
        layout = QVBoxLayout(self)
        identity = QGroupBox("Proyecto abierto")
        identity_layout = QFormLayout(identity)
        self._project_name = QLabel("Sin proyecto abierto")
        self._project_name.setObjectName("projectIdentityName")
        self._project_name.setWordWrap(True)
        self._project_workspace = QLabel("—")
        self._project_workspace.setObjectName("projectIdentityWorkspace")
        self._project_workspace.setWordWrap(True)
        identity_layout.addRow("Nombre:", self._project_name)
        identity_layout.addRow("Workspace:", self._project_workspace)
        layout.addWidget(identity)

        self._headline = QLabel("Abra un proyecto para consultar su resumen.")
        self._headline.setObjectName("overviewHeadline")
        self._headline.setWordWrap(True)
        layout.addWidget(self._headline)

        feed_state = QGroupBox("Estado del feed")
        feed_state_layout = QFormLayout(feed_state)
        self._feed_name = QLabel("—")
        self._feed_name.setObjectName("feedStateName")
        self._feed_import_status = QLabel("Sin feed importado")
        self._feed_import_status.setObjectName("feedImportStatus")
        self._feed_validation_status = QLabel("Sin ejecutar")
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
        feed_state_layout.addRow("Feed:", self._feed_name)
        feed_state_layout.addRow("Importación:", self._feed_import_status)
        feed_state_layout.addRow("Validación:", self._feed_validation_status)
        feed_state_layout.addRow("Incidencias:", self._feed_issue_count)
        layout.addWidget(feed_state)

        metrics = QGroupBox("Métricas normalizadas")
        metrics_layout = QVBoxLayout(metrics)
        self._metrics = QFormLayout()
        metrics_layout.addLayout(self._metrics)
        self._metrics_note = QLabel()
        self._metrics_note.setWordWrap(True)
        metrics_layout.addWidget(self._metrics_note)
        layout.addWidget(metrics)

        details = QGroupBox("Periodo y validación")
        self._details = QFormLayout(details)
        self._period = QLabel("Sin fechas de servicio declaradas")
        self._validation = QLabel("Sin ejecuciones de validación registradas")
        self._details.addRow("Periodo de servicio (fecha GTFS):", self._period)
        self._details.addRow("Validación:", self._validation)
        show_validation = QPushButton("Ver incidencias de validación")
        show_validation.setAccessibleName("Ver incidencias de validación")
        show_validation.clicked.connect(on_show_validation)
        self._details.addRow(show_validation)
        layout.addWidget(details)

        files = QGroupBox("Archivos inventariados")
        files_layout = QVBoxLayout(files)
        self._files = QTableWidget(0, 3)
        self._files.setObjectName("overviewFiles")
        self._files.setHorizontalHeaderLabels(("Archivo", "Especificación", "Filas cargadas"))
        self._files.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._files.setAccessibleName("Archivos inventariados del feed")
        files_layout.addWidget(self._files)
        layout.addWidget(files)

        self._welcome = QGroupBox(
            f"{IDENTITY.name} · {t('identity.edition', edition=IDENTITY.edition)}"
        )
        welcome_layout = QVBoxLayout(self._welcome)
        welcome_title = QLabel("Explora el transporte con datos en los que puedes confiar")
        welcome_title.setObjectName("welcomeTitle")
        welcome_title.setStyleSheet("font-size: 18px; font-weight: 700;")
        welcome_layout.addWidget(welcome_title)
        welcome_text = QLabel(
            "Una aplicación profesional para importar, explorar, validar, visualizar "
            "y exportar GTFS Schedule de forma local y offline-first.\n\n"
            + t("identity.created_by", author=IDENTITY.author)
            + "\n"
            + t(
                "identity.copyright",
                year=IDENTITY.copyright_year,
                author=IDENTITY.author,
                rights_notice=IDENTITY.rights_notice,
            )
        )
        welcome_text.setWordWrap(True)
        welcome_text.setObjectName("welcomeCredits")
        welcome_layout.addWidget(welcome_text)
        welcome_layout.addWidget(
            QLabel("Comienza creando o abriendo un proyecto desde la barra de acciones.")
        )
        layout.insertWidget(0, self._welcome)
        self._welcome.setAccessibleName(t("identity.introduction", product_name=IDENTITY.name))

    def show_project_identity(self, name: str, workspace: str) -> None:
        """Muestra la identidad del workspace actualmente abierto."""
        self._project_name.setText(name)
        self._project_name.setToolTip(name)
        self._project_workspace.setText(workspace)
        self._project_workspace.setToolTip(workspace)

    def clear_project_identity(self) -> None:
        """Elimina toda identidad del proyecto cerrado."""
        self._project_name.setText("Sin proyecto abierto")
        self._project_name.setToolTip("")
        self._project_workspace.setText("—")
        self._project_workspace.setToolTip("")

    def clear(self) -> None:
        self._welcome.show()
        self._headline.setText("Abra un proyecto para consultar su resumen.")
        self._feed_name.setText("—")
        self._feed_import_status.setText("Sin feed importado")
        self._feed_validation_status.setText("Sin ejecutar")
        self._feed_issue_count.setText("—")
        self._period.setText("Sin fechas de servicio declaradas")
        self._validation.setText("Sin ejecuciones de validación registradas")
        self._files.setRowCount(0)
        self._clear_metrics()

    def show_overview(self, overview: FeedOverview) -> None:
        self._welcome.hide()
        if overview.feed is None:
            self.clear()
            self._headline.setText("El proyecto todavía no contiene un feed importado.")
            return
        self._feed_name.setText(overview.feed.source_name)
        self._feed_import_status.setText(_import_status_text(overview.feed.status.value))
        validation = overview.validation
        validation_status = _validation_status_text(overview.feed.status.value, validation.statuses)
        self._feed_validation_status.setText(validation_status)
        self._feed_issue_count.setText(
            str(validation.total_issue_count) if validation.run_count else "No disponible"
        )
        self._headline.setText("Estado técnico de importación y resultado de validación del feed.")
        self._clear_metrics()
        if overview.feed.status.value == "IMPORTED":
            self._metrics_note.setText("")
            for metric in overview.metrics:
                self._metrics.addRow(
                    f"{metric.label} ({metric.source}):",
                    QLabel(f"{metric.value} {metric.unit}"),
                )
        else:
            self._metrics_note.setText(
                "Métricas no disponibles: la importación no terminó correctamente."
            )
        self._period.setText(
            "Sin fechas de servicio declaradas"
            if overview.period is None
            else (
                f"{overview.period.start_date.isoformat()} a {overview.period.end_date.isoformat()}"
            )
        )
        self._validation.setText(
            "Sin ejecuciones de validación registradas"
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
                "Conocido" if file.known_to_schedule_spec else "No reconocido",
                "No cargado" if file.row_count is None else str(file.row_count),
            )
            for column, value in enumerate(values):
                self._files.setItem(index, column, QTableWidgetItem(value))
        self._files.resizeColumnsToContents()

    def _clear_metrics(self) -> None:
        while self._metrics.rowCount():
            self._metrics.removeRow(0)


def _import_status_text(status: str) -> str:
    return {
        "IMPORTED": "Completada",
        "CANCELLED": "Cancelada",
        "FAILED": "Fallida",
    }.get(status, status)


def _validation_status_text(feed_status: str, statuses: tuple[str, ...]) -> str:
    if feed_status == "FAILED":
        return "No disponible"
    if not statuses or all(status == "CANCELLED" for status in statuses):
        return "Sin ejecutar"
    return ", ".join(statuses)
