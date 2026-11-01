FROM python:3.13-slim

# uv pinned (":latest" made every rebuild a different toolchain)
COPY --from=ghcr.io/astral-sh/uv:0.6.1 /uv /bin/uv

# Set up non-root user for Hugging Face Spaces (user ID 1000)
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

# Set working directory
WORKDIR /home/user/app

# Install EXACTLY what uv.lock pins (the lock is the source of truth; `uv sync` without --frozen could
# silently re-resolve to newer versions at build time). Dev tools are not shipped.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy the rest of the project
COPY . .

# Expose Hugging Face's default port
EXPOSE 7860

# Liveness probe (the readiness check with auth/DB detail is /ready)
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD ["/home/user/app/.venv/bin/python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7860/health', timeout=4).status == 200 else 1)"]

# Run the app with Uvicorn for production (adjust --workers based on CPU)
CMD ["/home/user/app/.venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "2"]
