from django.conf import settings
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont


def generate_og_image(title, subtitle=None):
    """
    Generate Open Graph image dynamically.

    Args:
        title: Main title text
        subtitle: Optional subtitle text

    Returns:
        BytesIO object containing PNG image
    """
    width = 1200
    height = 630

    # Create gradient background
    img = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(img)

    # Create purple gradient (similar to landing page)
    for y in range(height):
        r = int(102 + (118 - 102) * y / height)
        g = int(126 + (75 - 126) * y / height)
        b = int(234 + (162 - 234) * y / height)
        draw.rectangle([(0, y), (width, y + 1)], fill=(r, g, b))

    # Try to use system fonts, fall back to default
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 72)
        subtitle_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 40)
    except:
        try:
            title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
            subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
        except:
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()

    # Draw title
    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_width = title_bbox[2] - title_bbox[0]
    title_height = title_bbox[3] - title_bbox[1]
    title_x = (width - title_width) // 2
    title_y = 200 if subtitle else (height - title_height) // 2

    draw.text((title_x, title_y), title, fill='white', font=title_font)

    # Draw subtitle if provided
    if subtitle:
        subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
        subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
        subtitle_x = (width - subtitle_width) // 2
        subtitle_y = title_y + title_height + 30

        draw.text((subtitle_x, subtitle_y), subtitle, fill=(255, 255, 255, 230), font=subtitle_font)

    # Save to BytesIO
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)

    return buffer
