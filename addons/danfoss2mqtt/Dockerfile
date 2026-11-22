ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20
FROM ${BUILD_FROM}

WORKDIR /app

# Install pydanfoss-cloud[mqtt] (zero Home Assistant core dependency) directly from the pinned
# release tag so Home Assistant Supervisor can build the add-on without requiring a PyPI mirror.
ARG PYDANFOSS_REF="2.0.0-alpha.1"
RUN apk add --no-cache git \
    && pip install --no-cache-dir \
       "pydanfoss-cloud[mqtt] @ git+https://github.com/aghulas/ha-danfoss-ally.git@${PYDANFOSS_REF}" \
    && apk del git

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
