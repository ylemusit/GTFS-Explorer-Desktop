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


class FeedOverviewWidget(QWidget):
    """Muestra métricas y procedencia sin confundir ausencia con cero."""

    def __init__(
        self, on_show_validation: Callable[[], None], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self._headline = QLabel("Abra un proyecto para consultar su resumen.")
        self._headline.setObjectName("overviewHeadline")
        self._headline.setWordWrap(True)
        layout.addWidget(self._headline)

        metrics = QGroupBox("Métricas normalizadas")
        self._metrics = QFormLayout(metrics)
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

    def clear(self) -> None:
        self._headline.setText("Abra un proyecto para consultar su resumen.")
        self._period.setText("Sin fechas de servicio declaradas")
        self._validation.setText("Sin ejecuciones de validación registradas")
        self._files.setRowCount(0)
        self._clear_metrics()

    def show_overview(self, overview: FeedOverview) -> None:
        if overview.feed is None:
            self.clear()
            self._headline.setText("El proyecto todavía no contiene un feed importado.")
            return
        self._headline.setText(
            f"Feed: {overview.feed.source_name} — "
            f"estado de importación: {overview.feed.status.value}."
        )
        self._clear_metrics()
        for metric in overview.metrics:
            self._metrics.addRow(
                f"{metric.label} ({metric.source}):",
                QLabel(f"{metric.value} {metric.unit}"),
            )
        self._period.setText(
            "Sin fechas de servicio declaradas"
            if overview.period is None
            else (
                f"{overview.period.start_date.isoformat()} a {overview.period.end_date.isoformat()}"
            )
        )
        validation = overview.validation
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
