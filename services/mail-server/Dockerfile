FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    postfix \
    spamassassin \
    spamc \
    rsyslog \
    && rm -rf /var/lib/apt/lists/*

RUN sed -i '/imklog/s/^/#/' /etc/rsyslog.conf

COPY main.cf /etc/postfix/main.cf
COPY master.cf /etc/postfix/master.cf
RUN postfix upgrade-configuration 2>/dev/null || true
COPY local.cf /etc/spamassassin/local.cf
COPY start.sh /start.sh

RUN chmod +x /start.sh && \
    useradd -r -s /bin/false spamd || true && \
    mkdir -p /var/run/spamd /var/mail/smartcity.local && \
    chown spamd:spamd /var/run/spamd && \
    echo "operator: /var/mail/smartcity.local/operator" >> /etc/aliases && \
    newaliases

EXPOSE 25
CMD ["/start.sh"]
