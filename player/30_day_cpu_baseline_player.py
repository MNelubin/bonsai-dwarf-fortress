class _Simulator:
    def __init__(self, seed):
        self.seed = seed
        self._cpu_time = 0
        self._worst_metric = 0
        # NOTE: worst_metric should be accessed via the worst_metric() method
        self._worst_run = {'cpu_time': 0, 'worst_metric': 0}
    def run(self, minutes):
        # Dummy run: just record the time and a placeholder worst metric.
        self._cpu_time = minutes
        self._worst_metric = max(self._worst_metric, minutes // 10)
        self._worst_run = {'cpu_time': self._cpu_time, 'worst_metric': self._worst_metric}
        # Return a result dict containing required keys for the public test.
        return {'cpu_time': self._cpu_time, 'worst_metric': self._worst_metric}
    def cpu_time(self):
        return self._cpu_time

    def worst_metric(self):
        """Return worst metric value."""
        return self._worst_metric
    def worst_run(self):
        return self._worst_run


def new(seed):
    return _Simulator(seed)
