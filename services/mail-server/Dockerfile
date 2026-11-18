FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    postfix \
    spamassassin \
    spamc \
    python3 \
    python3-pip \
    && pip3 install --no-cache-dir prometheus-client \
    && rm -rf /var/lib/apt/lists/*

COPY main.cf /etc/postfix/main.cf
COPY master.cf /etc/postfix/master.cf
COPY header_checks /etc/postfix/header_checks
COPY local.cf /etc/spamassassin/local.cf
COPY mail_exporter.py /mail_exporter.py
COPY start.sh /start.sh

RUN chmod +x /start.sh && \
    useradd -r -s /bin/false spamd || true && \
    mkdir -p /var/run/spamd /var/mail/smartcity.local && \
    chown spamd:spamd /var/run/spamd && \
    echo "operator: /var/mail/smartcity.local/operator" >> /etc/aliases && \
    newaliases

EXPOSE 25
CMD ["/start.sh"]
