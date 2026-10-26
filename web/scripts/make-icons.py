from pathlib import Path
from PIL import Image, ImageDraw

# Code-drawn version of the app's existing flag mark; no third-party branding.
out = Path('public/icons')
out.mkdir(parents=True, exist_ok=True)
for size in [192, 512]:
    image = Image.new('RGB', (size, size), '#0b0f14')
    draw = ImageDraw.Draw(image)
    def points(values):
        return [(round(x * size), round(y * size)) for x, y in values]
    width = max(3, round(size * .025))
    draw.line(points([(.32,.76),(.32,.25)]), fill='#2ecc71', width=width)
    draw.line(points([(.32,.26),(.46,.23),(.59,.30),(.70,.26),(.70,.49),(.59,.53),(.46,.46),(.32,.49)]), fill='#2ecc71', width=width, joint='curve')
    draw.line(points([(.23,.77),(.48,.77)]), fill='#2ecc71', width=width)
    image.save(out / f'icon-{size}.png')
