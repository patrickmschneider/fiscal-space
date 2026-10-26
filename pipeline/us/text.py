"""Reader-facing date wording for the US edition (US style: 'November 12, 2026', 'February 2026')."""
from datetime import date

MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December')


def long_date(value):
    """date or 'YYYY-MM-DD' (a timestamp is cut to its date) -> 'November 12, 2026'."""
    d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return f'{MONTHS[d.month - 1]} {d.day}, {d.year}'


def month_year(value):
    """'YYYY-MM' (or a longer ISO date) -> 'February 2026'."""
    text = str(value)
    return f'{MONTHS[int(text[5:7]) - 1]} {text[:4]}'
