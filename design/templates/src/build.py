"""Build the gallery templates listed in design/templates/src/gallery.json from installed Office themes.

For each entry: take the Office theme (or one of its built-in color variants, unpacked from the .thmx into a
standalone .thmx), run build_template.ps1 through PowerPoint, write theme.json and check the result with
matn_deck.templates.validate_template. Nothing is downloaded.

Usage: .venv\\Scripts\\python.exe design/templates/src/build.py [template_id ...]
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parent
ROOT = SRC.parents[2]
GALLERY = SRC.parent
WORK = ROOT / "out" / "template-build"
sys.path.insert(0, str(ROOT))
from matn_deck.templates import validate_template  # noqa: E402

THEME_DIRS = [Path(os.environ.get(var, "")) / "Microsoft Office" / "root" / "Document Themes 16"
              for var in ("ProgramFiles", "ProgramFiles(x86)")]
_CONTENT_TYPES = {
    "rels": "application/vnd.openxmlformats-package.relationships+xml",
    "xml": "application/xml",
    "jpeg": "image/jpeg",
    "png": "image/png",
}
_OVERRIDES = {
    r"theme/presentation\.xml": "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    r"theme/slideMasters/slideMaster\d+\.xml": "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml",
    r"theme/slideLayouts/slideLayout\d+\.xml": "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml",
    r"theme/theme/theme\d+\.xml": "application/vnd.openxmlformats-officedocument.theme+xml",
    r"theme/theme/themeManager\.xml": "application/vnd.openxmlformats-officedocument.themeManager+xml",
}


def theme_path(name: str) -> Path:
    for directory in THEME_DIRS:
        path = directory / f"{name}.thmx"
        if path.is_file():
            return path
    raise FileNotFoundError(f"OFFICE_THEME_NOT_INSTALLED:{name}")


def variant_modes(path: Path) -> dict[int, str]:
    """{variant number: "dark" | "light"} from each variant's slide-master color map (bg1 mapped to dk1 = dark)."""
    modes = {}
    with zipfile.ZipFile(path) as package:
        for name in package.namelist():
            match = re.fullmatch(r"themeVariants/variant(\d+)/theme/slideMasters/slideMaster1\.xml", name)
            if match:
                modes[int(match.group(1))] = "dark" if 'bg1="dk1"' in package.read(name).decode("utf-8") else "light"
    return dict(sorted(modes.items()))


def variant_thmx(path: Path, variant: int, out: Path) -> Path:
    """Unpack themeVariants/variant<N>/ of an installed .thmx into a standalone .thmx PowerPoint can apply."""
    prefix = f"themeVariants/variant{variant}/"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        parts = [n for n in source.namelist() if n.startswith(prefix) and not n.endswith("/")]
        if not parts:
            raise ValueError(f"THEME_VARIANT_MISSING:{path.stem}:{variant}")
        overrides = []
        for name in parts:
            inner = name[len(prefix):]
            target.writestr(inner, source.read(name))
            for pattern, content_type in _OVERRIDES.items():
                if re.fullmatch(pattern, inner):
                    overrides.append(f'<Override PartName="/{inner}" ContentType="{content_type}"/>')
        defaults = "".join(f'<Default Extension="{ext}" ContentType="{ct}"/>' for ext, ct in _CONTENT_TYPES.items())
        target.writestr("[Content_Types].xml",
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                        f"{defaults}{''.join(overrides)}</Types>")
    return out


def build(entry: dict) -> None:
    source = theme_path(entry["theme"])
    thmx = source
    if entry.get("variant"):
        thmx = variant_thmx(source, entry["variant"], WORK / f"{entry['id']}.thmx")
    folder = GALLERY / entry["id"]
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SRC / "build_template.ps1"),
                    "-Thmx", str(thmx), "-OutPptx", str(folder / "template.pptx"),
                    "-Thumbnail", str(folder / "thumbnail.png"), "-HeadingFont", entry["fonts"]["heading"],
                    "-BodyFont", entry["fonts"]["body"], "-Label", entry["name_en"]], check=True, cwd=ROOT)
    meta = {key: entry[key] for key in ("id", "name_ar", "name_en", "fonts", "mode")}
    meta["source"] = f"Office theme {entry['theme']}" + (f" (variant {entry['variant']})" if entry.get("variant") else "")
    (folder / "theme.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_template(folder / "template.pptx")
    if not report.ok:
        raise SystemExit(f"{entry['id']}: template invalid: {report.errors}")
    print(f"{entry['id']}: ok ({(folder / 'template.pptx').stat().st_size // 1024} KB)")


def main(ids: list[str]) -> int:
    entries = json.loads((SRC / "gallery.json").read_text(encoding="utf-8"))["templates"]
    for entry in entries:
        if not ids or entry["id"] in ids:
            build(entry)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
