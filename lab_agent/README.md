# Bonsai lab agent

This service runs as root only inside the untrusted Dwarf Fortress LXC. It polls the trusted control API, asks the large Ollama model for one structured action at a time, executes code and DFHack experiments, commits coherent candidates, and uploads a Git bundle plus an NDJSON trace.

It has no PostgreSQL or GitHub credential. Every job runs in a fresh clone so a failed experiment cannot corrupt the baseline checkout. Promotion is performed only by the trusted control plane after private gates.
