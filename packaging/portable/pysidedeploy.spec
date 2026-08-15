[app]
title = GTFS Explorer
project_dir = packaging/portable
input_file = packaging/portable/entrypoint.py
exec_directory = packaging/portable
icon =

[python]
python_path = C:\Users\yeiso\Desktop\Folder\VSCode\Proyectos\GTFS Explorer Desktop\.venv\Scripts\python.exe
packages = Nuitka==2.6.9

[qt]
modules = Core,Gui,Widgets,WebChannel,WebEngineCore,WebEngineWidgets
plugins =

[nuitka]
mode = standalone
extra_args = --quiet --noinclude-qt-translations --windows-console-mode=disable --nofollow-import-to=duckdb --include-data-dir=src/gtfs_explorer/resources=gtfs_explorer/resources --include-data-dir=src/gtfs_explorer/infrastructure/duckdb/migrations=gtfs_explorer/infrastructure/duckdb/migrations --include-data-dir=schemas=schemas
