"""Small formatting helpers shared by the cogs."""

from datetime import datetime, timezone


def coc_time(value):
    """'20261115T024959.000Z' -> '2026-11-15 02:49 UTC'."""
    if not value or len(str(value)) < 13:
        return "—"
    text = str(value)
    return f"{text[0:4]}-{text[4:6]}-{text[6:8]} {text[9:11]}:{text[11:13]} UTC"


def parse_coc_time(value):
    """Parse a Clash of Clans timestamp into an aware datetime."""
    if not value or len(str(value)) < 13:
        return None
    text = str(value)
    try:
        return datetime(
            int(text[0:4]), int(text[4:6]), int(text[6:8]),
            int(text[9:11]), int(text[11:13]), int(text[13:15]),
            tzinfo=timezone.utc,
        )
    except (ValueError, IndexError):
        return None


def hours_until(value, now=None):
    """Hours until a CoC timestamp; negative once it has passed."""
    target = parse_coc_time(value)
    if target is None:
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    return (target - now).total_seconds() / 3600.0


def duration_text(hours):
    """Human '2h 15m' from a float number of hours."""
    if hours is None:
        return "—"
    minutes = int(abs(hours) * 60)
    sign = "-" if hours < 0 else ""
    return f"{sign}{minutes // 60}h {minutes % 60}m"


def age_text(hours):
    """Human '3.2h ago' from a float number of hours."""
    if hours is None:
        return "unknown"
    if hours < 1:
        return f"{int(hours * 60)}m ago"
    if hours < 48:
        return f"{hours:.1f}h ago"
    return f"{hours / 24:.1f}d ago"


def num(value):
    """Thousands separator, safe on None."""
    if value is None:
        return "—"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def truncate(text, limit=900):
    """Discord embed field values cap at 1024 chars."""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
