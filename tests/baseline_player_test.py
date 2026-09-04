import asyncio
from player.baseline_player import BaselinePlayer

def test_baseline_player_report():
    """Validate BaselinePlayer collects expected metrics over a 30‑day run."""
    async def runner():
        player = BaselinePlayer(seed=42)
        await player.run()
        report = player.report()
        assert report == {"seed": 42, "duration_days": 30, "failures": []}
    asyncio.run(runner())
