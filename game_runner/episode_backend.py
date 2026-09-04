# Minimal stub implementation of EpisodeBackend for public tests
# Provides the required protocol for EpisodeRunner to operate deterministically.

class EpisodeBackend:
    """Protocol base for episode backends.

    The bridge and test infrastructure expect a ``run_step`` method that accepts
    an ``action`` and returns an ``observation``.  This stub returns an empty
    observation dict for any action, keeping the test deterministic while the
    real backend is not part of this bounded edit.
    """

    def run_step(self, action=None):
        """Execute a single step with the given *action*.

        Parameters
        ----------
        action : optional
            An opaque dict representing the requested action.  It is ignored.

        Returns
        -------
        dict
            An empty observation placeholder.
        """
        return {}
