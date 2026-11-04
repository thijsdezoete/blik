"""Geometry for the report PDF charts. Templates only draw what is computed here."""
import math

from reviews.models import CATEGORY_ORDER

MAX_LABEL = 22
RADAR_PAD_X = 90
RADAR_PAD_Y = 34
RADAR_LINE = 18  # characters per line of a wrapped axis label


def _short(title):
    return title if len(title) <= MAX_LABEL else title[:MAX_LABEL - 1] + '…'


def _wrap(title, width=RADAR_LINE):
    """The title on at most two lines of about `width` characters; the second line is cut short when needed."""
    words = title.split()
    first = ''
    while words and len(f'{first} {words[0]}'.strip()) <= width:
        first = f'{first} {words.pop(0)}'.strip()
    if not first:  # one long word
        return [_short(title)]
    rest = ' '.join(words)
    if not rest:
        return [first]
    return [first, rest if len(rest) <= width else rest[:width - 1] + '…']


def radar_chart(section_scores, size=240):
    """Polygons for a radar of section scores, centred at (size/2, size/2).

    Score 5 sits at radius size*0.38, first axis straight up, clockwise.
    The viewBox extends beyond 0..size so axis labels fit.
    """
    c = size / 2
    r5 = size * 0.38
    n = len(section_scores)

    def point(i, score):
        angle = 2 * math.pi * i / n
        r = r5 * score / 5
        return c + r * math.sin(angle), c - r * math.cos(angle)

    def polygon(scores):
        return ' '.join('%.1f,%.1f' % point(i, s) for i, s in enumerate(scores))

    rings = [polygon([level] * n) for level in range(1, 6)]
    axes = []
    for i, title in enumerate(section_scores):
        x2, y2 = point(i, 5)
        lx, ly = point(i, 5.6)
        sin = math.sin(2 * math.pi * i / n)
        cos = math.cos(2 * math.pi * i / n)
        lines = _wrap(title)
        # Labels above the centre grow upwards, so a second line never covers the chart
        ly += 2 - (len(lines) - 1) * 11 * (1 if cos > 0.2 else 0.5 if cos > -0.2 else 0)
        axes.append({
            'number': i + 1, 'x1': c, 'y1': c, 'x2': round(x2, 1), 'y2': round(y2, 1),
            'nx': round(point(i, 5.55)[0], 1), 'ny': round(point(i, 5.55)[1] + 3, 1),
            'label': _short(title), 'lines': lines, 'lx': round(lx, 1), 'ly': round(ly, 1),
            'anchor': 'middle' if abs(sin) < 0.2 else ('start' if sin > 0 else 'end'),
        })

    return {
        'size': size, 'center': c, 'rings': rings, 'axes': axes,
        'groups': _group_polygons(section_scores, polygon),
        'view_box': '%d %d %d %d' % (-RADAR_PAD_X, -RADAR_PAD_Y,
                                     size + 2 * RADAR_PAD_X, size + 2 * RADAR_PAD_Y),
        'width': size + 2 * RADAR_PAD_X, 'height': size + 2 * RADAR_PAD_Y,
    }


def _group_polygons(section_scores, polygon):
    """One polygon per reviewer group with a score, self included, in the usual group order.

    A section without a score of the group is drawn at 0 (the centre), not skipped: skipping would change the
    polygon's axes.

    A group hidden for anonymity has no scores here, or an 'insufficient' marker instead of a number: it gets none.
    """
    groups = []
    for category in CATEGORY_ORDER:
        scores = [cats.get(category) for cats in section_scores.values()]
        scores = [score if isinstance(score, (int, float)) else None for score in scores]
        if any(score is not None for score in scores):
            groups.append({'category': category, 'points': polygon([score or 0 for score in scores])})
    return groups
