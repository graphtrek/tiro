# Use a slim Python image to keep the container small
FROM python:3.12-slim

# Set working directory inside the container
WORKDIR /app

# Install dependencies first (separate layer — only re-runs when requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download and cache the ChromaDB default embedding model so it is baked
# into the image and does not need to be fetched at container start-up.
# Set HOME to a shared path so the model lands outside /root/ and is readable
# by the non-root runtime user.
ENV HOME=/opt/app-home
RUN mkdir -p /opt/app-home && \
    python -c "\
from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2; \
ef = ONNXMiniLM_L6_V2(); \
ef(['warmup']) \
" && chmod -R 755 /opt/app-home

# Copy the application source
COPY Chat.py .
COPY rag_utils.py .
COPY pages/ pages/

# Ensure uploads directory exists
RUN mkdir -p /app/uploads

# Copy Streamlit configuration (needed for correct WS URLs behind a reverse proxy)
COPY .streamlit/ .streamlit/

# Streamlit listens on 8501 by default
EXPOSE 8501

# Disable the browser auto-open and set the server address so it binds
# to all interfaces (required inside a container)
CMD ["streamlit", "run", "Chat.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
