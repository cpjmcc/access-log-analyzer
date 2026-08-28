from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

size = 1024
blue = "#0052CC"
navy = "#172B4D"
white = "#FFFFFF"
image = Image.new("RGBA", (size, size), blue)
draw = ImageDraw.Draw(image)

# Rounded white report card.
margin = 150
draw.rounded_rectangle((margin, margin, size - margin, size - margin), radius=90, fill=white)
# Blue report lines.
for y, width in ((350, 390), (455, 470), (560, 310)):
    draw.rounded_rectangle((300, y, 300 + width, y + 38), radius=19, fill=blue)
# Navy analysis magnifier.
draw.ellipse((550, 550, 760, 760), outline=navy, width=42)
draw.line((710, 710, 840, 840), fill=navy, width=48)

Path("assets").mkdir(exist_ok=True)
image.save("assets/access-log-analyzer-icon.png")
