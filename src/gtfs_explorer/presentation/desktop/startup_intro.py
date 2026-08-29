"""Presentación inicial de la aplicación."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from gtfs_explorer.presentation.desktop.i18n import t
from gtfs_explorer.product import IDENTITY


class StartupIntroDialog(QDialog):
    """Presenta la identidad del producto antes de mostrar la ventana principal."""

    def __init__(self, parent: QDialog | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("identity.welcome_window_title", product_name=IDENTITY.name))
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        eyebrow = QLabel(
            f"{IDENTITY.name.upper()} · {t('identity.edition', edition=IDENTITY.edition).upper()}"
        )
        eyebrow.setStyleSheet("color: #2563eb; font-weight: 700; letter-spacing: 1px;")
        layout.addWidget(eyebrow)

        title = QLabel(t("identity.welcome_title"))
        title.setStyleSheet("font-size: 24px; font-weight: 700;")
        title.setWordWrap(True)
        layout.addWidget(title)

        description = QLabel(t("identity.welcome_description"))
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addWidget(QLabel(t("identity.version", version=IDENTITY.version)))

        author = QLabel(
            t("identity.created_by", author=IDENTITY.author)
            + "\n"
            + t(
                "identity.copyright",
                year=IDENTITY.copyright_year,
                author=IDENTITY.author,
                rights_notice=IDENTITY.rights_notice,
            )
        )
        author.setWordWrap(True)
        author.setStyleSheet("margin-top: 12px; color: #4b5563;")
        layout.addWidget(author)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        start_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        start_button.setText(t("identity.start"))
        start_button.setDefault(True)
        start_button.setAccessibleName(t("identity.start"))
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box, alignment=Qt.AlignmentFlag.AlignRight)
