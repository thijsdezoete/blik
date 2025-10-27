"""
Management command to optimize screenshot images for web usage.
Compresses PNGs and optionally generates WebP versions.
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from pathlib import Path
from PIL import Image
import os


class Command(BaseCommand):
    help = 'Optimize screenshot images for web'

    def add_arguments(self, parser):
        parser.add_argument(
            '--input-dir',
            type=str,
            default='static/img/screenshots',
            help='Input directory containing screenshots'
        )
        parser.add_argument(
            '--quality',
            type=int,
            default=85,
            help='JPEG/WebP quality (1-100, default: 85)'
        )
        parser.add_argument(
            '--webp',
            action='store_true',
            help='Generate WebP versions in addition to PNG'
        )
        parser.add_argument(
            '--max-width',
            type=int,
            default=None,
            help='Maximum width to resize to (maintains aspect ratio)'
        )

    def handle(self, *args, **options):
        input_dir = options['input_dir']
        quality = options['quality']
        generate_webp = options['webp']
        max_width = options['max_width']

        input_path = Path(settings.BASE_DIR) / input_dir

        if not input_path.exists():
            self.stdout.write(self.style.ERROR(f'Input directory not found: {input_path}'))
            return

        # Find all PNG files
        png_files = list(input_path.glob('*.png'))

        if not png_files:
            self.stdout.write(self.style.WARNING(f'No PNG files found in {input_path}'))
            return

        self.stdout.write(f'Found {len(png_files)} PNG files to optimize')

        total_before = 0
        total_after = 0

        for png_file in png_files:
            original_size = png_file.stat().st_size
            total_before += original_size

            # Open image
            img = Image.open(png_file)

            # Resize if needed
            if max_width and img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                self.stdout.write(f'  Resized {png_file.name} to {max_width}x{new_height}')

            # Optimize PNG
            img.save(
                png_file,
                'PNG',
                optimize=True,
                compress_level=9
            )

            new_size = png_file.stat().st_size
            total_after += new_size
            saved = original_size - new_size
            saved_pct = (saved / original_size * 100) if original_size > 0 else 0

            self.stdout.write(
                f'✓ {png_file.name}: {original_size/1024:.1f}KB → {new_size/1024:.1f}KB '
                f'(saved {saved_pct:.1f}%)'
            )

            # Generate WebP version
            if generate_webp:
                webp_file = png_file.with_suffix('.webp')
                img.save(
                    webp_file,
                    'WEBP',
                    quality=quality,
                    method=6  # Maximum compression
                )
                webp_size = webp_file.stat().st_size
                self.stdout.write(
                    f'  → WebP: {webp_size/1024:.1f}KB '
                    f'({(1 - webp_size/new_size) * 100:.1f}% smaller than PNG)'
                )

        total_saved = total_before - total_after
        total_saved_pct = (total_saved / total_before * 100) if total_before > 0 else 0

        self.stdout.write(self.style.SUCCESS(
            f'\nOptimization complete!\n'
            f'Total: {total_before/1024:.1f}KB → {total_after/1024:.1f}KB\n'
            f'Saved: {total_saved/1024:.1f}KB ({total_saved_pct:.1f}%)'
        ))
