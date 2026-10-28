# Sandbox + reproducible dev image: Go toolchain, GnuCOBOL, Python.
# If `gnucobol` is not found on this Debian release, use `gnucobol3` instead.
FROM golang:1.22-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends gnucobol python3 python3-pip \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --break-system-packages -r requirements.txt
COPY . .
CMD ["pytest", "-q"]