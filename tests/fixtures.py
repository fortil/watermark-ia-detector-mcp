"""Offline fixtures: a localhost mock verifier and a JPEG signed at test time.

Nothing signed here is committed; the PKI is throwaway and trusted by nothing.
"""
from __future__ import annotations

import datetime
import io
import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import c2pa
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from PIL import Image

# Matches the claude profile in watermark_detector so detection attributes
# the fixture to a provider.
IPTC_DST = "http://cv.iptc.org/newscodes/digitalsourcetype/"
ORG = "Anthropic, PBC"
CN = "Anthropic Claude Content Signing"


@dataclass
class MockVerifier:
    url: str = ""
    requests: list[dict] = field(default_factory=list)


@contextmanager
def mock_verifier(response: dict | None = None, status: int = 200):
    mock = MockVerifier()
    payload = response if response is not None else {"result": {"likelihood": 0.87, "label": "likely"}}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            mock.requests.append({"headers": dict(self.headers), "body": body})
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    mock.url = f"http://127.0.0.1:{server.server_address[1]}/detect"
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield mock
    finally:
        server.shutdown()
        server.server_close()


def write_config(path: Path, url: str, name: str = "claude", api_key_env: str = "WMD_TEST_KEY") -> Path:
    fields = {
        "endpoint": url,
        "api_key_env": api_key_env,
        "score_path": "result.likelihood",
        "label_path": "result.label",
    }
    lines = [f"[verifiers.{name}]"]
    lines += [f"{k} = {json.dumps(v)}" for k, v in fields.items()]
    path.write_text("\n".join(lines) + "\n")
    return path


@dataclass(frozen=True)
class TestPki:
    __test__ = False  # not a pytest class

    chain_pem: bytes
    root_pem: bytes
    key_pem: bytes


def make_pki(org: str, cn: str) -> TestPki:
    start = datetime.datetime(2025, 12, 31, tzinfo=datetime.timezone.utc)
    end = start + datetime.timedelta(days=3650)

    def name(o: str, c: str) -> x509.Name:
        return x509.Name(
            [
                x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, o),
                x509.NameAttribute(NameOID.COMMON_NAME, c),
            ]
        )

    root_key = ec.generate_private_key(ec.SECP256R1())
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    root_name = name(org, f"{org} Test Root")
    leaf_name = name(org, cn)

    def build(subject, issuer, pub, signer_key, *, ca):
        b = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(pub)
            .serial_number(x509.random_serial_number())
            .not_valid_before(start)
            .not_valid_after(end)
            .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(pub), critical=False)
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(signer_key.public_key()), critical=False
            )
        )
        if not ca:
            b = b.add_extension(
                x509.KeyUsage(
                    digital_signature=True, content_commitment=False,
                    key_encipherment=False, data_encipherment=False,
                    key_agreement=False, key_cert_sign=False, crl_sign=False,
                    encipher_only=False, decipher_only=False,
                ),
                critical=True,
            ).add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
        return b.sign(signer_key, hashes.SHA256())

    root = build(root_name, root_name, root_key.public_key(), root_key, ca=True)
    leaf = build(leaf_name, root_name, leaf_key.public_key(), root_key, ca=False)
    pem = serialization.Encoding.PEM
    return TestPki(
        chain_pem=leaf.public_bytes(pem) + root.public_bytes(pem),
        root_pem=root.public_bytes(pem),
        key_pem=leaf_key.private_bytes(
            pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ),
    )


def signed_jpeg() -> tuple[bytes, TestPki]:
    """A 32x32 JPEG signed with a throwaway claude-like chain."""
    pki = make_pki(ORG, CN)
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (10, 20, 30)).save(buf, "JPEG", quality=90)
    manifest = {
        "claim_generator_info": [{"name": "Anthropic Files", "version": "1.0.0"}],
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {
                    "actions": [
                        {"action": "c2pa.created", "digitalSourceType": IPTC_DST + "trainedAlgorithmicMedia"},
                        {"action": "com.anthropic.claude.provided"},
                    ]
                },
            }
        ],
    }
    builder = c2pa.Builder(manifest)
    info = c2pa.C2paSignerInfo(
        alg=b"es256", sign_cert=pki.chain_pem, private_key=pki.key_pem, ta_url=None
    )
    signer = c2pa.Signer.from_info(info)
    dst = io.BytesIO()
    builder.sign(signer, "image/jpeg", io.BytesIO(buf.getvalue()), dst)
    return dst.getvalue(), pki
