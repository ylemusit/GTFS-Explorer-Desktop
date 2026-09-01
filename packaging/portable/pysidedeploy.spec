[app]
title = GTFS Explorer Desktop
project_dir = packaging/portable
input_file = packaging/portable/entrypoint.py
exec_directory = packaging/portable
icon = src/gtfs_explorer/resources/gtfs_explorer.ico

[python]
python_path = .venv/Scripts/python.exe
packages = Nuitka==2.6.9

[qt]
modules = Core,Gui,Widgets,WebChannel,WebEngineCore,WebEngineWidgets
plugins =

[nuitka]
mode = standalone
# tools/build_portable.py añade aquí la metadata PE desde gtfs_explorer.product
# a la copia temporal que consume pyside6-deploy.
extra_args = --quiet --noinclude-qt-translations --windows-console-mode=disable --windows-icon-from-ico=src/gtfs_explorer/resources/gtfs_explorer.ico --nofollow-import-to=duckdb --include-data-dir=src/gtfs_explorer/resources=gtfs_explorer/resources --include-data-dir=src/gtfs_explorer/infrastructure/duckdb/migrations=gtfs_explorer/infrastructure/duckdb/migrations --include-data-dir=schemas=schemas
