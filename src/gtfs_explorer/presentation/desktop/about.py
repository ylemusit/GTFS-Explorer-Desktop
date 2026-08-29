"""Diálogo local de identidad y versión de GTFS Explorer Desktop."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from gtfs_explorer.presentation.desktop.i18n import t
from gtfs_explorer.product import IDENTITY, runtime_architecture, runtime_build_id


class AboutDialog(QDialog):
    """Presenta la identidad operativa sin depender de red ni de archivos externos."""

    def __init__(
        self,
        data_directory: Path | None = None,
        *,
        parent: QWidget | None = None,
        build_id: str | None = None,
        architecture: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("identity.about_window_title", product_name=IDENTITY.name))
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        title = QLabel(IDENTITY.name, self)
        title.setObjectName("aboutProductName")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(title)
        description = QLabel(t("identity.about_description"), self)
        description.setWordWrap(True)
        layout.addWidget(description)

        form = QFormLayout()
        self._product_label = self._value(IDENTITY.name, "aboutProductValue")
        self._version_label = self._value(
            t("identity.version", version=IDENTITY.version), "aboutVersionValue"
        )
        self._build_label = self._value(
            build_id if build_id is not None else runtime_build_id(), "aboutBuildValue"
        )
        self._edition_label = self._value(
            t("identity.edition", edition=IDENTITY.edition), "aboutEditionValue"
        )
        self._gtfs_label = self._value(IDENTITY.gtfs_spec_revision, "aboutGtfsValue")
        self._architecture_label = self._value(
            architecture if architecture is not None else runtime_architecture(),
            "aboutArchitectureValue",
        )
        self._data_label = self._value(
            str(data_directory) if data_directory is not None else "—", "aboutDataValue"
        )
        for label, value in (
            (t("identity.about_product"), self._product_label),
            (t("identity.about_version"), self._version_label),
            (t("identity.about_build"), self._build_label),
            (t("identity.about_edition"), self._edition_label),
            (t("identity.about_gtfs"), self._gtfs_label),
            (t("identity.about_architecture"), self._architecture_label),
            (t("identity.about_data"), self._data_label),
        ):
            form.addRow(label + ":", value)
        layout.addLayout(form)

        credits = QLabel(IDENTITY.copyright_text, self)
        credits.setObjectName("aboutCredits")
        credits.setWordWrap(True)
        credits.setStyleSheet("margin-top: 10px; color: #4b5563;")
        layout.addWidget(credits)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        self._close_button = close_button
        close_button.setText(t("identity.about_close"))
        close_button.setAccessibleName(t("identity.about_close"))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, alignment=Qt.AlignmentFlag.AlignRight)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - API Qt
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    @staticmethod
    def _value(value: str, object_name: str) -> QLabel:
        label = QLabel(value)
        label.setObjectName(object_name)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label
