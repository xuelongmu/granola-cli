"""macOS safeStorage crypto, verified against harperreed/muesli's known-good vectors.

The keychain *read* is macOS-only, but the cipher math (PBKDF2 + AES-128-CBC for
`storage.dek`, AES-256-GCM for the cred file) is platform-independent — so these run
anywhere, including the Windows dev box. Vectors copied verbatim from muesli's
`session_decrypt.rs` tests.

Run: `uv run python tests/test_macos_crypto.py`  (or `pytest`).
"""
from __future__ import annotations

import base64
import json

from granola.crypto import aes_128_cbc_safestorage_decrypt, aes_gcm_decrypt

# kc_pw = "test-password"; DEK = bytes(range(32)); nonce = 0102..0c
TEST_KC_PW = "test-password"
TEST_DEK = bytes(range(32))
TEST_DEK_BLOB = (
    b"\x76\x31\x30\xe2\x31\xa6\xb2\x21\xf3\x7b\xb7\xbb\x6c\x18\x53\x26\x99\x94\x60"
    b"\xa4\xa4\xa5\x9f\xd7\x07\x26\xc6\x51\xca\x65\xe1\x08\x78\x3f\xb9\x8b\xf3\x50"
    b"\x2f\x9b\xd2\x8d\x4e\x7d\x28\x5e\x10\xc2\x43\x8a\xe5"
)
TEST_ENC_BLOB = (
    b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x7e\xc8\x29\xb0\x9f\xe7\x99"
    b"\xe9\x22\xfd\x0a\x23\x32\x29\xc8\x49\x20\x20\xc3\xd2\xb5\x1a\x3f\xb7\xca\x30"
    b"\x8a\x7b\xea\xd9\x1d\xa0\xea\x97\xb9\xe5\x4c\xce\xb0\xbd\xd1\xcf\xd9\x80\xb6"
    b"\xa8\xa7\x29\xf1\x9d\x2a\x8e\x88\xbb\x0c\x2d\x14\x17\x7b\xb9\x41\x63\x5b\x68"
    b"\x0e\x53\x78\x4a\xd8\xad\x7f\x9d\x69\x6f\x2d\xeb\x9d\x93\x3b\xf7\x62\x77\x37"
    b"\xd7\x5c\x58\xbc\x78\xf1\x24"
)
TEST_PLAINTEXT = (
    b'{"session_id":"abc","workos_tokens":"{\\"access_token\\":\\"jwt.body.sig\\"}"}'
)


def test_safestorage_dek_unwrap_matches_vector():
    """storage.dek (v10 CBC) -> base64 text -> 32-byte DEK."""
    cbc_plain = aes_128_cbc_safestorage_decrypt(TEST_DEK_BLOB, TEST_KC_PW)
    assert base64.b64decode(cbc_plain.decode("utf-8")) == TEST_DEK


def test_cred_file_gcm_decrypt_matches_vector():
    """supabase.json.enc (nonce|ct|tag) -> AES-256-GCM(DEK) -> JSON."""
    pt = aes_gcm_decrypt(TEST_ENC_BLOB, TEST_DEK)  # prefix_len=0, iv_len=12
    assert pt == TEST_PLAINTEXT
    parsed = json.loads(pt)
    assert parsed["session_id"] == "abc"
    assert json.loads(parsed["workos_tokens"])["access_token"] == "jwt.body.sig"


def test_wrong_keychain_password_is_rejected():
    try:
        out = aes_128_cbc_safestorage_decrypt(TEST_DEK_BLOB, "wrong-password")
        # If padding happened to validate, the base64/DEK decode must still fail.
        base64.b64decode(out.decode("utf-8"))
        raise AssertionError("wrong password unexpectedly produced valid output")
    except Exception:
        pass  # expected: bad padding / non-utf8 / non-base64


def test_tampered_gcm_tag_is_rejected():
    tampered = bytearray(TEST_ENC_BLOB)
    tampered[-1] ^= 0x01
    try:
        aes_gcm_decrypt(bytes(tampered), TEST_DEK)
        raise AssertionError("tampered tag unexpectedly authenticated")
    except Exception:
        pass  # expected: GCM auth failure


def test_missing_v10_prefix_is_rejected():
    try:
        aes_128_cbc_safestorage_decrypt(b"v09" + TEST_DEK_BLOB[3:], TEST_KC_PW)
        raise AssertionError("missing v10 prefix should raise")
    except ValueError as exc:
        assert "v10" in str(exc)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS  {fn.__name__}")
    print(f"\n{len(fns)} macOS-crypto vector tests passed.")
