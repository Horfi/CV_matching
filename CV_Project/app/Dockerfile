# Use a lightweight Python version
FROM python:3.10-slim

# Set the working directory inside the container
WORKDIR /code

# Copy your list of libraries and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Keep the container running so you can execute scripts
CMD ["tail", "-f", "/dev/null"]