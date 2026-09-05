"""Dwarf Fortress fortress-mode calendar, measured rather than assumed.

One home for these numbers. The tree carried six separate definitions of
TICKS_PER_DAY split three against three — bridge/probe.py and
evaluator_public/__init__.py said 86400 with 361 days to a season, while
player/baseline.py, player/cpu_policy.py and the lab agent's scoring.py said
1200. Half the codebase measured time in one calendar and half in another, and
tests/test_bridge_contract.py asserted the wrong pair, which is why it survived
every review: it was pinned in place.

86400 is the number of seconds in a real day. 361 is not DF's year.

Measured live on 2026-09-05 against the DF 53.16 mature save region3-lab:

    df.global.cur_year_tick = 299484   df.global.cur_year = 259

DF's own save list dates that state 26th Timber, late autumn, year 259. Timber
is the ninth month, so it is day 8*28 + 26 = 250 of the year.

    299484 / 1200  = 249.57  -> day 250, exactly as DF says
    299484 / 86400 = 3.47    -> the 3rd of Granite, early spring

A month is 28 days and a season is three months, so 84 days; a year is twelve
months, so 336 days and 403200 ticks.
"""

TICKS_PER_DAY = 1200
DAYS_PER_MONTH = 28
MONTHS_PER_SEASON = 3
SEASONS_PER_YEAR = 4

DAYS_PER_SEASON = DAYS_PER_MONTH * MONTHS_PER_SEASON          # 84
DAYS_PER_YEAR = DAYS_PER_MONTH * MONTHS_PER_SEASON * SEASONS_PER_YEAR  # 336
TICKS_PER_SEASON = DAYS_PER_SEASON * TICKS_PER_DAY            # 100800
TICKS_PER_YEAR = DAYS_PER_YEAR * TICKS_PER_DAY                # 403200

# The month names in order, so a tick can be turned back into the date DF shows.
MONTH_NAMES = (
    "Granite", "Slate", "Felsite",          # spring
    "Hematite", "Malachite", "Galena",      # summer
    "Limestone", "Sandstone", "Timber",     # autumn
    "Moonstone", "Opal", "Obsidian",        # winter
)


def day_of_year(cur_year_tick: int) -> int:
    """1-based day, the way DF's own date reads."""
    return int(cur_year_tick) // TICKS_PER_DAY + 1


def date(cur_year_tick: int) -> tuple[int, str]:
    """(day of month, month name) for a within-year tick count."""
    day_index = int(cur_year_tick) // TICKS_PER_DAY
    month, day = divmod(day_index, DAYS_PER_MONTH)
    return day + 1, MONTH_NAMES[month % len(MONTH_NAMES)]
