# Use a lightweight Python image to keep memory usage small
FROM python:3.11-slim-bullseye AS builder

WORKDIR /app

COPY ./requirements/base.txt .
RUN pip install --no-cache-dir -r base.txt

# Create a non-root user for security
RUN adduser --disabled-password --gecos "" appuser
USER appuser

# Explicitly copy the src directory from the root of the build context
COPY src ./src

# Add /app to the Python module search path
ENV PYTHONPATH=/app

EXPOSE 8000

# Run the FastAPI app with Uvicorn, specifying the port and host explicitly
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]