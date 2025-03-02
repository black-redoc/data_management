# Use official Python image
FROM python:3.12-slim

# Set working directory inside the container
WORKDIR /app

# Copy requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the source code
COPY src/api.py /app/api.py
COPY templates /app/templates
COPY static /app/static

# Expose the port
EXPOSE 8080

ARG DB_URL
ENV DB_URL=${DB_URL}

ARG CHUNK_SIZE
ENV CHUNK_SIZE=${CHUNK_SIZE}

# Run FastAPI with Uvicorn
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8080"]
