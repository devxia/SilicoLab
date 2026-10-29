"""Generate a quiet 660 × 420 pt Finder drag-to-install background."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parents[2] / "build" / "dmg"
root.mkdir(parents=True, exist_ok=True)
scale = 2
image = Image.new('RGB', (660 * scale, 420 * scale), '#f6f6f6')
draw = ImageDraw.Draw(image)
regular = '/System/Library/Fonts/Supplemental/Arial.ttf'
bold = '/System/Library/Fonts/Supplemental/Arial Bold.ttf'
chinese = '/System/Library/Fonts/Supplemental/Arial Unicode.ttf'

def text(value, position, size, color, face=regular):
    font = ImageFont.truetype(face, size * scale)
    draw.text((position[0] * scale, position[1] * scale), value, font=font, fill=color, anchor='mt')

text('SilicoLab', (330, 38), 29, '#191919', bold)
text('将应用拖入 Applications 文件夹', (330, 87), 16, '#777777', chinese)
# Finder draws an 80 pt icon plus a 13 pt filename beneath it. The combined
# visual group is centered about 15 pt below the icon coordinate (y=226).
frame_side = 148
group_center_y = 241
for center_x in [180, 480]:
    half = frame_side / 2
    bounds = ((center_x - half) * scale, (group_center_y - half) * scale,
              (center_x + half) * scale, (group_center_y + half) * scale)
    draw.rounded_rectangle(bounds, radius=24 * scale, fill='#ffffff', outline='#e8e8e8', width=scale)
draw.line([(294 * scale, group_center_y * scale), (365 * scale, group_center_y * scale)], fill='#909090', width=3 * scale)
draw.line([(353 * scale, (group_center_y - 12) * scale), (365 * scale, group_center_y * scale), (353 * scale, (group_center_y + 12) * scale)], fill='#909090', width=3 * scale, joint='curve')
text('拖拽安装', (330, 278), 12, '#999999', chinese)
# Reserve at least 70 pt below the footer for Finder's tab/path/status chrome.
text('安装完成后，推出镜像并从“应用程序”打开', (330, 330), 12, '#999999', chinese)
image.save(root / 'dmg-background@2x.png', dpi=(144, 144))
image.resize((660, 420), Image.Resampling.LANCZOS).save(root / 'dmg-background.png', dpi=(72, 72))
print(root / 'dmg-background.png')
