# 1. Use a stable Python image that supports apt-get
FROM python:3.11-slim

# 2. Install FFmpeg as a system package
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# 3. Set the working directory
WORKDIR /app

# 4. Copy the requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of the application code
COPY . .

# 6. Expose the port (Render handles mapping)
EXPOSE 10000

# 7. Set the startup command
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:$PORT"]