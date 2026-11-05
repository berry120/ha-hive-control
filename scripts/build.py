"""Build the installation ZIP and standalone preview with stable filenames."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

TEXT_SUFFIXES = {".py", ".js", ".json", ".yaml", ".yml", ".md", ".html", ".css"}


def file_bytes(path):
    # Keep archives identical across checkouts with different file times or line endings.
    return (
        path.read_text(encoding="utf-8").encode("utf-8")
        if path.suffix in TEXT_SUFFIXES
        else path.read_bytes()
    )


def build(root):
    root = Path(root).resolve()
    component = root / "custom_components" / "hive_local"
    strings = (component / "strings.json").read_text(encoding="utf-8")
    (component / "translations").mkdir(exist_ok=True)
    (component / "translations" / "en.json").write_text(strings, encoding="utf-8", newline="\n")
    output = root / "dist" / "hive-local-control.zip"
    output.parent.mkdir(exist_ok=True)
    files = [
        path
        for path in component.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    ]
    files.extend(root / name for name in ("README.md", "hive_zigbee_protocol_reference.md"))
    files.extend(
        path for path in (root / "docs").rglob("*") if path.is_file() and not path.is_symlink()
    )
    with ZipFile(output, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
            info = ZipInfo(path.relative_to(root).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, file_bytes(path), compresslevel=9)

    preview = (root / "preview" / "index.html").read_text(encoding="utf-8")
    card_script = (component / "frontend" / "hive-local-card.js").read_text(encoding="utf-8")
    demo_script = (root / "preview" / "demo.js").read_text(encoding="utf-8").split("\n", 1)[1]
    inline_script = (card_script + "\n" + demo_script).replace("</script", "<\\/script")
    preview = preview.replace(
        '<script type="module" src="./demo.js"></script>',
        '<script type="module">\n' + inline_script + "\n</script>",
    )
    (output.parent / "preview.html").write_text(preview, encoding="utf-8", newline="\n")
    return output


if __name__ == "__main__":
    print(build(Path(__file__).resolve().parents[1]))
