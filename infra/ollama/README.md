# Bonsai Ollama runtime

This is the canonical Ollama deployment for the PVE-Chert host.

No original Ollama Compose project was found on the host. The previous container
had no `com.docker.compose.*` labels and was most likely created with `docker run`.
This configuration was reconstructed from its immutable `docker inspect` data and
the existing storage layout.

The image combines the pinned official Ollama 0.32.1 image with NVIDIA's CUDA 13
runtime. The NVIDIA kernel driver remains on the host and is injected by
`nvidia-container-runtime`; it must not be installed in the application image.

Persistent data is deliberately split:

- `/var/lib/docker/ollama` contains Ollama state and identity files.
- `/var/lib/docker/shared_models/ollama` contains the shared model blobs and manifests.

The state directory already contains the absolute symlink
`models -> /var/lib/docker/shared_models/ollama`. Compose therefore mounts the
shared store at that same absolute path inside the container instead of masking
the symlink with a second nested mount.

Before promotion, build and run the image under a temporary name and require the
startup log to identify the RTX 3090 with `library=cuda`. Do not replace the live
container merely because `nvidia-smi` works inside the image.

The host's generated `docker-default` profile uses AppArmor semantics that deny
`AF_UNIX/SOCK_SEQPACKET`, causing CUDA `cuInit` to fail with error 304. Load the
included `apparmor-bonsai-ollama` profile before starting Compose. It follows the
current Moby default profile and pins AppArmor ABI 3.0, which restores the intended
meaning of `network,` without making the container privileged or unconfined.
