FROM node:alpine

ARG N8N_VERSION=1.103.2

RUN apk add --no-cache tzdata git openssh openssl graphicsmagick ca-certificates jq libc6-compat \
    && npm i n8n@${N8N_VERSION} -g \
    && rm -rf ${HOME}/.npm

ENV N8N_USER_FOLDER=/data

ENTRYPOINT ["n8n", "start"]