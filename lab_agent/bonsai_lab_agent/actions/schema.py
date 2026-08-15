"""Argument schemas for agent action intents.

The old gate was a set of verb names and nothing else: `sanitize_actions` checked that
the verb was allow-listed and then passed `args` through untouched, so a wrong argument
type reached the DFHack dispatcher and died there silently. With five verbs that was
survivable. The target surface is roughly forty — everything a human player can do — and
at that size an untyped gate is a guarantee of quiet failure.

So a verb is DECLARED, not hardcoded: name, category, arguments with types and ranges,
the observable that proves it worked, and which tranche implements it. Three things then
fall out of the same declaration:

  * validation — the evaluator can reject or repair an intent before it reaches the game
  * discoverability — the controller is handed the schema, instead of guessing arguments
  * a roadmap — verbs the game supports but we have not wired yet are declared `planned`,
    so the gap between what a player can do and what the agent can do is a queryable
    list rather than a memory

INVARIANT: this module never touches the game. It decides what an intent MEANS; trusted
Lua decides what happens. The agent still executes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class SchemaError(ValueError):
    """A verb declaration is malformed — a programming error, not agent input."""


@dataclass(frozen=True)
class Arg:
    """One argument of one verb.

    `lo`/`hi` bound numbers and `choices` bounds strings, and the two are treated
    DIFFERENTLY on violation — see `Decision` below for why.
    """

    name: str
    kind: str                                   # int | str | bool | enum
    doc: str
    required: bool = True
    default: Any = None
    choices: tuple[str, ...] | None = None
    lo: int | None = None
    hi: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("int", "str", "bool", "enum"):
            raise SchemaError(f"{self.name}: unknown kind {self.kind!r}")
        if self.kind == "enum" and not self.choices:
            raise SchemaError(f"{self.name}: enum needs choices")
        if not self.required and self.default is None and self.kind != "str":
            raise SchemaError(f"{self.name}: optional argument needs a default")

    def describe(self) -> dict:
        # `required` is emitted only when FALSE: required is the default, and the flag
        # rides in every controller prompt on every argument of every verb. The schema is
        # a running cost, not a one-off.
        d: dict[str, Any] = {"name": self.name, "type": self.kind, "doc": self.doc}
        if not self.required:
            d["required"] = False
        if self.default is not None:
            d["default"] = self.default
        if self.choices:
            d["choices"] = list(self.choices)
        if self.lo is not None or self.hi is not None:
            d["range"] = [self.lo, self.hi]
        return d


@dataclass(frozen=True)
class Verb:
    """One atomic action a player can take, and the agent may request.

    `observable` is not documentation. Every verb has to name the thing that would be
    read back to prove it did something, because this project has shipped actions that
    dispatched cleanly and changed nothing: dig designations that produced zero jobs, and
    manager orders that were never validated into work. A verb whose effect cannot be
    observed cannot be scored, and should not be added.
    """

    name: str
    category: str
    doc: str
    observable: str
    args: tuple[Arg, ...] = ()
    tranche: int = 0                            # 0 = already live
    status: str = "live"                        # live | planned
    guide: str = ""                             # timestamp in the official guide
    note: str = ""

    def __post_init__(self) -> None:
        if self.status not in ("live", "planned"):
            raise SchemaError(f"{self.name}: bad status {self.status!r}")
        seen = set()
        optional_seen = False
        for a in self.args:
            if a.name in seen:
                raise SchemaError(f"{self.name}: duplicate argument {a.name!r}")
            seen.add(a.name)
            # Positional order is the wire format (the dispatcher reads tab-separated
            # fields), so a required argument after an optional one would be unfillable.
            if optional_seen and a.required:
                raise SchemaError(f"{self.name}: required {a.name!r} follows an optional")
            optional_seen = optional_seen or not a.required

    def describe(self) -> dict:
        # category is for the roadmap and this file, not for the controller: it groups
        # verbs for a reader and the model never acts on it.
        d = {"verb": self.name, "doc": self.doc,
             "args": [a.describe() for a in self.args]}
        if self.status != "live":
            d["status"] = self.status
        return d


@dataclass
class Decision:
    """The result of judging one intent.

    Two failure modes are deliberately treated differently.

    A number out of range is a SCALE mistake: the agent asked to dig 10,000 tiles when
    the cap is 400. Clamping keeps the intent and loses only the exaggeration.

    An unknown enum is a CATEGORY mistake: a workshop type that does not exist cannot be
    repaired into one that does without inventing the agent's intent, so it is rejected.

    Either way the reason is recorded and handed back, so a controller can learn from a
    rejection instead of silently getting nothing.
    """

    ok: bool
    verb: str = ""
    args: list = field(default_factory=list)
    reason: str = ""
    repairs: list = field(default_factory=list)
