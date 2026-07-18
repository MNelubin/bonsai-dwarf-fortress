# Bonsai Dwarf Fortress

Автономная исследовательская система для Dwarf Fortress: большой coding-agent использует Ollama/RTX 3090 для создания и улучшения инструментов, bridge, сценариев и лёгкого CPU-инференс игрока; headless-игра и недоверенный агент работают в отдельном LXC.

Текущая топология и границы доверия описаны в [ARCHITECTURE.md](ARCHITECTURE.md), принятые решения — в [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md).

Основные части:

- `control_plane/` — trusted API, WebUI, durable scheduler и policy gates;
- `guest/` — файлы и операционные заметки игрового CT123;
- `infra/` — воспроизводимые скрипты развёртывания и аудита;
- будущие `bridge/`, `game_runner/`, `player/`, `skills/`, `curricula/` — область, которую агент сможет улучшать автоматически.

Секреты, Steam-сессия, GitHub credential и приватный evaluator в репозиторий не коммитятся.
