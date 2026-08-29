# Backend-only image for the AI Governance API. Ollama is expected to run
# separately (e.g. natively on the host desktop) -- see OLLAMA_URL in config.py.

FROM python:3.11-slim

WORKDIR /app

# Native build tools: some spaCy/SciSpaCy sub-dependencies fall back to a
# source build on platforms without a matching prebuilt wheel.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch explicitly, from PyTorch's own CPU wheel index,
# before anything else. Without this, pip resolves a CUDA-enabled torch build
# as a transitive dependency of detoxify/sentence-transformers below, dragging
# in several GB of NVIDIA CUDA toolkit libraries this container never uses --
# nothing in here does GPU inference; Ollama runs as its own separate process
# outside this image, not inside it.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Dependencies as their own layer, copied before the application code below.
# This is the slow, expensive part (spaCy, SciSpaCy, Detoxify,
# sentence-transformers) -- keeping it separate means editing api.py later
# doesn't force a 20+ minute reinstall on every rebuild.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# General-purpose spaCy model (the SciSpaCy medical model is already pinned
# by its direct URL in requirements.txt and installs with the pip step above).
RUN python -m spacy download en_core_web_lg

# Pre-warm the Detoxify and sentence-transformers model weights at build time
# instead of on the container's first request -- avoids a slow, surprising
# cold start every time the container restarts.
RUN python -c "from detoxify import Detoxify; Detoxify('unbiased')"
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Application code and the data files it reads at runtime. cohort.db is
# intentionally not copied -- database.init_db() creates and seeds it fresh
# on startup.
COPY api.py config.py database.py audit_logger.py custom_recognizers.py \
     benchmark_logger.py llm_watchdog.py diff_engine.py toxicity_guard.py \
     rag_engine.py notifications.py ./
COPY pii_rules.json test_cases.json config.json ./
COPY governance_policies/ ./governance_policies/

# config.json ships with CPU-only defaults baked into the image. To point a
# container at a GPU machine's Ollama (different models, different URL)
# without rebuilding, mount a machine-specific file over it at run time, e.g.:
#   docker run -v C:\path\to\gpu-config.json:/app/config.json ...

EXPOSE 8000

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
