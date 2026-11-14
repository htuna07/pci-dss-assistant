# syntax=docker/dockerfile:1
#
# Build once with your own copy of the PCI DSS PDF at data/PCI-DSS-v4_0_1.pdf:
#   docker build -t pci-assistant .
#   docker run -p 127.0.0.1:8000:8000 -e CLAUDE_CODE_OAUTH_TOKEN=... pci-assistant
#
# The final image contains the standard's text (chunks), which PCI SSC copyrights:
# use it on your own machine and never push it to a registry.

FROM python:3.14-slim AS prepare
WORKDIR /app
ENV HF_HOME=/opt/hf PIP_NO_CACHE_DIR=1

# The default PyPI torch for Linux bundles CUDA; this service only needs the CPU build.
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r requirements.txt

# data/ always exists in a checkout (it holds a README), so a missing PDF reaches the check below
# instead of failing here with a path error.
COPY data/ data/
RUN test -f data/PCI-DSS-v4_0_1.pdf || { \
      echo "ERROR: data/PCI-DSS-v4_0_1.pdf is missing." >&2; \
      echo "Download PCI DSS v4.0.1 from the PCI SSC document library and save it there." >&2; \
      exit 1; }

# Only the modules this step needs, so editing the server or the web page does not repeat the
# 100-second embedding step.
COPY src/main.py src/extract.py src/table.py src/introduction.py src/chunking.py \
     src/build_chunks.py src/build_index.py src/embeddings.py src/jsonl_io.py \
     src/config.py src/errors.py src/
RUN python src/main.py --pages 42 337 --extract \
 && python src/build_chunks.py \
 && python src/build_index.py \
 && rm data/PCI-DSS-v4_0_1.pdf

FROM python:3.14-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/bash app
USER app
WORKDIR /app
ENV HOME=/home/app PATH=/home/app/.local/bin:/opt/venv/bin:$PATH \
    HF_HOME=/opt/hf HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1

# Native installer: a single binary, no Node.js needed.
RUN curl -fsSL https://claude.ai/install.sh | bash && claude --version

COPY --from=prepare /opt/venv /opt/venv
COPY --from=prepare /opt/hf /opt/hf
COPY --from=prepare /app/data/chunks data/chunks
COPY --from=prepare /app/data/index data/index
COPY eval eval
COPY src src

EXPOSE 8000
# Inside a container the server must listen on all interfaces; `docker run -p 127.0.0.1:...`
# is what keeps it reachable from this machine only.
CMD ["python", "src/server.py", "--host", "0.0.0.0"]
