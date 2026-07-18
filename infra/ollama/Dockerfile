ARG OLLAMA_IMAGE=ollama/ollama@sha256:6345fbc18bd73a1e16404be681dbc6fd291a027cab43ed541abe78c4c81051b0
FROM ${OLLAMA_IMAGE} AS ollama

FROM nvidia/cuda:13.0.0-runtime-ubuntu24.04

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ollama /bin/ollama /bin/ollama
COPY --from=ollama /usr/lib/ollama /usr/lib/ollama

ENV OLLAMA_HOST=0.0.0.0:11434 \
    OLLAMA_LLM_LIBRARY=cuda_v13 \
    OLLAMA_VULKAN=0 \
    GGML_VK_VISIBLE_DEVICES=-1 \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    LD_LIBRARY_PATH=/usr/lib/ollama/cuda_v13:/usr/local/nvidia/lib:/usr/local/nvidia/lib64

EXPOSE 11434
ENTRYPOINT ["/bin/ollama"]
CMD ["serve"]
