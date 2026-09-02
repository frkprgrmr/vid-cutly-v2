from pathlib import Path

from PIL import Image, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
BACKGROUND = Path(
    "/home/umam/.codex/generated_images/01a060e6-0c14-72e3-92c5-87dc3be041bb/"
    "exec-50f47817-71c4-4adb-b8f9-8a629ff556cd.png"
)
LOGO = ROOT / "assets" / "clipper-magang954-watermark.png"
OUTPUT = ROOT / "assets" / "youtube-banner-clipper-magang.png"

CANVAS_SIZE = (2560, 1440)
SAFE_SIZE = (1546, 423)


def main() -> None:
    background = Image.open(BACKGROUND).convert("RGB")
    background = background.resize(CANVAS_SIZE, Image.Resampling.LANCZOS).convert("RGBA")

    logo = Image.open(LOGO).convert("RGBA")
    target_width = 1260
    target_height = round(logo.height * target_width / logo.width)
    logo = logo.resize((target_width, target_height), Image.Resampling.LANCZOS)

    x = (CANVAS_SIZE[0] - logo.width) // 2
    y = (CANVAS_SIZE[1] - logo.height) // 2

    safe_left = (CANVAS_SIZE[0] - SAFE_SIZE[0]) // 2
    safe_top = (CANVAS_SIZE[1] - SAFE_SIZE[1]) // 2
    assert x >= safe_left and x + logo.width <= safe_left + SAFE_SIZE[0]
    assert y >= safe_top and y + logo.height <= safe_top + SAFE_SIZE[1]

    shadow = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    shadow_alpha = logo.getchannel("A").filter(ImageFilter.GaussianBlur(18))
    shadow_layer = Image.new("RGBA", logo.size, (0, 0, 0, 190))
    shadow_layer.putalpha(shadow_alpha.point(lambda value: value * 3 // 4))
    shadow.alpha_composite(shadow_layer, (x, y + 14))

    background = Image.alpha_composite(background, shadow)
    background.alpha_composite(logo, (x, y))
    background.convert("RGB").save(OUTPUT, quality=95)


if __name__ == "__main__":
    main()
