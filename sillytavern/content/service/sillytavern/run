#!/bin/sh

if [ ! -e "config/config.yaml" ]; then
    echo "Resource not found, copying from defaults: config.yaml"
    cp -r "default/config.yaml" "config/config.yaml"
fi

sed -i 's/listen: false/listen: true/' "./config/config.yaml" || true
sed -i 's/whitelistMode: true/whitelistMode: false/' "./config/config.yaml" || true
sed -i 's/basicAuthMode: false/basicAuthMode: true/' "./config/config.yaml" || true

PASSWORD=$(head -c 128 /dev/urandom | tr -dc 'A-Za-z0-9' | head -c 16)
sed -i 's/password: "password"/password: "'"$PASSWORD"'"/' "./config/config.yaml" || true

# Execute postinstall to auto-populate config.yaml with missing values
npm run postinstall

# Start the server
exec node server.js --listen "$@"