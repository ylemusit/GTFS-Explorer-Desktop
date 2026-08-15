"""Manual local buscable y presentado sin interpretar HTML de terceros."""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from importlib.resources import files

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class HelpTopic:
    """Una entrada de contenido local, sin HTML ni enlaces externos."""

    topic_id: str
    title: str
    body: str
    keywords: tuple[str, ...]


class HelpCatalog:
    """Carga y resuelve el manual versionado incluido en el paquete."""

    def __init__(self, topics: tuple[HelpTopic, ...]) -> None:
        if not topics or len({topic.topic_id for topic in topics}) != len(topics):
            raise ValueError("El manual debe contener identificadores de tema únicos.")
        self._topics = topics
        self._by_id = {topic.topic_id: topic for topic in topics}

    @classmethod
    def load_default(cls) -> HelpCatalog:
        raw = files("gtfs_explorer.resources.help").joinpath("index.json").read_text("utf-8")
        payload = json.loads(raw)
        if payload.get("version") != 1 or not isinstance(payload.get("topics"), list):
            raise ValueError("La versión del manual local no es compatible.")
        topics = tuple(
            HelpTopic(
                str(entry["id"]),
                str(entry["title"]),
                str(entry["body"]),
                tuple(str(keyword) for keyword in entry["keywords"]),
            )
            for entry in payload["topics"]
        )
        return cls(topics)

    def resolve(self, help_id: str | None) -> HelpTopic:
        """Devuelve la regla genérica para cualquier código público de validación."""
        if help_id and help_id in self._by_id:
            return self._by_id[help_id]
        if help_id and help_id.startswith("validation/"):
            return self._by_id["validation/reglas"]
        return self._by_id["inicio"]

    def search(self, query: str) -> tuple[HelpTopic, ...]:
        terms = tuple(term.casefold() for term in query.split() if term)
        if not terms:
            return self._topics
        return tuple(
            topic
            for topic in self._topics
            if all(
                term in " ".join((topic.title, topic.body, *topic.keywords)).casefold()
                for term in terms
            )
        )


class HelpDialog(QDialog):
    """Diálogo de ayuda offline con búsqueda; el contenido se escapa antes de HTML."""

    def __init__(
        self, catalog: HelpCatalog, help_id: str | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self.setWindowTitle("Ayuda local")
        self.resize(720, 460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Manual integrado (sin conexión)", self))
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Buscar en la ayuda…")
        self._search.textChanged.connect(self._refresh_topics)
        layout.addWidget(self._search)
        content = QHBoxLayout()
        self._topics = QListWidget(self)
        self._topics.currentRowChanged.connect(self._show_topic)
        content.addWidget(self._topics, 1)
        self._body = QTextBrowser(self)
        self._body.setOpenExternalLinks(False)
        content.addWidget(self._body, 3)
        layout.addLayout(content)
        self._shown = self._catalog.search("")
        self._refresh_topics()
        target = self._catalog.resolve(help_id)
        self._select(target.topic_id)

    def _refresh_topics(self) -> None:
        selected = self._topics.currentItem().data(0x0100) if self._topics.currentItem() else None
        self._shown = self._catalog.search(self._search.text())
        self._topics.clear()
        for topic in self._shown:
            self._topics.addItem(topic.title)
            self._topics.item(self._topics.count() - 1).setData(0x0100, topic.topic_id)
        self._select(str(selected) if selected else None)

    def _select(self, topic_id: str | None) -> None:
        for row in range(self._topics.count()):
            if self._topics.item(row).data(0x0100) == topic_id:
                self._topics.setCurrentRow(row)
                return
        if self._topics.count():
            self._topics.setCurrentRow(0)

    def _show_topic(self, row: int) -> None:
        if not 0 <= row < len(self._shown):
            self._body.clear()
            return
        topic = self._shown[row]
        self._body.setHtml(f"<h2>{escape(topic.title)}</h2><p>{escape(topic.body)}</p>")
