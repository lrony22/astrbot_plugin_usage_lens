"""Render a seven-day stacked token chart without network resources."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .stats import TOKEN_FIELDS


def render_trend(report: dict, output: Path) -> Path:
    """Draw Magpie's uncached, cache-read, cache-write, and output tokens.

    Args:
        report: Seven daily buckets from collect_usage.
        output: Unique destination within AstrBot's temporary directory.

    Returns:
        The written PNG path.
    """
    image = Image.new("RGB", (1080, 680), "#f5f7fa")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.load_default(size=34)
    font = ImageFont.load_default(size=20)
    small = ImageFont.load_default(size=16)
    ink, muted = "#172638", "#66758a"
    colors = ("#597eeb", "#2bb79d", "#a786d9", "#efa85a")
    draw.text((50, 35), "MAGPIE USAGE / 7 DAYS", font=title_font, fill=ink)
    draw.text(
        (52, 88),
        f"{report['daily'][0]['date']} - {report['daily'][-1]['date']}  |  {report['timezone']}",
        font=font,
        fill=muted,
    )
    for index, (label, color) in enumerate(
        zip(("Uncached input", "Cache read", "Cache write", "Output"), colors)
    ):
        x = 52 + index * 245
        draw.rounded_rectangle((x, 133, x + 16, 149), radius=4, fill=color)
        draw.text((x + 26, 129), label, font=font, fill=ink)

    left, right, top, bottom = 110, 1025, 212, 530
    maximum = max(sum(day[field] for field in TOKEN_FIELDS) for day in report["daily"])
    ceiling = max(maximum * 1.18, 4)
    for index in range(5):
        y = bottom - (bottom - top) * index / 4
        value = ceiling * index / 4
        draw.line((left, y, right, y), fill="#dfe5ed", width=1)
        label = f"{value / 1_000_000:.1f}M" if value >= 1_000_000 else f"{value:,.0f}"
        draw.text((left - 16, y), label, font=small, fill=muted, anchor="rm")

    step = (right - left) / len(report["daily"])
    for index, day in enumerate(report["daily"]):
        x = left + step * (index + 0.5)
        y = float(bottom)
        count = sum(day[field] for field in TOKEN_FIELDS)
        for field, color in zip(TOKEN_FIELDS, colors):
            height = day[field] / ceiling * (bottom - top)
            if height:
                draw.rectangle((x - 32, y - height, x + 32, y), fill=color)
                y -= height
        label = f"{count / 1_000_000:.2f}M" if count >= 1_000_000 else f"{count:,}"
        draw.text((x, y - 16), label, font=small, fill=ink, anchor="mm")
        draw.text((x, bottom + 22), day["date"][5:], font=font, fill=ink, anchor="mm")
        input_tokens = max(
            0,
            day["input_other"]
            + day["input_cached"]
            + day["cache_write"]
            - day["cache_unknown"],
        )
        cache = f"{day['input_cached'] / input_tokens:.0%}" if input_tokens else "--"
        draw.text(
            (x, bottom + 54), f"{cache} cache", font=small, fill=muted, anchor="mm"
        )

    draw.text(
        (52, 635),
        "Source: Magpie gateway  |  Tokens include cache reads/writes  |  Today is partial",
        font=small,
        fill=muted,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG")
    return output
