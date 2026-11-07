from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
import shutil
import socketserver
import ssl
from threading import Thread

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import httpx
from pydantic import SecretStr
import pytest

from app.customer_email import deliver, stamp
from app.customer_smtp import MAILER
from test_hosted_followup import configured_mail, issue_email


class Mailbox(socketserver.StreamRequestHandler):
    def handle(self):
        def reply(line):
            self.wfile.write(line + b"\r\n")

        recipient = b""
        reply(b"220 fixture.local ESMTP")
        while line := self.rfile.readline():
            command = line.split(maxsplit=1)[0].upper()
            if command in (b"EHLO", b"HELO"):
                reply(b"250-fixture.local\r\n250 AUTH PLAIN")
            elif command == b"AUTH":
                reply(b"235 authenticated")
            elif command == b"MAIL":
                reply(b"250 sender accepted")
            elif command == b"RCPT":
                recipient = line.strip()
                reply(b"250 recipient accepted")
            elif command == b"DATA":
                reply(b"354 send message")
                data = []
                while (part := self.rfile.readline()) not in (b".\r\n", b""):
                    data.append(part)
                self.server.transfers.append((recipient, b"".join(data)))
                if b"uncertain@" in recipient:
                    # Drop the connection after DATA without reporting acceptance.
                    return
                if b"retry@" in recipient and not self.server.deferred:
                    self.server.deferred = True
                    reply(b"451 temporarily unavailable")
                else:
                    reply(b"250 accepted")
            elif command == b"QUIT":
                reply(b"221 goodbye")
                return
            else:
                reply(b"500 unmodeled")


class MailServer(socketserver.ThreadingTCPServer):
    daemon_threads = True

    def get_request(self):
        connection, peer = super().get_request()
        connection.settimeout(5)
        try:
            return self.tls.wrap_socket(connection, server_side=True), peer
        except (ssl.SSLError, OSError):
            connection.close()
            raise


@pytest.fixture
def local_smtp(tmp_path, monkeypatch):
    if (
        not shutil.which("node")
        or not (MAILER / "node_modules" / "nodemailer").is_dir()
    ):
        pytest.skip("Install backend/mailer dependencies to run SMTP integration")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    identity = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(identity)
        .issuer_name(identity)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    certfile, keyfile = tmp_path / "fixture.crt", tmp_path / "fixture.key"
    certfile.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    monkeypatch.setenv("NODE_EXTRA_CA_CERTS", str(certfile))
    with MailServer(("127.0.0.1", 0), Mailbox) as server:
        server.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server.tls.load_cert_chain(certfile, keyfile)
        server.transfers = []
        server.deferred = False
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_nodemailer_delivers_over_tls_and_retries_only_explicit_rejections(
    client, local_smtp
):
    settings = configured_mail(client)
    settings.customer_email_transport = "smtp"
    settings.smtp_host = "127.0.0.1"
    settings.smtp_port = local_smtp.server_address[1]
    settings.smtp_secure = True
    settings.smtp_user = "updates@example.com"
    settings.smtp_password = SecretStr("synthetic-smtp-password")
    settings.smtp_from = "updates@example.com"
    store = client.app.state.store
    for recipient in ("success", "retry", "uncertain", "interrupted"):
        issue_email(client, "SMTP-" + recipient, recipient + "@example.com")
    now = datetime.now(timezone.utc)
    with store.transaction(write=True) as db:
        # A previous worker died after taking an SMTP lease.
        db.execute(
            """UPDATE customer_mail_outbox SET lease_id='fixture-lease',delivery_transport='smtp',attempts=1,next_attempt_at=?
               WHERE recipient='interrupted@example.com'""",
            (stamp(now - timedelta(seconds=1)),),
        )
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: pytest.fail("SMTP must not call Resend")
        )
    ) as http:
        first = deliver(store, settings, http, now=now)
        assert first == {"accepted": 1, "retry": 1, "failed": 1, "cancelled": 0}
        assert (
            deliver(store, settings, http, now=now + timedelta(minutes=2))["accepted"]
            == 1
        )
    with store.transaction() as db:
        assert {
            row["recipient"].split("@")[0]: (row["status"], row["attempts"])
            for row in db.execute(
                "SELECT recipient,status,attempts FROM customer_mail_outbox"
            )
        } == {
            "success": ("accepted", 1),
            "retry": ("accepted", 2),
            "uncertain": ("failed", 1),
            "interrupted": ("failed", 1),
        }
    assert len(local_smtp.transfers) == 4
    assert all(
        b"Message-ID: <resolve." in message for _, message in local_smtp.transfers
    )
    retries = [
        message for recipient, message in local_smtp.transfers if b"retry@" in recipient
    ]
    assert len(retries) == 2
    assert [
        line for line in retries[0].splitlines() if line.startswith(b"Message-ID:")
    ] == [line for line in retries[1].splitlines() if line.startswith(b"Message-ID:")]
