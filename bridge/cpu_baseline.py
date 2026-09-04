from typing import List, Dict

# 30‑day CPU baseline

class CPUBaseline:
    def __init__(self) -> None:
        self._records: List[Dict[str, float]] = []
        self.total_cpu_seconds = 0.0

    def instance(self):
        return self

    def run(self, steps: int) -> None:
        # Dummy implementation: simulate steps and accumulate CPU time
        self.total_cpu_seconds = steps * 0.1
        for i in range(steps):
            self._records.append({"_step": i, "cpu": 0.1})
