FROM python:3.13-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy the application
COPY . .

# Set PATH to use uv's managed Python environment
ENV PATH="/app/.venv/bin:$PATH"

# Run the application
CMD ["python", "main.py"]
