# Use a lightweight Python image to keep memory usage small
FROM python:3.11-slim-bullseye AS builder

WORKDIR /app

COPY ./requirements/base.txt .
RUN pip install --no-cache-dir -r base.txt

# Create a non-root user for security
RUN adduser --disabled-password --gecos "" appuser
RUN apt-get update && apt-get install -y curl iputils-ping
USER appuser

# Explicitly copy the src directory from the root of the build context
COPY src ./src

# Add /app to the Python module search path
ENV PYTHONPATH=/app

EXPOSE 8000

# Run the FastAPI app with Uvicorn, specifying workers for a 2-core system
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "5"]