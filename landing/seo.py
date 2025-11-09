from django.conf import settings
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont


def wrap_text(text, font, max_width, draw):
    """Wrap text to fit within max_width."""
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = ' '.join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
                current_line = [word]
            else:
                lines.append(word)

    if current_line:
        lines.append(' '.join(current_line))

    return lines


def generate_og_image(title, subtitle=None):
    """
    Generate Open Graph image dynamically with professional design.

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

    # Create modern gradient (indigo to purple)
    for y in range(height):
        # Indigo to purple gradient
        r = int(79 + (147 - 79) * y / height)
        g = int(70 + (51 - 70) * y / height)
        b = int(229 + (234 - 229) * y / height)
        draw.rectangle([(0, y), (width, y + 1)], fill=(r, g, b))

    # Add subtle overlay pattern (circles in corners)
    overlay_color = (255, 255, 255, 15)
    draw.ellipse([(-100, -100), (300, 300)], fill=overlay_color)
    draw.ellipse([(900, 400), (1400, 900)], fill=overlay_color)

    # Try to use system fonts with multiple fallbacks
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 76)
        subtitle_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 42)
        brand_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 38)
    except:
        try:
            title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 76)
            subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 42)
            brand_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 38)
        except:
            try:
                # Linux alternative fonts
                title_font = ImageFont.truetype("/usr/share/fonts/liberation/LiberationSans-Bold.ttf", 76)
                subtitle_font = ImageFont.truetype("/usr/share/fonts/liberation/LiberationSans-Regular.ttf", 42)
                brand_font = ImageFont.truetype("/usr/share/fonts/liberation/LiberationSans-Bold.ttf", 38)
            except:
                title_font = ImageFont.load_default()
                subtitle_font = ImageFont.load_default()
                brand_font = ImageFont.load_default()

    # Add brand logo/icon in top left (simple circle with "B")
    logo_x, logo_y = 60, 50
    logo_size = 70
    draw.ellipse([logo_x, logo_y, logo_x + logo_size, logo_y + logo_size], fill='white')
    draw.ellipse([logo_x + 3, logo_y + 3, logo_x + logo_size - 3, logo_y + logo_size - 3], fill=(79, 70, 229))

    # Draw "Blik360" brand name next to logo
    draw.text((logo_x + logo_size + 20, logo_y + 15), "Blik360", fill='white', font=brand_font)

    # Calculate text positioning
    content_y_start = 220
    max_text_width = width - 120  # 60px padding on each side

    # Wrap title text if needed
    title_lines = wrap_text(title, title_font, max_text_width, draw)

    # Draw title (centered, multi-line support)
    current_y = content_y_start
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        line_width = bbox[2] - bbox[0]
        line_height = bbox[3] - bbox[1]
        x = (width - line_width) // 2

        # Add subtle shadow for depth
        draw.text((x + 2, current_y + 2), line, fill=(0, 0, 0, 80), font=title_font)
        draw.text((x, current_y), line, fill='white', font=title_font)
        current_y += line_height + 20

    # Draw subtitle if provided
    if subtitle:
        current_y += 20
        subtitle_lines = wrap_text(subtitle, subtitle_font, max_text_width, draw)

        for line in subtitle_lines:
            bbox = draw.textbbox((0, 0), line, font=subtitle_font)
            line_width = bbox[2] - bbox[0]
            line_height = bbox[3] - bbox[1]
            x = (width - line_width) // 2

            draw.text((x, current_y), line, fill=(255, 255, 255, 230), font=subtitle_font)
            current_y += line_height + 15

    # Add bottom accent line
    accent_y = height - 80
    draw.rectangle([(60, accent_y), (width - 60, accent_y + 4)], fill=(255, 255, 255, 100))

    # Add tagline at bottom
    tagline = "Open Source • Self-Hosted • Privacy-First"
    tagline_bbox = draw.textbbox((0, 0), tagline, font=subtitle_font)
    tagline_width = tagline_bbox[2] - tagline_bbox[0]
    tagline_x = (width - tagline_width) // 2
    draw.text((tagline_x, accent_y + 20), tagline, fill=(255, 255, 255, 200), font=subtitle_font)

    # Save to BytesIO
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)

    return buffer
