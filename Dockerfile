# Use a slim Python image to keep the container small
FROM python:3.12-slim

# Set working directory inside the container
WORKDIR /app

# Install dependencies first (separate layer — only re-runs when requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source
COPY scaleway-chat.py .

# Streamlit listens on 8501 by default
EXPOSE 8501

# Disable the browser auto-open and set the server address so it binds
# to all interfaces (required inside a container)
CMD ["streamlit", "run", "scaleway-chat.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
