ARG GO_VERSION=1.23.4
FROM golang:${GO_VERSION}-alpine AS builder

WORKDIR /app/
COPY ./OpenList .

RUN go mod download
RUN apk add --no-cache bash curl jq git
RUN bash build.sh release docker

FROM scratch

COPY --from=builder /app/bin/openlist /bin/openlist
COPY --from=builder /etc/ssl  /etc/ssl

WORKDIR /opt/openlist/

ENTRYPOINT [ "openlist", "server" ]
