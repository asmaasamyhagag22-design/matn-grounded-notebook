"""Deterministic, calm 16:9 background assets for creative templates."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from matn_deck.color import rgb_from_hex

from .spec import CreativeSpec

SIZE = (2560, 1440)


def _u8(value: str) -> np.ndarray:
    return np.array(rgb_from_hex(value), dtype=float) * 255


def _grain(array: np.ndarray, rng: np.random.Generator, strength: float) -> np.ndarray:
    return np.clip(array + rng.normal(0, strength, (*array.shape[:2], 1)), 0, 255)


def render_background(spec: CreativeSpec, size: tuple[int, int] = SIZE) -> Image.Image:
    width, height = size
    rng = np.random.default_rng(spec.background.fixed_seed)
    from matn_deck.color import derive_roles
    roles = derive_roles(spec.seed_colors.primary, spec.seed_colors.accent, spec.mode, spec.seed_colors.surface,
                         spec.card_style.fill_alpha)
    base, primary, focus = (_u8(roles[k]) for k in ("surface", "primary", "focus"))
    decor = _u8(str(spec.background.parameters.get("decor_color", roles["focus"])))
    canvas = np.broadcast_to(base, (height, width, 3)).copy()
    kind = spec.background.generator
    if kind == "aurora":
        yy, xx = np.mgrid[0:height, 0:width]
        glow = float(spec.background.parameters.get("glow_strength", 1.0))  # edge glow only; the centre stays calm
        for color, cx, cy, radius, alpha in ((primary, -0.05, 0.12, 0.32, 0.28),
                                              (decor, 1.04, 0.86, 0.38, 0.22),
                                              (decor, 0.78, -0.12, 0.30, 0.12)):
            radius = radius / glow ** 0.5 if glow > 1 else radius  # brighter but tighter: the light stays at the edge
            dist = ((xx / width - cx) ** 2 + (yy / height - cy) ** 2) / (2 * radius ** 2)
            weight = (np.exp(-dist) * min(0.9, alpha * glow))[..., None]
            canvas = canvas * (1 - weight) + color * weight
        canvas = _grain(canvas, rng, float(spec.background.parameters.get("grain", 0.8)))
    elif kind == "paper":
        canvas = _grain(canvas, rng, float(spec.background.parameters.get("grain", 1.5)))
        wave = np.sin(np.linspace(0, 18 * np.pi, width))[None, :, None] * 0.5
        canvas = np.clip(canvas + wave, 0, 255)
    else:
        band = int(width * float(spec.background.parameters.get("band_width", 0.16)))
        canvas[:, :band] = primary
        image = Image.fromarray(canvas.astype("uint8"))
        draw = ImageDraw.Draw(image, "RGBA")
        step = max(24, int(spec.background.parameters.get("step", 64)))
        line = tuple(int(v) for v in focus) + (95,)
        for y in range(-step, height + step, step):
            for x in range(-step, band + step, step):
                r = step // 3
                points = [(x, y - r), (x + r, y), (x, y + r), (x - r, y)]
                draw.line(points + [points[0]], fill=line, width=max(1, step // 18))
        canvas = np.asarray(image, dtype=float)
    image = Image.fromarray(canvas.astype("uint8"))
    if spec.motif.type == "lotus":
        draw = ImageDraw.Draw(image, "RGBA")
        color = tuple(int(v) for v in primary) + (round(255 * spec.motif.opacity),)
        weight = float(spec.background.parameters.get("motif_weight", 1.0))  # line weight and extra petals
        motif_width = width * 0.09
        motif_height = height * 0.132
        scales = (0.7, 1.0, 1.35) if weight <= 1 else (0.55, 0.7, 0.85, 1.0, 1.17, 1.35)
        for origin_x, flip in ((0, 1), (width, -1)):
            for scale in scales:
                box = [origin_x, height - motif_height * scale,
                       origin_x + flip * motif_width * scale, height + motif_height * 0.21 * scale]
                draw.arc([min(box[0], box[2]), box[1], max(box[0], box[2]), box[3]], 195 if flip > 0 else 165,
                         345 if flip > 0 else 315, fill=color,
                         width=max(2, round(width * 0.00156 * scale * weight)))
    return image


def content_zone_variance(image: Image.Image) -> float:
    data = np.asarray(image.convert("RGB"), dtype=float)
    h, w = data.shape[:2]
    zone = data[round(h * 0.18):round(h * 0.84), round(w * 0.20):round(w * 0.84)]
    return float(np.mean(np.std(zone, axis=(0, 1))))


def decor_zone_metrics(image: Image.Image, content: tuple[float, float, float, float] = (0.2, 0.18, 0.64, 0.66)
                       ) -> dict[str, float | bool]:
    """Compare the calm content rectangle with everything around it, using normalized coordinates."""
    data = np.asarray(image.convert("RGB"), dtype=float)
    h, w = data.shape[:2]
    x, y, width, height = content
    x0, y0, x1, y1 = round(x * w), round(y * h), round((x + width) * w), round((y + height) * h)
    calm = data[y0:y1, x0:x1]
    mask = np.ones((h, w), dtype=bool)
    mask[y0:y1, x0:x1] = False
    edge = data[mask]
    content_std = float(np.std(calm, axis=(0, 1)).mean())
    edge_std = float(np.std(edge, axis=0).mean())
    mean_delta = float(np.linalg.norm(edge.mean(axis=0) - calm.mean(axis=(0, 1))))
    return {"content_std": content_std, "edge_std": edge_std, "mean_delta": mean_delta,
            "calm": content_std < 12, "perceptible": edge_std - content_std >= 0.5 or mean_delta >= 6}


def write_background(spec: CreativeSpec, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    render_background(spec).save(path, "JPEG", quality=88, optimize=True, progressive=True)
    return path
