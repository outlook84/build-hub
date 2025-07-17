ARG CADDY_VERSION=2.10.0
FROM docker.io/caddy:${CADDY_VERSION}-builder-alpine AS builder

RUN apk add mailcap && \
    xcaddy build \
    --with github.com/caddy-dns/cloudflare \
    --with github.com/greenpau/caddy-security

FROM busybox:musl

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
COPY --from=builder /etc/ssl /etc/ssl
COPY --from=builder /etc/ca-certificates /etc/ca-certificates
COPY --from=builder /etc/ca-certificates.conf /etc/ca-certificates.conf
COPY --from=builder /etc/mime.types /etc/mime.types

ENV XDG_CONFIG_HOME=/etc/caddy/config
ENV XDG_DATA_HOME=/etc/caddy/data  

WORKDIR /etc/caddy

ENTRYPOINT [ "/usr/bin/caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile" ]