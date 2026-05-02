"""
generate_vapid_keys.py

Run this ONCE on PythonAnywhere (or anywhere with cryptography installed)
to print a VAPID keypair. Paste the output into your WSGI file's
`os.environ[...]` lines as VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY.

    python3 generate_vapid_keys.py
"""

import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def main():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    # The Web Push standard wants the raw 32-byte private value and
    # the uncompressed 65-byte (0x04 || X || Y) public point, both
    # base64url encoded without padding.
    priv_num = private_key.private_numbers().private_value
    priv_bytes = priv_num.to_bytes(32, "big")

    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )

    print("VAPID_PUBLIC_KEY  =", b64url(pub_bytes))
    print("VAPID_PRIVATE_KEY =", b64url(priv_bytes))
    print()
    print("Paste these into your WSGI file. Don't share the private key.")


if __name__ == "__main__":
    main()
