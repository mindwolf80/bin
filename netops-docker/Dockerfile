FROM python:3.12-alpine

RUN apk add --no-cache \
    openssh-client tzdata ca-certificates git bash nano \
 && update-ca-certificates

ENV HTTP_PROXY="" \
    HTTPS_PROXY="" \
    NO_PROXY="" \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    NET_TEXTFSM=/usr/local/lib/python3.12/site-packages/ntc_templates/templates \
    TZ=America/Chicago

RUN pip install --no-cache-dir \
    netmiko==4.4.0 \
    scrapli==2024.7.30 \
    paramiko==3.4.0 \
    ntc-templates==5.1.0 \
    textfsm==1.1.3 \
    rich==13.7.1 \
    tqdm==4.66.4 \
    pandas==2.2.2

WORKDIR /work
RUN mkdir -p /work/scripts /work/data/outputs

COPY scripts/ /work/scripts/
COPY data/ /work/data/

ENTRYPOINT ["/bin/bash"]
