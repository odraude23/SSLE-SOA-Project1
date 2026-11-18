"""
Postfix mail metrics exporter for Prometheus.
Tails /var/log/mail/mail.log and counts three events:
  - postfix_messages_received_total  (new SMTP message accepted)
  - postfix_spam_discarded_total     (SpamAssassin DISCARD fired)
  - postfix_messages_delivered_total (email delivered to local mailbox)
Exposes metrics on port 9154.
"""

import os
import re
import time
from prometheus_client import Counter, start_http_server

LOG_FILE = "/var/log/mail/mail.log"
PORT = 9154

RECEIVED_RE  = re.compile(r"postfix/smtpd.*client=")
DISCARD_RE   = re.compile(r"discard: header X-Spam-Level")
DELIVERED_RE = re.compile(r"postfix/local.*status=sent")

messages_received  = Counter("postfix_messages_received_total",
                              "SMTP messages accepted by Postfix")
spam_discarded     = Counter("postfix_spam_discarded_total",
                              "Emails discarded by SpamAssassin content filter")
messages_delivered = Counter("postfix_messages_delivered_total",
                              "Emails delivered to local mailbox")


def tail_forever():
    while not os.path.exists(LOG_FILE):
        time.sleep(2)
    with open(LOG_FILE, "r") as f:
        f.seek(0, 2)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.1)
                continue
            if DISCARD_RE.search(line):
                spam_discarded.inc()
            elif RECEIVED_RE.search(line):
                messages_received.inc()
            elif DELIVERED_RE.search(line):
                messages_delivered.inc()


if __name__ == "__main__":
    start_http_server(PORT)
    print(f"[mail-exporter] listening on :{PORT}", flush=True)
    tail_forever()
