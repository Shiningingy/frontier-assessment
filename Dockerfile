# Minimal image for the deterministic crawler. The LLM agent tiers are optional
# and need either ANTHROPIC_API_KEY (set at runtime) or the Claude CLI; neither is
# baked into the image so secrets never live in a layer.
FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

# Profiles (cached extraction rules) + config travel with the app.
COPY config.yaml ./
COPY profiles ./profiles

# Non-root for safety.
RUN useradd -m runner && chown -R runner /app
USER runner

ENTRYPOINT ["safco"]
CMD ["crawl"]
