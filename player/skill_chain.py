"""Skill-chain player composes reusable Skills into an episode policy.

Iteration protocol per step:
  1. Call each Skill.steps(observation) in order.
  2. If a skill returns None, skip to the next skill.
  3. If a skill returns a list, extend the internal buffer with those actions.
  4. Emit one action from the FIFO buffer per call. When the buffer is empty
     after refilling, return None to terminate the episode.

The resulting callable matches the `action_policy` signature expected by
EpisodeRunner.run():  `callable(observation) -> action_dict | None`.
"""

from collections import deque


def make_skill_chain(*skills):
    """Return an episode-ready policy function from a list of Skill instances.

    Parameters:
        *skills: any number of Skill instances.

    Returns:
        A callable `policy(observation) -> action_dict | None` with an attached
        `_reset()` method that clears buffered actions (called by EpisodeRunner
        at episode start).
    """

    buffer = deque()
    _needs_refill = True

    def _gather_actions(obs):
        for skill in skills:
            result = skill.steps(obs)
            if result is None:
                continue
            if isinstance(result, list):
                buffer.extend(result)
            else:
                buffer.append(result)

    def policy(observation):
        nonlocal _needs_refill
        if _needs_refill or not buffer:
            _gather_actions(observation)
            _needs_refill = False

        if not buffer:
            return None

        return buffer.popleft()

    def _reset():
        nonlocal _needs_refill
        buffer.clear()
        _needs_refill = True
        for skill in skills:
            if callable(getattr(skill, "reset", None)):
                skill.reset()

    policy._reset = _reset

    return policy
