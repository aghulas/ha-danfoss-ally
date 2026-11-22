ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20
FROM ${BUILD_FROM}

WORKDIR /app

# Install pydanfoss-cloud with paho-mqtt (zero Home Assistant core dependency).
# In a release image this installs from PyPI; for local add-on builds from the repo root,
# switch to `COPY . /src && pip install --no-cache-dir "/src[mqtt]"`.
ARG PYDANFOSS_VERSION=">=0.3.1"
RUN pip install --no-cache-dir "pydanfoss-cloud[mqtt]${PYDANFOSS_VERSION}"

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
