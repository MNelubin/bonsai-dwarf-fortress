# Bonsai Dwarf Fortress

Автономная исследовательская система для Dwarf Fortress: большой coding-agent использует Ollama/RTX 3090 для создания и улучшения инструментов, bridge, сценариев и лёгкого CPU-инференс игрока; headless-игра и недоверенный агент работают в отдельном LXC.

Текущая топология и границы доверия описаны в [ARCHITECTURE.md](ARCHITECTURE.md), принятые решения — в [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md).

Основные части:

- `lab_agent/` — недоверенная лаборатория: единственный драйвер эпизода (`session.py` +
  `stepped_episode.py`), метрика (`scoring.py`), шлюз действий (`actions/`), эталонные
  политики (`baselines/`) и DFHack-скрипты (`dfhack/`), которыми всё это говорит с игрой;
- `control_plane/` — trusted API, WebUI, durable scheduler и policy gates;
- `guest/` — файлы и операционные заметки игрового CT123;
- `infra/` — воспроизводимые скрипты развёртывания и аудита;
- `bridge/`, `game_runner/`, `player/`, `skills/`, `curricula/` — область, которую агент
  улучшает автоматически. Здесь они перечислены как существующие, а не как будущие:
  `bridge/` и `game_runner/` вызываются из `worker.py` и оркестратора прямо сейчас.

Одна канонная дорога к игре, и другой нет: `session.DFSession` поднимает форт через
`bonsai_session.sh`, `stepped_episode` ведёт эпизод раунд за раундом, `game_evaluate`
считает результат по `scoring.py`. Второй драйвер (`live_episode.py` поверх
одноразового `bonsai_episode.sh`) удалён — он дублировал разбор наблюдений и успел
разойтись с основным, из-за чего засчитывал нулевую копку в каждом эпизоде.

Секреты, Steam-сессия, GitHub credential и приватный evaluator в репозиторий не коммитятся.
