"""Build the static demo site's local, uncropped 16:9 image and download assets.

The source for a deck image is always a per-slide export, never a contact sheet.  PIL
uses contain + padding, so no source pixels are cropped.  Generated output lives under
``out/demo_site`` and is deliberately ignored by git like the rest of ``out/``.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image, ImageOps

from matn_deck.demo_data import gallery_entries

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "out" / "demo"
OUTPUT = ROOT / "out" / "demo_site"
MANIFEST = DEMO / "manifest.json"
DOCUMENT_ORDER = ("wb_eem_2021_12", "gao_21_519sp", "2601.14525v1")
BACKGROUND = (247, 246, 242)

TIMELINE = (
    {
        "version": "v0",
        "title": "أول تصميم",
        "sentence": "أول proof إن المستند يقدر يتحول لعرض كامل بمصادره.",
        "sources": tuple(ROOT / "output" / "phase04a-english-demo" / "slide-previews" / f"Slide{i}.PNG"
                         for i in (1, 2, 4)),
    },
    {
        "version": "2b",
        "title": "PowerPoint templates",
        "sentence": "نقلنا التصميم لقوالب PowerPoint حقيقية قابلة للتعديل.",
        "sources": tuple(ROOT / "out" / "gallery" / "integral-light" / "png_v2" / f"slide_{i:02}.png"
                         for i in (1, 4, 7)),
    },
    {
        "version": "2c",
        "title": "Smart layout",
        "sentence": "الـ renderer بقى يولّد بدائل ويختار layout بالقواعد والـ score.",
        "sources": tuple(ROOT / "out" / "gallery" / "integral-light" / "png_v3" / f"slide_{i:02}.png"
                         for i in (1, 4, 7)),
    },
    {
        "version": "2c.1",
        "title": "Polish",
        "sentence": "المساحات والخطوط والكروت اتظبطت على الحبر الحقيقي في الصورة.",
        "sources": tuple(ROOT / "out" / "gallery" / "history" / "2d" / "modulo" / "png" /
                         f"slide_{i:02}.png" for i in (1, 4, 7)),
    },
    {
        "version": "2d",
        "title": "Creative family",
        "sentence": "ليل النيل وبردي ومشربية أضافوا عيلة إبداعية من غير كسر القواعد.",
        "sources": tuple(ROOT / "out" / "gallery" / "mashrabiya" / "png" / f"slide_{i:02}.png"
                         for i in (1, 4, 7)),
    },
    {
        "version": "النسخة الحالية",
        "title": "تلميع الليلة",
        "sentence": "contrast أوضح، Modulo مضبوط، وموقع ديمو ثابت يفتح أوفلاين.",
        "current": True,
        "sources": tuple(DEMO / "decks" / "wb_eem_2021_12" / "modulo" / "png" /
                         f"slide_{i:02}.png" for i in (1, 4, 7)),
    },
)


def _rel(path: Path, output: Path) -> str:
    return path.relative_to(output).as_posix()


def fit_16_9(source: Path, target: Path, width: int, *, quality: int = 84) -> None:
    """Write an exact 16:9 JPEG using padding only; never crop the source."""
    height = round(width * 9 / 16)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_mtime >= source.stat().st_mtime:
        try:
            with Image.open(target) as cached:
                if cached.size == (width, height):
                    return
        except OSError:
            pass
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
        contained = ImageOps.contain(image, (width, height), method=Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (width, height), (*BACKGROUND, 255))
        left = (width - contained.width) // 2
        top = (height - contained.height) // 2
        canvas.alpha_composite(contained, (left, top))
        canvas.convert("RGB").save(target, "JPEG", quality=quality, optimize=True, progressive=True)


def load_manifest() -> dict:
    if not MANIFEST.is_file():
        raise FileNotFoundError("Demo cache is missing: build out/demo before the static site")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _all_decks(manifest: dict) -> list[dict]:
    decks = []
    documents = manifest["documents"]
    order = [key for key in DOCUMENT_ORDER if key in documents]
    order += [key for key in documents if key not in order]
    for doc_key in order:
        document = documents[doc_key]
        for template_id, deck in document.get("decks", {}).items():
            decks.append({
                "id": f"{doc_key}--{template_id}",
                "doc_key": doc_key,
                "template_id": template_id,
                "title": document["title"],
                "publisher": document["publisher"],
                "source": deck,
            })
    return decks


def missing_inputs() -> list[str]:
    """Every local cache input build_assets needs but cannot find (out/ and output/ are git-ignored)."""
    if not MANIFEST.is_file():
        return [str(MANIFEST)]
    sources = [ROOT / name for deck in _all_decks(load_manifest())
               for name in (*deck["source"]["pngs"], deck["source"]["pptx"], deck["source"]["pdf"]) if name]
    sources += [source for step in TIMELINE for source in step["sources"]]
    return [str(path) for path in sources if not path.is_file()]


def build_assets(output: Path = OUTPUT) -> dict:
    """Create all Part 1 assets and return their relative-path inventory."""
    output = Path(output)
    assets = output / "assets"
    files = output / "files"
    assets.mkdir(parents=True, exist_ok=True)
    files.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    decks = _all_decks(manifest)

    built_decks: list[dict] = []
    for deck in decks:
        deck_id = deck["id"]
        source = deck.pop("source")
        grid, viewer = [], []
        for number, source_name in enumerate(source["pngs"], start=1):
            slide_source = ROOT / source_name
            if not slide_source.is_file():
                raise FileNotFoundError(slide_source)
            grid_target = assets / "decks" / deck_id / "grid" / f"slide_{number:02}.jpg"
            viewer_target = assets / "decks" / deck_id / "viewer" / f"slide_{number:02}.jpg"
            fit_16_9(slide_source, grid_target, 960)
            fit_16_9(slide_source, viewer_target, 1920)
            grid.append(_rel(grid_target, output))
            viewer.append(_rel(viewer_target, output))
        copied = {}
        for extension in ("pptx", "pdf"):
            source_file = ROOT / source[extension]
            if not source_file.is_file():
                raise FileNotFoundError(source_file)
            target = files / f"{deck_id}.{extension}"
            shutil.copy2(source_file, target)
            copied[extension] = _rel(target, output)
        built_decks.append({**deck, "grid": grid, "viewer": viewer, **copied})

    by_template: dict[str, dict] = {}
    for deck in built_decks:  # already in explicit document preference order
        by_template.setdefault(deck["template_id"], deck)

    templates = []
    for entry in gallery_entries():
        template_id = entry["id"]
        primary = by_template.get(template_id)
        source = ROOT / manifest["documents"][primary["doc_key"]]["decks"][template_id]["pngs"][0] \
            if primary else Path(entry["thumbnail"])
        cover = assets / "covers" / f"{template_id}.jpg"
        fit_16_9(source, cover, 960)
        templates.append({
            "id": template_id,
            "name_ar": entry["name_ar"],
            "name_en": entry["name_en"],
            "mood": entry["mood"],
            "family": entry["family"],
            "mode": entry["mode"],
            "default": entry["default"],
            "cover": _rel(cover, output),
            "primary_deck_id": primary["id"] if primary else None,
        })

    timeline = []
    for step in TIMELINE:
        images = []
        for number, source in enumerate(step["sources"], start=1):
            if not source.is_file():
                raise FileNotFoundError(source)
            target = assets / "timeline" / str(step["version"]).replace(" ", "-") / f"slide_{number:02}.jpg"
            fit_16_9(source, target, 960)
            images.append(_rel(target, output))
        timeline.append({key: value for key, value in step.items() if key != "sources"} | {"images": images})

    result = {"templates": templates, "decks": built_decks, "timeline": timeline}
    (output / "assets.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    inventory = build_assets()
    print(f"Built {len(inventory['templates'])} covers and {len(inventory['decks'])} decks in {OUTPUT}")
