# Use an official Python runtime as the base image
# dgm-config: pin the Debian release so the mirror rewrite below is stable
FROM python:3.10-slim-bookworm

# dgm-config: optional apt/pip mirrors for hosts where deb.debian.org / pypi.org
# are unreachable. utils/docker_utils.py passes DGM_APT_MIRROR and
# DGM_PIP_INDEX_URL as build args; both default to empty (upstream behaviour).
ARG APT_MIRROR=
RUN if [ -n "$APT_MIRROR" ]; then \
      for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources /etc/apt/sources.list.d/*.list; do \
        if [ -f "$f" ]; then \
          sed -i "s|deb.debian.org|$APT_MIRROR|g; s|security.debian.org|$APT_MIRROR|g" "$f"; \
        fi; \
      done; \
    fi
ARG PIP_INDEX_URL=
RUN if [ -n "$PIP_INDEX_URL" ]; then pip config set global.index-url "$PIP_INDEX_URL"; fi

# Install system-level dependencies, including git
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /dgm

# Copy the entire repository into the container
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Keep the container running by default
CMD ["tail", "-f", "/dev/null"]