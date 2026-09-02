from pathlib import Path

from PIL import Image, ImageDraw


output = Path(__file__).resolve().parents[1] / "assets" / "youtube-source-icon.png"
output.parent.mkdir(parents=True, exist_ok=True)

image = Image.new("RGBA", (96, 68), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((2, 5, 94, 63), radius=18, fill=(255, 0, 51, 255))
draw.polygon(((40, 20), (40, 48), (67, 34)), fill=(255, 255, 255, 255))
image.save(output)
