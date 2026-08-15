"""Offline room-design search.

Runs OUTSIDE the agent's training loop, by the owner's explicit instruction:

    отбор комнат уже вести вне обучения основного Агента

The agent never sees a floor plan. It asks for a template by name; the winners of this
search become entries in `actions.library.TEMPLATES`.
"""

from .model import Design, Requirement, bare_room, item_value, score
from .emit import to_quickfort
from .validate import validate
from .search import Result, anneal

__all__ = ["Design", "Requirement", "Result", "anneal", "bare_room", "item_value",
           "score", "to_quickfort", "validate"]
