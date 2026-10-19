from PIL import Image, ImageDraw, ImageFilter, ImageFont
import subprocess, shutil
from pathlib import Path
S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
# fond dégradé arrondi (style macOS)
grad = Image.new("RGBA", (S, S))
g = ImageDraw.Draw(grad)
for y in range(S):
    t = y / S
    g.line([(0, y), (S, y)], fill=(int(255 - 40 * t), int(94 - 50 * t), int(58 + 30 * t), 255))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle((100, 100, 924, 924), radius=185, fill=255)
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle((100, 118, 924, 942), radius=185, fill=(0, 0, 0, 110))
img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
img.paste(grad, (0, 0), mask)
d = ImageDraw.Draw(img)
# deux documents qui se transforment
d.rounded_rectangle((250, 260, 560, 660), radius=34, fill=(255, 255, 255, 235))
d.polygon([(470, 260), (560, 350), (470, 350)], fill=(255, 210, 190, 255))
for i in range(5):
    d.rounded_rectangle((290, 400 + i * 45, 520 - (60 if i == 4 else 0), 420 + i * 45), radius=8, fill=(240, 120, 90, 255))
d.rounded_rectangle((470, 380, 780, 780), radius=34, fill=(255, 255, 255, 255), outline=(255, 255, 255, 255))
f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 120, index=1)
d.text((625, 560), "PDF", font=f, fill=(225, 60, 50, 255), anchor="mm")
d.rounded_rectangle((515, 650, 735, 680), radius=10, fill=(255, 190, 170, 255))
# flèche de conversion
d.line([(330, 760), (430, 760)], fill=(255, 255, 255, 255), width=34)
d.polygon([(420, 715), (480, 760), (420, 805)], fill=(255, 255, 255, 255))
iconset = Path("FileForge.iconset"); shutil.rmtree(iconset, ignore_errors=True); iconset.mkdir()
for s in (16, 32, 128, 256, 512):
    img.resize((s, s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
    img.resize((s * 2, s * 2), Image.LANCZOS).save(iconset / f"icon_{s}x{s}@2x.png")
subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", "FileForge.icns"], check=True)
img.save("icon.png")
print("icon ok")
