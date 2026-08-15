"""Punto de entrada estable para el build portable de Nuitka."""

from gtfs_explorer.__main__ import main  # noqa: I001 - entrada mínima intencionada


if __name__ == "__main__":
    raise SystemExit(main())
