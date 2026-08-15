"""The action catalog — everything a Dwarf Fortress player can do, declared.

Grounded in the official Kitfox beginner guide (tools/df_docs/guide_transcript.txt,
timestamps quoted per verb) and the capability analysis derived from it. The guide is
the right source because it is the publisher's own statement of what the basic game
consists of, and it is ruthless about the order things matter in: it calls the minimum
"beds, beer and biscuits" and spends its longest chapters on digging and on the food
chain.

STATUS is the point of this file. `live` verbs dispatch today. `planned` verbs are ones a
player has and the agent does not — declared here with their intended signature so the
gap is a list you can query and shrink, not a thing someone has to remember. A planned
verb is REFUSED at the gate with a reason naming its tranche, never silently dropped.

TRANCHES are ordered by survival impact, measured rather than guessed. A full game year
under the current five verbs ended with drink 12 -> 0, nothing farmed or brewed, and 2 of
7 dwarves dead — for both the idle policy and the developing one. So tranche 1 is exactly
the chain that turns dirt into a mug of beer, and nothing else:

    1  stay alive        the food and drink chain, and the manager who runs it
    2  stay sane         rooms, zones and the furniture that makes them count
    3  shape the world   the terrain verbs: chop, smooth, build, prioritise
    4  compose           templates and workshop clusters over the atoms below them

One measured fact drives tranche 1's first verb. On the pinned save only
EXPEDITION_LEADER is filled; MANAGER and BOOKKEEPER are vacant. The guide is explicit
that the manager is what turns an order into a job — which is the most plausible reason
`workorders_done` sat at 0 for an entire game year while workshops stood ready.
"""

from __future__ import annotations

from .schema import Arg, Verb

# Labours the guide singles out as needing equipment, so they cannot be blanket-assigned
# to everyone the way the rest are (guide 09:50). Kept here because the gate should be
# able to explain a refusal, not just issue one.
EQUIPPED_LABORS = ("MINE", "CUTWOOD", "HUNT")

# Job types the dispatcher can actually queue. The list is closed, and it is closed at
# the gate rather than only in Lua, because the failure mode of an open list is silent:
# an unrecognised job used to fall through to a default and quietly produce beds.
#
# A job belongs here only once it has BOTH a workshop and a reagent rule on the DFHack
# side (JOB_SPEC in bonsai-apply-actions.lua). Handing a job the wrong reagent is not a
# soft failure — DF cancels it thousands of ticks later, and by then the agent believes
# the work is under way. Keep the two lists in step.
ORDERABLE_JOBS = (
    "ConstructBed", "ConstructTable", "ConstructThrone", "ConstructDoor",
    "ConstructCabinet", "ConstructChest", "ConstructBin", "MakeBarrel",
    "ConstructCoffin",                       # carpenter, one log each
    "MakeCrafts", "ConstructBlocks",         # stone
)

# Material classes the dispatcher can pick a reagent and a workshop for. "any" lets it
# take whichever the job supports and the fort has a workshop for.
ORDER_MATERIALS = ("any", "wood", "stone")

# DF's own comparison and schedule enums (df.logic_condition_type,
# df.workquota_frequency_type), so a condition the agent writes is the same shape a
# player's is and survives an `orders export`.
ORDER_COMPARISONS = ("LessThan", "AtMost", "Exactly", "AtLeast", "GreaterThan")
ORDER_FREQUENCIES = ("Daily", "Monthly", "Seasonally", "Yearly")

# The stockpile categories DFHack ships a preset for, read off hack/data/stockpiles as
# `cat_*.dfstock`. These names are the presets', not the settings flags' — the preset is
# `sheets` where the flag is `sheet` — and only a preset makes a pile actually accept
# anything, so this is the list that has to be right.
STOCKPILE_CATEGORIES = (
    "ammo", "animals", "armor", "bars_blocks", "cloth", "coins", "corpses",
    "finished_goods", "food", "furniture", "gems", "leather", "refuse", "sheets",
    "stone", "weapons", "wood",
)

CATALOG: tuple[Verb, ...] = (
    # ---------------------------------------------------------------- time
    Verb(
        name="advance", category="time",
        doc="Let the fort run. The only verb that changes nothing by itself.",
        observable="frame_counter increases",
        guide="",
    ),

    # ---------------------------------------------------------------- live today
    Verb(
        name="set_labor", category="labour",
        doc="Turn a labour on or off for every citizen at once.",
        observable="unit.status.labors[id] on each citizen",
        args=(
            Arg("labor", "str", "df.unit_labor name, e.g. PLANT or BREWER"),
            Arg("on", "bool", "enable or disable", required=False, default=True),
        ),
        guide="09:50",
        note="Blunt compared to a player, who assigns per dwarf and can pull one dwarf "
             "out of the general pool to specialise them (guide 29:44). See "
             "set_dwarf_labor.",
    ),
    Verb(
        name="designate_dig", category="terrain",
        doc="Extend the fort: a stairwell down from a pinned origin, plus rooms off "
            "each landing.",
        observable="dug_tiles, derived from the fall in solid tiles inside the T0 region",
        args=(Arg("tiles", "int", "how many tiles to designate", lo=1, hi=400,
                  required=False, default=25),),
        guide="12:06",
        note="A player chooses WHERE and in what shape; this picks for them. The shape "
             "is deliberate — every tile connects to the one above, because "
             "designations that nothing can walk to generate no jobs.",
    ),
    Verb(
        name="create_stockpile", category="logistics",
        doc="Place a 2x2 stockpile on a ring around the wagon.",
        observable="buildings count of type Stockpile, and the categories it accepts",
        args=(Arg("count", "int", "how many to place", lo=1, hi=8,
                  required=False, default=1),
              Arg("accepts", "str",
                  "one configure_stockpile category, or everything",
                  required=False, default="everything")),
        guide="08:00",
        note="Accepts everything unless a category is named, the way a player picks a "
             "type from DF's menu when placing. This note used to say the same thing "
             "and be FALSE: the verb placed untyped piles that accepted nothing, so "
             "DF made no hauling job and the test fort's wagon was still fully loaded "
             "three game days after embark. A player's next act is to NARROW it — the "
             "guide removes stone and wood so bulk goods cannot crowd out perishables "
             "(09:06). See configure_stockpile.",
    ),
    Verb(
        name="add_workorder", category="production",
        doc="Make a specific quantity of something, once.",
        observable="workorders_done, from the fall in amount_left across manager_orders",
        args=(
            Arg("job", "enum", "what to make", choices=ORDERABLE_JOBS),
            Arg("amount", "int", "how many", lo=1, hi=200, required=False, default=10),
            Arg("material", "enum", "what to make it out of",
                choices=ORDER_MATERIALS, required=False, default="any"),
        ),
        guide="18:42",
        note="Bulk creation, deliberately WITHOUT a condition or a schedule — those are "
             "add_workorder_conditional, a different thing to want even though DF stores "
             "both in one manager_order (tools/df_docs/open_decisions.md). The job list "
             "is closed because the dispatcher can only queue work it has a workshop AND "
             "a reagent rule for; before it was an enum, `add_workorder NoSuchJobType 5` "
             "fell through to a default and queued five beds.",
    ),
    Verb(
        name="build_workshop", category="production",
        doc="Build a workshop on a ring around the wagon.",
        observable="buildings count of type Workshop with the requested subtype",
        args=(Arg("kind", "str", "df.workshop_type name, e.g. Carpenters, Still",
                  required=False, default="Carpenters"),),
        guide="16:48",
    ),

    # ================================================================ TRANCHE 1
    # The chain from dirt to a mug of beer, plus the administrator who runs it.
    Verb(
        name="assign_noble", category="administration", tranche=0,
        doc="Put a dwarf in an administrative position. MANAGER validates work orders "
            "into jobs; BOOKKEEPER makes stockpile counts exact.",
        observable="dfhack.units.getNoblePositions(unit) names the position — measured "
                   "going from (none) to MANAGER to MANAGER,BOOKKEEPER",
        args=(
            Arg("position", "enum", "which office",
                choices=("MANAGER", "BOOKKEEPER", "BROKER", "CHIEF_MEDICAL_DWARF",
                         "SHERIFF", "MILITIA_COMMANDER")),
            Arg("dwarf", "str", "citizen id, or 'best' to let the evaluator choose",
                required=False, default="best"),
        ),
        guide="17:55",
        note="Seating requires a histfig_entity_link_positionst on the appointee, not "
             "just the assignment's histfig field — writing the field alone left "
             "getNoblePositions empty while the nobles screen read correctly. "
             "'best' is currently the crudest defensible rule (most total skill "
             "experience, ties by unit id) until the fitness scorer lands. "
             "NOTE: seating a manager did NOT make work orders validate — that "
             "hypothesis was tested and refused; the cause of workorders_done == 0 "
             "lies in the order, not the office.",
    ),
    Verb(
        name="build_farm_plot", category="food-water", tranche=0,
        doc="Lay out a farm plot on ground that suits the crop you mean to grow.",
        observable="a building of type FarmPlot exists; seed and plant counts move",
        args=(
            Arg("width", "int", "tiles", lo=1, hi=10, required=False, default=3),
            Arg("height", "int", "tiles", lo=1, hi=10, required=False, default=3),
            Arg("plant", "str",
                "plant raw id to site it for, or 'best' to use what the fort has seed for",
                required=False, default="best"),
        ),
        guide="24:32",
        note="Which ground is right depends on WHAT is being planted. A subterranean "
             "crop in a surface plot grows nothing while the plot reads as built and "
             "sown — measured, the first version did exactly that on an embark whose "
             "six crops all happened to be subterranean. Another embark carrying wheat "
             "or a surface plant wants the opposite ground, so the crop is chosen first "
             "and the site demanded to match, falling through the fort's other seeds "
             "rather than building somewhere nothing will grow. If nothing suitable is "
             "dug out yet the answer is designate_dig, and the refusal says so by "
             "leaving the count at zero. The plot is sown on the spot with the crop its "
             "ground was chosen for.",
    ),
    Verb(
        name="set_crop", category="food-water", tranche=0,
        doc="Choose what the farm plots grow, per season.",
        observable="the plot's per-season plant id",
        args=(
            Arg("plant", "str", "plant raw id, or 'best' to pick from the fort's seeds",
                required=False, default="best"),
            Arg("season", "enum", "which season",
                choices=("all", "spring", "summer", "autumn", "winter"),
                required=False, default="all"),
        ),
        guide="26:04",
        note="'best' picks per plot from the seeds the fort actually holds, matched to "
             "where that plot is - a subterranean crop in a surface plot grows nothing "
             "and looks fine - and prefers one that can be brewed, because drink is what "
             "a fort runs out of first.",
    ),
    Verb(
        name="set_kitchen_flag", category="food-water", tranche=0,
        doc="Forbid or allow cooking an item type, for every material the fort holds.",
        observable="the kitchen exclusion list",
        args=(
            Arg("item", "str", "df.item_type name, e.g. SEEDS or DRINK"),
            Arg("allow", "bool", "allow cooking it, or forbid it",
                required=False, default=False),
        ),
        guide="11:18",
        note="The guide's most emphasised early setting and pure downside protection: "
             "cooking destroys seeds, and cooking drink turns the beer supply into "
             "meals. Reports reaching the requested state, not only changing it - DF "
             "ships with seeds already excluded, so a correct call looked like a failed "
             "verb.",
    ),
    Verb(
        name="add_workorder_conditional", category="production", tranche=0,
        doc="Watch a stock level and refill it automatically, without being asked again.",
        observable="the guarded stock stops falling below the threshold while material "
                   "lasts, and the order reads validated with active tracking the "
                   "condition",
        args=(
            Arg("job", "enum", "what to make", choices=ORDERABLE_JOBS),
            Arg("item", "str", "df.item_type name to count, e.g. BARREL or BAR"),
            Arg("value", "int", "the threshold to compare the count against",
                lo=0, hi=1000),
            Arg("amount", "int", "how many to make each time it fires",
                lo=1, hi=100, required=False, default=10),
            Arg("compare", "enum", "how the count is compared with the threshold",
                choices=ORDER_COMPARISONS, required=False, default="LessThan"),
            Arg("item_material", "str",
                "narrow the count to one material, e.g. ASH or INORGANIC:STEEL",
                required=False, default=""),
            Arg("frequency", "enum", "how often the condition is re-checked",
                choices=ORDER_FREQUENCIES, required=False, default="Daily"),
        ),
        guide="28:14",
        note="This is how a player stops babysitting. Read off a hand-played fort the "
             "shape is `MakeAsh x_/10 Daily WHILE LessThan 10 of BAR (ASH)` — thirty of "
             "that fort's fifty-seven orders carry a condition and every one is Daily. "
             "The amount is the FULL order, not the shortfall; the condition is what "
             "makes it go quiet once the shelf is full. The condition is written into "
             "the order's real item_conditions, so it reads in-game and exports through "
             "`orders export` like a player's, even though we evaluate it ourselves.",
    ),

    # ================================================================ TRANCHE 2
    # Rooms, zones and the furniture that makes them count.
    Verb(
        name="place_furniture", category="quality-of-life", tranche=0,
        doc="Install an already-made bed, table, chair, door, cabinet or coffer into a "
            "dug room.",
        observable="a building of that furniture type exists at the position",
        args=(
            Arg("kind", "enum", "what to install",
                choices=("Bed", "Table", "Chair", "Door", "Cabinet", "Coffer", "Hatch")),
            Arg("count", "int", "how many", lo=1, hi=20, required=False, default=1),
        ),
        guide="21:59",
        note="Without this, add_workorder('ConstructBed') only makes objects that sit "
             "in a stockpile. A bed is not a bedroom until it is built into one.",
    ),
    Verb(
        name="create_zone", category="quality-of-life", tranche=0,
        doc="Paint a zone: bedroom, dining hall, meeting area, pen and pasture, office, "
            "or a surface fruit-gathering area.",
        observable="a civzone of that type covering the rectangle",
        args=(
            Arg("kind", "enum", "zone type",
                choices=("bedroom", "dining", "meeting", "pasture", "office",
                         "gather_fruit", "dormitory", "refuse")),
            Arg("width", "int", "tiles", lo=1, hi=20, required=False, default=6),
            Arg("height", "int", "tiles", lo=1, hi=20, required=False, default=6),
        ),
        guide="21:39",
        note="Livestock need a pasture or they do not eat (21:18). A meeting area is "
             "where idle dwarves gather, and the guide wants it 6x6 and clear so they "
             "can dance.",
    ),
    Verb(
        name="assign_room", category="quality-of-life", tranche=0,
        doc="Give a room to a specific dwarf, or let the next claimant take it.",
        observable="the zone's assigned unit id",
        args=(
            Arg("kind", "enum", "which room",
                choices=("bedroom", "office", "dining")),
            Arg("dwarf", "str", "citizen id, or 'best' for the evaluator's pick, or "
                                "'any' to leave it unclaimed",
                required=False, default="any"),
        ),
        guide="23:06",
        note="A manager needs an office once the fort passes twenty dwarves (18:19), so "
             "this stops being cosmetic and starts being a requirement.",
    ),
    Verb(
        name="set_dwarf_labor", category="labour", tranche=0,
        doc="Set one dwarf's labours, or pull them out of the general pool so they only "
            "do their speciality.",
        observable="that unit's labor flags, and the job it picks up next",
        args=(
            Arg("dwarf", "str", "citizen id, or 'best' for the evaluator's pick"),
            Arg("labor", "str", "df.unit_labor name"),
            Arg("on", "bool", "enable it, or turn it off",
                required=False, default=False),
        ),
        guide="29:44",
        note="The guide's fix for a fort where smoothing was starving mining of hands.",
    ),
    Verb(
        name="configure_stockpile", category="logistics", tranche=0,
        doc="Say what a stockpile accepts, and whether it uses barrels or bins.",
        observable="the pile's accept flags and its per-material lists",
        args=(
            Arg("index", "int", "which stockpile", lo=0, hi=64),
            Arg("accepts", "enum", "the one category to accept",
                choices=STOCKPILE_CATEGORIES),
            Arg("containers", "bool", "allow barrels and bins in this pile",
                required=False, default=True),
        ),
        guide="09:06",
        note="Three separate fort-saving uses in the guide: a seeds pile with barrels "
             "OFF so dwarves can find the seeds, a refuse pile so corpses leave the "
             "fort, and a starter pile with stone and wood excluded. What a pile takes "
             "is NOT its accept flags — DF matches items against per-material lists, "
             "and a pile with every flag on but empty lists produced zero hauling jobs "
             "over 2000 ticks with a claimable bar two tiles away.",
    ),
    Verb(
        name="cancel_dwarf_job", category="labour", tranche=0,
        doc="Drop one dwarf's current job so somebody else can take it.",
        observable="that unit's current job becomes empty, then differs",
        args=(Arg("dwarf", "str", "citizen id"),),
        guide="20:31",
        note="The guide's answer to one miner working while a second pick sits idle.",
    ),

    # ================================================================ TRANCHE 3
    # The terrain vocabulary. Mostly what it takes to survive an aquifer.
    Verb(
        name="chop_trees", category="terrain", tranche=0,
        doc="Mark surface trees for felling.",
        observable="log count rises",
        args=(Arg("count", "int", "how many trees", lo=1, hi=60,
                  required=False, default=10),),
        guide="12:52",
        note="Wood is the input to barrels, beds and the constructed walls that seal an "
             "aquifer, so this feeds three other chains.",
    ),
    Verb(
        name="build_construction", category="terrain", tranche=0,
        doc="Build a wall, floor, ramp or staircase out of stored material.",
        observable="the tiletype at the position becomes a construction",
        args=(
            Arg("kind", "enum", "what to build",
                choices=("wall", "floor", "ramp", "stair")),
            Arg("count", "int", "how many tiles", lo=1, hi=40,
                required=False, default=4),
        ),
        guide="14:20",
        note="Half of the aquifer technique, and the only way to repair a staircase "
             "that was dug in the wrong order (29:02).",
    ),
    Verb(
        name="smooth", category="terrain", tranche=0,
        doc="Smooth dug stone. Stops aquifer seepage and makes rooms worth more.",
        observable="tile special becomes SMOOTH; room value rises",
        args=(Arg("count", "int", "how many tiles", lo=1, hi=200,
                  required=False, default=25),),
        guide="15:46",
        note="Does double duty: the cheap way through an aquifer in stone, and the "
             "cheap way to make a bedroom please its owner.",
    ),
    Verb(
        name="set_dig_priority", category="terrain", tranche=0,
        doc="Set the priority of mining designations, 1 highest to 7 lowest.",
        observable="the designation priority, and miners keeping to mining",
        args=(Arg("priority", "int", "1..7", lo=1, hi=7, required=False, default=4),),
        guide="14:20",
        note="At priority 2 dwarves stop wandering off to haul instead of dig. I first "
             "reported this mechanic as absent because map_block has no priority array - "
             "wrong, and the owner said so. It is stored in a block_square_event of type "
             "designation_priority, indexed by pos %% 16 and held as priority * 1000, "
             "which is how DFHack's own quickfort/dig.lua writes it. Read the working "
             "implementation instead of concluding from one missing field.",
    ),
    Verb(
        name="set_standing_order", category="logistics", tranche=0,
        doc="Flip a fort-wide standing order, such as collecting refuse left outdoors.",
        observable="the standing order flag",
        args=(
            Arg("order", "str", "standing order name"),
            Arg("on", "bool", "enable", required=False, default=True),
        ),
        guide="32:14",
    ),

    # ================================================================ TRANCHE 4
    # Composition. Nothing here does anything the atoms above cannot; it decides
    # placement and bundles, which is where an offline search can help the agent.
    Verb(
        name="apply_template", category="composition", status="planned", tranche=4,
        doc="Stamp a stored room design at a chosen spot: dig, build and zone in one "
            "intent.",
        observable="the finished room's value reaches the template's declared tier",
        args=(
            Arg("template", "str", "template name from the library"),
            Arg("tier", "int", "quality tier to aim for", lo=1, hi=5,
                required=False, default=1),
        ),
        guide="",
        note="Designs are improved OUTSIDE agent training, by search against room value. "
             "The agent picks a name and a tier; it never has to learn floor plans.",
    ),
    Verb(
        name="build_workshop_cluster", category="composition", status="planned",
        tranche=4,
        doc="Place a related group of workshops, e.g. woodworking, and the stockpiles "
            "that feed them.",
        observable="every workshop in the cluster exists and is reachable",
        args=(
            Arg("cluster", "str", "cluster name from the library"),
            Arg("scale", "int", "how many copies", lo=1, hi=4,
                required=False, default=1),
        ),
        guide="",
        note="Carries its cost and the capabilities it unlocks as metadata, so the "
             "agent can weigh one against another instead of memorising which workshop "
             "makes barrels.",
    ),
)

BY_NAME = {v.name: v for v in CATALOG}
LIVE = tuple(v for v in CATALOG if v.status == "live")
PLANNED = tuple(v for v in CATALOG if v.status == "planned")
