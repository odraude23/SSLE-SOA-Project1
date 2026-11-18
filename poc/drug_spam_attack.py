"""
Drug/pharmaceutical spam attack — Threat 3 (content-based variant)

Sends high-score spam emails directly via SMTP to the mail server,
triggering SpamAssassin's drug-content rules (SC_DRUG_ERECTILE,
SC_DRUG_CHEAP_PILLS, SC_SUBJ_BUY_CHEAP) plus SpamAssassin built-ins
(DRUG_ED_CAPS, SUBJ_BUY, SUBJECT_DRUG_GAP_C, DRUGS_ERECTILE).

Expected total score: ~14 stars → Postfix DISCARDS via header_checks.
Result: zero emails delivered to operator@smartcity.local.

Usage (from attacker container or VM):
    python3 /root/poc/drug_spam_attack.py [--target HOST:PORT] [--count N] [--interval S]
"""

import argparse
import smtplib
import subprocess
import time
from email.message import EmailMessage


def _detect_ip() -> str:
    try:
        out = subprocess.check_output(
            ["incus", "list", "--format", "csv", "-c", "n4"],
            timeout=5, stderr=subprocess.DEVNULL
        ).decode()
        for line in out.splitlines():
            parts = line.split(",")
            if len(parts) >= 2 and "smartcity-services" in parts[0]:
                ip = parts[1].strip().split("/")[0]
                if ip:
                    return ip
    except Exception:
        pass
    return ""


_ip = _detect_ip()
_default_target = f"{_ip}:25" if _ip else "localhost:25"

DRUG_SUBJECTS = [
    "BUY CHEAP VIAGRA NOW FREE PILLS AND CIALIS",
    "SPECIAL OFFER: Cheap pills - Viagra, Cialis, Levitra",
    "Buy cheap generic pills - free shipping worldwide",
    "LIMITED TIME: free viagra and cialis samples",
    "BUY NOW: cheap sildenafil and tadalafil online",
]

DRUG_BODIES = [
    "buy viagra cheap free shipping now cialis generic pills levitra discount",
    "cheap pills online: viagra 50mg, cialis 20mg, levitra 10mg. free shipping!",
    "buy generic sildenafil online - same as viagra but cheap. tadalafil also available.",
    "get free viagra and cialis samples today. buy cheap pills with overnight delivery.",
    "best prices on erectile dysfunction pills: viagra, cialis, levitra. buy now!",
]


def send_drug_email(host: str, port: int, idx: int) -> bool:
    subject = DRUG_SUBJECTS[idx % len(DRUG_SUBJECTS)]
    body = DRUG_BODIES[idx % len(DRUG_BODIES)]

    msg = EmailMessage()
    msg["From"] = "spammer@external.com"
    msg["To"] = "operator@smartcity.local"
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=5) as s:
            s.sendmail("spammer@external.com", ["operator@smartcity.local"], msg.as_string())
        return True
    except Exception as e:
        print(f"  [!] SMTP error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Drug spam SMTP attack")
    parser.add_argument("--target", default=_default_target,
                        help=f"HOST:PORT of mail server (default: {_default_target})")
    parser.add_argument("--count", type=int, default=10,
                        help="Number of spam emails to send (default: 10)")
    parser.add_argument("--interval", type=float, default=0.5,
                        help="Seconds between emails (default: 0.5)")
    args = parser.parse_args()

    if ":" in args.target:
        host, port_str = args.target.rsplit(":", 1)
        port = int(port_str)
    else:
        host, port = args.target, 25

    print(f"[*] Drug spam attack → {host}:{port}")
    print(f"[*] Sending {args.count} pharmaceutical spam emails")
    print(f"[*] SpamAssassin will score each ~14+ → Postfix DISCARD")
    print()

    sent = 0
    for i in range(args.count):
        subject = DRUG_SUBJECTS[i % len(DRUG_SUBJECTS)]
        print(f"  [{i+1:02d}/{args.count}] Subject: {subject[:60]}")
        if send_drug_email(host, port, i):
            sent += 1
            print(f"         → accepted by SMTP (SpamAssassin will discard on delivery)")
        if i < args.count - 1:
            time.sleep(args.interval)

    print()
    print(f"[+] Attack complete: {sent}/{args.count} accepted by SMTP")
    print(f"[+] Check mailbox: none should appear (all discarded by SpamAssassin)")
    print(f"[+] Postfix log: look for 'discard: header X-Spam-Level'")
    print(f"[+] Verify: cat /var/log/mail/mail.log | grep discard")


if __name__ == "__main__":
    main()
