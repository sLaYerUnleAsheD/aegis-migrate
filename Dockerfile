# Dev + sandbox image: Go toolchain, GnuCOBOL, Python.
# If `gnucobol` is not found on this Debian release, use `gnucobol3` instead.
FROM golang:1.26-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends gnucobol python3 python3-pip \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --break-system-packages -r requirements.txt

# Warm the Go build cache (standard library + vendored decimal) so sandboxed builds
# take seconds. This layer is rebuilt only when go_harness/ or the warm-up file changes.
# If this step fails, delete it: everything still works, builds are just slower.
ENV GOCACHE=/gocache GOTOOLCHAIN=local CGO_ENABLED=0
COPY go_harness /app/go_harness
COPY scripts/warmup_main.go /tmp/warmup_main.go
RUN mkdir -p /gocache /tmp/warm \
 && cp -r /app/go_harness/. /tmp/warm/ \
 && cp /tmp/warmup_main.go /tmp/warm/main.go \
 && cd /tmp/warm && go build -trimpath -mod=vendor -o /tmp/warm/prog . \
 && chmod -R a+rwX /gocache \
 && rm -rf /tmp/warm /tmp/warmup_main.go

COPY . .
CMD ["pytest", "-q"]