FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container
COPY . /app

# Install dependencies
RUN pip install uv

# Expose the port FastAPI will run on
EXPOSE 8080

# Command to run your FastAPI app
# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
CMD ["uv", "run", "main.py"]
