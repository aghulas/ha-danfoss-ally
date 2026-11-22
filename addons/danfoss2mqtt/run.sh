#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -euo pipefail

# Auto-discover Home Assistant's Mosquitto broker when mqtt_host is left empty.
MQTT_HOST="$(bashio::config 'mqtt_host')"
if [ -z "${MQTT_HOST}" ] && bashio::services.available "mqtt"; then
    export DANFOSS_MQTT_HOST="$(bashio::services mqtt "host")"
    export DANFOSS_MQTT_PORT="$(bashio::services mqtt "port")"
    export DANFOSS_MQTT_USERNAME="$(bashio::services mqtt "username")"
    export DANFOSS_MQTT_PASSWORD="$(bashio::services mqtt "password")"
    bashio::log.info "Using Home Assistant Mosquitto service at ${DANFOSS_MQTT_HOST}:${DANFOSS_MQTT_PORT}"
fi

export DANFOSS_OPTIONS_FILE="/data/options.json"
bashio::log.info "Starting danfoss2mqtt bridge..."
exec danfoss2mqtt --options "${DANFOSS_OPTIONS_FILE}"
