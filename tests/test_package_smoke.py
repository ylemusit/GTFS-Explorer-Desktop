from pathlib import Path


def test_package_smoke_forbidden_check_is_relative_to_extracted_root() -> None:
    script = (Path(__file__).parents[1] / "tools" / "package_smoke.ps1").read_text(encoding="utf-8")

    assert "[System.IO.Path]::GetRelativePath($root, $_.FullName)" in script
    assert "$_.FullName -match" not in script
    assert "(^|\\\\)ctm(\\\\|$)" in script
