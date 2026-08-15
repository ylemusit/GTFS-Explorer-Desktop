"""Errores tipados de importación que la UI podrá traducir más adelante."""


class ImportSecurityError(ValueError):
    """Una fuente incumple un límite o una garantía de confinamiento."""


class ImportCancelled(RuntimeError):
    """La importación se ha cancelado antes de completar la extracción."""


class TabularReadError(ValueError):
    """Error de lectura tabular con la fila física que lo originó."""

    def __init__(self, message: str, row_number: int) -> None:
        super().__init__(f"Fila {row_number}: {message}")
        self.row_number = row_number


class RepositoryError(RuntimeError):
    """Un repositorio no pudo completar una operación de persistencia."""
