# Use an official Python runtime as a parent image
FROM python:3.9-slim-buster

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install uv and then install dependencies
RUN pip install uv && uv sync

# Run the main.py when the container launches
CMD ["uv", "run", "main.py", "start"]
