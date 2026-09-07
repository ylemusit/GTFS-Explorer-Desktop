"""Welcome rasterizado con cuatro regiones dinámicas autorizadas por contrato."""

from __future__ import annotations

from collections.abc import Callable
from importlib.resources import files
from typing import Final

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QWidget

from gtfs_explorer.presentation.desktop.i18n import t
from gtfs_explorer.presentation.desktop.icon import application_icon_path
from gtfs_explorer.product import IDENTITY

Translate = Callable[..., str]

# Coordenadas normalizadas respecto a welcome_master_es.png (1077 x 947).
TITLEBAR_RECT: Final[tuple[float, float, float, float]] = (0.0, 0.0, 1.0, 64 / 947)
START_BUTTON_RECT: Final[tuple[float, float, float, float]] = (
    376 / 1077,
    666 / 947,
    324 / 1077,
    68 / 947,
)
VERSION_RECT: Final[tuple[float, float, float, float]] = (
    440 / 1077,
    748 / 947,
    198 / 1077,
    42 / 947,
)
COPYRIGHT_RECT: Final[tuple[float, float, float, float]] = (0.0, 884 / 947, 1.0, 63 / 947)
TITLEBAR_ICON_RECT: Final[tuple[float, float, float, float]] = (
    20 / 1077,
    17 / 947,
    38 / 1077,
    38 / 947,
)
TITLEBAR_TEXT_RECT: Final[tuple[float, float, float, float]] = (
    77 / 1077,
    15 / 947,
    400 / 1077,
    34 / 947,
)
MINIMIZE_RECT: Final[tuple[float, float, float, float]] = (
    950 / 1077,
    8 / 1077,
    54 / 1077,
    48 / 947,
)
CLOSE_RECT: Final[tuple[float, float, float, float]] = (1010 / 1077, 8 / 1077, 54 / 1077, 48 / 947)
TITLEBAR_DRAG_RECT: Final[tuple[float, float, float, float]] = (
    60 / 1077,
    0.0,
    880 / 1077,
    64 / 947,
)

MASTER_ASSET = "welcome_master_es.png"


def _resource_image() -> QImage:
    image = QImage(str(files("gtfs_explorer.resources.brand").joinpath(MASTER_ASSET)))
    if image.isNull():
        raise RuntimeError(f"No se pudo cargar la imagen maestra: {MASTER_ASSET}")
    return image


def _rect(normalized: tuple[float, float, float, float], size: tuple[int, int]) -> QRect:
    width, height = size
    x, y, w, h = normalized
    return QRect(round(x * width), round(y * height), round(w * width), round(h * height))


class RasterWelcomeSurface(QWidget):
    """Pinta la maestra y cubre únicamente las regiones dinámicas autorizadas."""

    def __init__(self, image: QImage, parent: QWidget) -> None:
        super().__init__(parent)
        self.image = image
        self.setMouseTracking(True)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawImage(self.rect(), self.image)
        for region, color in (
            (TITLEBAR_RECT, QColor("#101820")),
            (VERSION_RECT, QColor("#101820")),
            (COPYRIGHT_RECT, QColor("#101820")),
        ):
            painter.fillRect(_rect(region, (self.width(), self.height())), color)
        start = _rect(START_BUTTON_RECT, (self.width(), self.height()))
        painter.setBrush(QColor("#1768E8"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(start, 12, 12)
        titlebar = _rect(TITLEBAR_RECT, (self.width(), self.height()))
        painter.setPen(QColor("#283544"))
        painter.drawLine(0, titlebar.bottom(), self.width(), titlebar.bottom())
        painter.end()

    def mousePressEvent(self, event: object) -> None:
        if hasattr(event, "button") and event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return
        super().mousePressEvent(event)  # type: ignore[arg-type]


class _DynamicLabel(QLabel):
    def __init__(self, parent: QWidget, text: str, *, accessible_name: str) -> None:
        super().__init__(text, parent)
        self.setAccessibleName(accessible_name)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


class WelcomeDialog(QDialog):
    """Ventana frameless: cuerpo raster inmutable y titlebar Qt funcional."""

    def __init__(
        self, parent: QWidget | None = None, *, translate: Translate | None = None
    ) -> None:
        super().__init__(parent)
        self._translate = translate or (lambda key, **values: t(key, **values))
        self.master_image = _resource_image()
        self.setObjectName("startupWelcomeDialog")
        self.setAccessibleName(IDENTITY.name)
        self.setWindowTitle(self._text("startup.window_title", product_name=IDENTITY.name))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(True)
        self.setFixedSize(self.master_image.width(), self.master_image.height())
        self.setWindowIcon(QIcon(str(application_icon_path())))
        self.surface = RasterWelcomeSurface(self.master_image, self)
        self.surface.setGeometry(self.rect())
        self._build_dynamic_regions()

    def _text(self, key: str, **values: object) -> str:
        return self._translate(key, **values)

    def _geometry(self, normalized: tuple[float, float, float, float]) -> QRect:
        return _rect(normalized, (self.width(), self.height()))

    def _button(
        self, text: str, accessible: str, region: tuple[float, float, float, float]
    ) -> QPushButton:
        button = QPushButton(text, self)
        button.setAccessibleName(accessible)
        button.setGeometry(self._geometry(region))
        button.setFlat(True)
        button.setStyleSheet(
            "QPushButton { color: #DCE7F2; background: transparent; border: 0; font-size: 22px; }"
            "QPushButton:hover { background: rgba(255,255,255,18); }"
            "QPushButton:pressed { background: rgba(255,255,255,30); }"
        )
        return button

    def _build_dynamic_regions(self) -> None:
        self.title_label = _DynamicLabel(
            self,
            self._text("startup.window_title", product_name=IDENTITY.name),
            accessible_name=IDENTITY.name,
        )
        self.title_label.setGeometry(self._geometry(TITLEBAR_TEXT_RECT))
        self.title_label.setFont(QFont("Segoe UI", 14))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.title_label.setStyleSheet("color: #F4F7FA; background: transparent;")

        self.title_icon = QLabel(self)
        self.title_icon.setGeometry(self._geometry(TITLEBAR_ICON_RECT))
        self.title_icon.setPixmap(
            QIcon(str(application_icon_path())).pixmap(self.title_icon.size())
        )
        self.title_icon.setAccessibleName(IDENTITY.name)
        self.title_icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.minimize_button = self._button("−", "Minimize", MINIMIZE_RECT)
        self.minimize_button.clicked.connect(self.showMinimized)
        self.close_button = self._button("×", "Close", CLOSE_RECT)
        self.close_button.clicked.connect(self.reject)

        self.start_button = self._button(
            self._text("startup.start") + "   →",
            self._text("startup.start_accessible"),
            START_BUTTON_RECT,
        )
        self.start_button.setDefault(True)
        self.start_button.setStyleSheet(
            "QPushButton { color: white; background: transparent; border: 0; "
            "font-size: 24px; font-weight: 700; }"
            "QPushButton:hover { background: rgba(255,255,255,18); }"
        )
        self.start_button.clicked.connect(self.accept)

        self.version_label = _DynamicLabel(
            self, self._text("startup.version", version=IDENTITY.version), accessible_name="Version"
        )
        self.version_label.setGeometry(self._geometry(VERSION_RECT))
        self.version_label.setStyleSheet(
            "color: #9DA9B6; background: transparent; font-size: 17px;"
        )
        self.footer_label = _DynamicLabel(
            self,
            f"© {IDENTITY.copyright_year} {IDENTITY.author}  ·  {IDENTITY.rights_notice}",
            accessible_name="Copyright",
        )
        self.footer_label.setGeometry(self._geometry(COPYRIGHT_RECT))
        self.footer_label.setStyleSheet("color: #778493; background: transparent; font-size: 16px;")

    def keyPressEvent(self, event: object) -> None:
        if hasattr(event, "key") and event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)  # type: ignore[arg-type]

    def resizeEvent(self, event: object) -> None:
        self.surface.setGeometry(self.rect())
        for widget, region in (
            (self.title_label, TITLEBAR_TEXT_RECT),
            (self.title_icon, TITLEBAR_ICON_RECT),
            (self.minimize_button, MINIMIZE_RECT),
            (self.close_button, CLOSE_RECT),
            (self.start_button, START_BUTTON_RECT),
            (self.version_label, VERSION_RECT),
            (self.footer_label, COPYRIGHT_RECT),
        ):
            widget.setGeometry(self._geometry(region))
        super().resizeEvent(event)  # type: ignore[arg-type]

    def retranslate(self) -> None:
        self.setWindowTitle(self._text("startup.window_title", product_name=IDENTITY.name))
        self.title_label.setText(self.windowTitle())
        self.start_button.setText(self._text("startup.start") + "   →")
        self.start_button.setAccessibleName(self._text("startup.start_accessible"))
        self.version_label.setText(self._text("startup.version", version=IDENTITY.version))


StartupIntroDialog = WelcomeDialog


def show_welcome_dialog(
    parent: QWidget | None = None, *, translate: Translate | None = None
) -> int:
    return WelcomeDialog(parent, translate=translate).exec()
