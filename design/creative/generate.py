r"""Build the creative gallery from data-only specs, then run the shared gallery QA.

Usage: .venv\Scripts\python.exe design/creative/generate.py [template_id ...] [--skip-qa]
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

from lxml import etree
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = ROOT / "out" / "creative-build"
TEMPLATES = ROOT / "design" / "templates"
sys.path.insert(0, str(ROOT))

from design.creative.backgrounds import content_zone_variance, decor_zone_metrics, write_background  # noqa: E402
from design.creative.spec import CreativeSpec, load_spec  # noqa: E402
from design.templates.src import build as classic  # noqa: E402
from matn_deck.color import contrast_ratio, derive_roles, rgb_from_hex  # noqa: E402
from matn_deck.templates import validate_template  # noqa: E402

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS = {"a": _A}


def specs() -> dict[str, tuple[Path, CreativeSpec]]:
    found = {}
    for path in sorted(HERE.glob("*/spec.json")):
        spec = load_spec(path)
        if spec.id in found:
            raise ValueError(f"SPEC_ID_DUPLICATE:{spec.id}")
        found[spec.id] = (path, spec)
    return found


def _replace_color(parent, slot: str, value: str) -> None:
    element = parent.find(f"a:{slot}", _NS)
    if element is None:
        return
    for child in list(element):
        element.remove(child)
    etree.SubElement(element, f"{{{_A}}}srgbClr", {"val": value})


def _theme_xml(blob: bytes, roles: dict[str, str], spec: CreativeSpec) -> bytes:
    root = etree.fromstring(blob)
    scheme = root.find(".//a:clrScheme", _NS)
    mapping = {
        "dk1": roles["on_surface"], "lt1": roles["surface"], "dk2": roles["muted"], "lt2": roles["card"],
        "accent1": roles["accent"], "accent2": roles["focus"], "accent3": roles["muted"],
        "accent4": roles["primary"], "accent5": roles["accent"], "accent6": roles["muted"],
        "hlink": roles["primary"], "folHlink": roles["muted"],
    }
    for slot, value in mapping.items():
        _replace_color(scheme, slot, value)
    for branch, face in (("majorFont", spec.fonts.title), ("minorFont", spec.fonts.body)):
        for tag in ("latin", "cs"):
            element = root.find(f".//a:fontScheme/a:{branch}/a:{tag}", _NS)
            if element is not None:
                element.set("typeface", face)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def creative_theme(source: Path, target: Path, roles: dict[str, str], spec: CreativeSpec) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as after:
        for item in before.infolist():
            data = before.read(item.filename)
            if re.fullmatch(r"theme/theme/theme\d+\.xml", item.filename):
                data = _theme_xml(data, roles, spec)
            after.writestr(item, data)
    return target


def build(path: Path, spec: CreativeSpec) -> None:
    roles = derive_roles(spec.seed_colors.primary, spec.seed_colors.accent, spec.mode, spec.seed_colors.surface,
                         spec.card_style.fill_alpha)
    asset = write_background(spec, WORK / spec.id / "background.jpg")
    variance = content_zone_variance(Image.open(asset))
    if variance >= 12:
        raise ValueError(f"BACKGROUND_CONTENT_VARIANCE:{spec.id}:{variance:.2f}")
    theme = creative_theme(classic.theme_path("Integral"), WORK / spec.id / "theme.thmx", roles, spec)
    layouts = classic.expanded_layouts(WORK / spec.id / "layouts.json")
    area_out = WORK / spec.id / "area.json"
    folder = TEMPLATES / spec.id
    folder.mkdir(parents=True, exist_ok=True)
    divider = spec.divider_style
    fills = [roles["divider_background"]]
    if divider.type == "gradient":
        secondary = divider.secondary or f"#{roles['primary']}"
        fills.append(derive_roles(secondary, spec.seed_colors.accent, "dark", secondary)["divider_background"])
    pattern = "mashrabiya" if spec.pattern and spec.motif.type == "mashrabiya" else "lines" if spec.pattern else ""
    safe_left = 0.0
    if spec.background.generator == "mashrabiya":
        safe_left = 960 * (float(spec.background.parameters.get("band_width", 0.16)) +
                           float(spec.background.parameters.get("gutter", 0.03)))
    command = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(classic.SRC / "build_template.ps1"),
        "-Thmx", str(theme), "-OutPptx", str(folder / "template.pptx"), "-Thumbnail", str(folder / "thumbnail.png"),
        "-HeadingFont", spec.fonts.title, "-BodyFont", spec.fonts.body, "-Label", spec.name_en,
        "-LayoutsJson", str(layouts), "-AreaOut", str(area_out), "-AccentBrightness", "0",
        "-DividerFill", fills[0], "-DividerText", roles["on_divider"],
        "-DividerNumberColor", roles["on_divider"], "-DividerStyle", divider.type,
        "-BackgroundImage", str(asset), "-CleanThemeArt",
    ]
    if safe_left:
        command += ["-SafeLeftPt", str(round(safe_left, 2))]
    if len(fills) == 2:
        command += ["-DividerFill2", fills[1]]
    if pattern:
        command += ["-Pattern", pattern]
    if divider.thin_rules:
        command.append("-ThinRules")
    subprocess.run(command, check=True, cwd=ROOT)
    area = json.loads(area_out.read_text(encoding="utf-8-sig"))
    art = decor_zone_metrics(Image.open(asset), (area["left"] / 960, area["top"] / 540,
                                                  area["width"] / 960, area["height"] / 540))
    if not art["calm"]:
        raise ValueError(f"BACKGROUND_CONTENT_NOT_CALM:{spec.id}:{art['content_std']:.2f}")
    if not art["perceptible"]:
        raise ValueError(f"BACKGROUND_ART_NOT_PERCEPTIBLE:{spec.id}:{art}")
    divider_meta = {"fill": fills, "text": roles["on_divider"],
                    "contrast": round(min(contrast_ratio(rgb_from_hex(fill), rgb_from_hex(roles["on_divider"]))
                                          for fill in fills), 2),
                    "safe": json.loads((classic.SRC / "layouts.json").read_text(encoding="utf-8"))["divider"]["safe"]}
    divider_style = divider.model_dump()
    divider_style["outline_color"] = roles["on_divider"]
    divider_style["outline_width_pt"] = 4.5 if divider.type == "outline_number" else 0.0
    meta = {
        "id": spec.id, "name_ar": spec.name_ar, "name_en": spec.name_en,
        "fonts": {"heading": spec.fonts.title, "body": spec.fonts.body}, "mode": spec.mode,
        "source": str(path.relative_to(ROOT)).replace("\\", "/"),
        "content_area_pt": [round(area[k], 2) for k in ("left", "top", "width", "height")],
        "divider": divider_meta, "pattern": pattern or None, "glow": False,
        "family": spec.family, "mood": spec.mood, "audience": spec.recommended_audience,
        "roles": roles, "card_style": spec.card_style.model_dump(), "divider_style": divider_style,
        "background": {**spec.background.model_dump(), "asset": "embedded:creative_background",
                       "content_variance": round(float(art["content_std"]), 3),
                       "edge_variance": round(float(art["edge_std"]), 3),
                       "edge_mean_delta": round(float(art["mean_delta"]), 3),
                       "art_perceptible": bool(art["perceptible"])},
        "decor_zone": {"safe_left_pt": round(safe_left, 2),
                       "band_right_pt": round(960 * float(spec.background.parameters.get("band_width", 0)), 2)},
    }
    (folder / "theme.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate_template(folder / "template.pptx")
    size = (folder / "template.pptx").stat().st_size
    if not report.ok:
        raise RuntimeError(f"{spec.id}: template invalid: {report.errors}")
    if size >= 5 * 1024 * 1024:
        raise RuntimeError(f"{spec.id}: TEMPLATE_OVER_5_MB:{size}")
    print(f"{spec.id}: ok ({size // 1024} KB, background variance {variance:.2f})")


def main(argv: list[str]) -> int:
    skip_qa = "--skip-qa" in argv
    wanted = {arg for arg in argv if not arg.startswith("--")}
    found = specs()
    missing = wanted - set(found)
    if missing:
        raise SystemExit(f"UNKNOWN_CREATIVE_SPEC:{','.join(sorted(missing))}")
    for template_id, (path, spec) in found.items():
        if not wanted or template_id in wanted:
            build(path, spec)
    if not skip_qa:
        from design.templates.src.qa import main as qa
        return qa()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
