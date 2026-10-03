"""Small, dependency-free color system for spec-driven creative templates.

All public RGB tuples use encoded sRGB components in the 0..1 range. OKLab follows
Bjorn Ottosson's reference matrices; OKLCH uses radians internally.
"""
from __future__ import annotations

import math

RGB = tuple[float, float, float]
OKLab = tuple[float, float, float]
OKLCH = tuple[float, float, float]


def srgb_to_linear(rgb: RGB) -> RGB:
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb)  # type: ignore[return-value]


def linear_to_srgb(rgb: RGB) -> RGB:
    def one(c: float) -> float:
        c = min(1.0, max(0.0, c))
        return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return tuple(one(c) for c in rgb)  # type: ignore[return-value]


def linear_to_oklab(rgb: RGB) -> OKLab:
    r, g, b = rgb
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = math.copysign(abs(l) ** (1 / 3), l), math.copysign(abs(m) ** (1 / 3), m), math.copysign(abs(s) ** (1 / 3), s)
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def oklab_to_linear(lab: OKLab) -> RGB:
    light, a, b = lab
    l_ = light + 0.3963377774 * a + 0.2158037573 * b
    m_ = light - 0.1055613458 * a - 0.0638541728 * b
    s_ = light - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def oklab_to_oklch(lab: OKLab) -> OKLCH:
    light, a, b = lab
    return light, math.hypot(a, b), math.atan2(b, a)


def oklch_to_oklab(lch: OKLCH) -> OKLab:
    light, chroma, hue = lch
    return light, chroma * math.cos(hue), chroma * math.sin(hue)


def srgb_to_oklch(rgb: RGB) -> OKLCH:
    return oklab_to_oklch(linear_to_oklab(srgb_to_linear(rgb)))


def oklch_to_srgb(lch: OKLCH) -> RGB:
    return linear_to_srgb(oklab_to_linear(oklch_to_oklab(lch)))


def relative_luminance(rgb: RGB) -> float:
    r, g, b = srgb_to_linear(rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: RGB, b: RGB) -> float:
    high, low = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def blend(top: RGB, bottom: RGB, alpha: float) -> RGB:
    return tuple(alpha * t + (1 - alpha) * b for t, b in zip(top, bottom))  # type: ignore[return-value]


def rgb_from_hex(value: str) -> RGB:
    value = value.removeprefix("#")
    if len(value) != 6 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise ValueError(f"COLOR_NOT_HEX:{value}")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(rgb: RGB) -> str:
    return "".join(f"{round(min(1, max(0, c)) * 255):02X}" for c in rgb)


def _tone(seed: RGB, lightness: float, chroma_scale: float = 1.0) -> RGB:
    _, chroma, hue = srgb_to_oklch(seed)
    # Reduce chroma until the un-clipped linear value is in gamut, preserving hue.
    chroma *= chroma_scale
    for _ in range(30):
        linear = oklab_to_linear(oklch_to_oklab((lightness, chroma, hue)))
        if all(-1e-6 <= c <= 1 + 1e-6 for c in linear):
            return linear_to_srgb(linear)
        chroma *= 0.9
    return linear_to_srgb(linear)


def _contrasting_tone(seed: RGB, background: RGB, target: float, prefer_light: bool) -> RGB:
    levels = [i / 200 for i in range(201)]
    levels.sort(key=lambda value: (not (value >= 0.5) if prefer_light else value >= 0.5,
                                   abs(value - srgb_to_oklch(seed)[0])))
    candidates = [_tone(seed, level) for level in levels]
    passing = [rgb for rgb in candidates if contrast_ratio(rgb, background) >= target]
    if not passing:
        return (1.0, 1.0, 1.0) if prefer_light else (0.0, 0.0, 0.0)
    original_l = srgb_to_oklch(seed)[0]
    return min(passing, key=lambda rgb: abs(srgb_to_oklch(rgb)[0] - original_l))


def _contrasting_glass_tone(seed: RGB, background: RGB, alpha: float, target: float, prefer_light: bool) -> RGB:
    """Text tone that clears `target` on both the base and its own translucent glass tint."""
    if alpha <= 0:
        return _contrasting_tone(seed, background, target, prefer_light)
    levels = [i / 200 for i in range(201)]
    original_l = srgb_to_oklch(seed)[0]
    passing = []
    for level in levels:
        foreground = _tone(seed, level)
        glass = blend(foreground, background, alpha)
        if contrast_ratio(foreground, background) >= target and contrast_ratio(foreground, glass) >= target:
            passing.append(foreground)
    if not passing:
        return (1.0, 1.0, 1.0) if prefer_light else (0.0, 0.0, 0.0)
    side = [rgb for rgb in passing if (srgb_to_oklch(rgb)[0] >= 0.5) == prefer_light]
    return min(side or passing, key=lambda rgb: abs(srgb_to_oklch(rgb)[0] - original_l))


def derive_roles(seed: str, accent_seed: str, mode: str, surface_seed: str | None = None,
                 card_alpha: float = 0.0) -> dict[str, str]:
    """Derive accessible theme roles from two seed colors in perceptual OKLCH space."""
    if mode not in {"light", "dark"}:
        raise ValueError(f"MODE_INVALID:{mode}")
    base, accent_base = rgb_from_hex(seed), rgb_from_hex(accent_seed)
    surface_base = rgb_from_hex(surface_seed) if surface_seed else base
    dark = mode == "dark"
    surface = _tone(surface_base, 0.13 if dark else 0.97, 0.18)
    on_surface = _contrasting_glass_tone(base, surface, card_alpha, 4.5, prefer_light=dark)
    muted = _contrasting_glass_tone(_tone(base, 0.72 if dark else 0.43, 0.22), surface, card_alpha, 4.5,
                                    prefer_light=dark)
    primary = _contrasting_tone(base, surface, 4.5, prefer_light=dark)
    # On light templates the vivid seed is a focus fill, never text. Text accents stay with the dark primary.
    accent = _contrasting_tone(accent_base, surface, 4.5, prefer_light=True) if dark else primary
    focus = _contrasting_tone(accent_base, surface, 3.0, prefer_light=dark)
    card = _tone(surface_base, 0.20 if dark else 0.93, 0.12)
    divider = _tone(base, 0.24 if dark else 0.31, 0.8)
    on_divider = _contrasting_tone(accent_base, divider, 4.5, prefer_light=True)
    roles = {"primary": primary, "accent": accent, "focus": focus, "surface": surface, "on_surface": on_surface,
             "muted": muted, "card": card, "divider_background": divider, "on_divider": on_divider}
    return {name: rgb_to_hex(value) for name, value in roles.items()}
