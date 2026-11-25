# DDDS Cloud - Production Dockerfile
FROM python:3.11-slim

# Prevent Python from writing .pyc and buffer stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOME=/tmp
ENV SAL_USE_VCLPLUGIN=gen

WORKDIR /app

# Install system dependencies:
# - build-essential, curl
# - complete libreoffice suite (headless docx & pptx conversion)
# - fonts-liberation, fonts-dejavu-core, fonts-noto-core, fonts-freefont-ttf (complete Cyrillic/Latin typography)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    libreoffice \
    fonts-liberation \
    fonts-dejavu-core \
    fonts-noto-core \
    fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/*

# Install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project code
COPY . .

# Create runtime directories
RUN mkdir -p uploads cache data

EXPOSE 8000

CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "8000"]
