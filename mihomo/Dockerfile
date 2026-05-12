# ── Build stage ───────────────────────────────────────────────────────────────
ARG GO_VERSION=1.26
FROM golang:${GO_VERSION}-alpine AS builder

ARG MIHOMO_VERSION=unknown
ARG BUILDTIME

RUN apk add --no-cache git ca-certificates

WORKDIR /src
COPY . .

RUN mkdir -p /out
RUN CGO_ENABLED=0 go build \
      -tags with_gvisor \
      -trimpath \
      -ldflags "-s -w -buildid= \
        -X 'github.com/metacubex/mihomo/constant.Version=${MIHOMO_VERSION}' \
        -X 'github.com/metacubex/mihomo/constant.BuildTime=${BUILDTIME}'" \
      -o /out/mihomo .


# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM busybox:1.37-musl
LABEL org.opencontainers.image.source="https://github.com/MetaCubeX/mihomo"

ENV CLASH_HOME_DIR=/etc/mihomo

COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=builder /out/mihomo /mihomo

RUN mkdir -p /etc/mihomo
VOLUME ["/etc/mihomo"]

ENTRYPOINT ["/mihomo"]
