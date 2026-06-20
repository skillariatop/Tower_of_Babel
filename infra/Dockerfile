FROM python:3.12-slim

WORKDIR /app

# Install dependencies separately for better layer caching
COPY pyproject.toml .
RUN pip install --no-cache-dir -e "." 2>/dev/null || pip install --no-cache-dir \
    "discord.py>=2.4" \
    "fastapi>=0.111" \
    "uvicorn[standard]>=0.30" \
    "httpx>=0.27" \
    "pydantic>=2.7" \
    "pydantic-settings>=2.3" \
    "PyYAML>=6.0" \
    "sqlalchemy>=2.0" \
    "aiosqlite>=0.20" \
    "python-dotenv>=1.0"

COPY . .
RUN pip install --no-cache-dir -e "."

# decisions/ and data/ are mounted as volumes in production
RUN mkdir -p /app/data /app/decisions

CMD ["python", "-m", "bot.main"]
