# Lightweight image with just parrec2dcm and its dependencies installed -- for tasks that
# only need PAR/REC -> DICOM conversion (e.g. a script task whose PAR/REC input is already
# pushed to the host by Agora itself) and don't need gtagora-connector-py's Agora API client
# on top, unlike gtagora-connector-py's own "-converter" image
# (https://github.com/GyroTools/gtagora-connector-py/blob/master/Docker/converter/Dockerfile).
FROM python:3.10-slim
COPY . /src
WORKDIR /src
RUN pip install --no-cache-dir .
