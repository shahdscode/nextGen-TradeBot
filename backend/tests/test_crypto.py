"""Unit tests for secret-at-rest encryption."""
from app.utils.crypto import encrypt_secret, decrypt_secret


def test_roundtrip():
    plain = "PKTEST1234567890SECRET"
    enc = encrypt_secret(plain)
    assert enc is not None
    assert enc.startswith("enc:")
    assert enc != plain                 # actually encrypted
    assert decrypt_secret(enc) == plain # recovers original


def test_ciphertext_is_not_plaintext():
    enc = encrypt_secret("supersecret")
    assert "supersecret" not in enc


def test_legacy_plaintext_passthrough():
    # Values stored before encryption have no 'enc:' prefix -> returned as-is.
    assert decrypt_secret("legacy-plain-key") == "legacy-plain-key"


def test_empty_values():
    assert encrypt_secret(None) is None
    assert encrypt_secret("") is None
    assert decrypt_secret(None) is None
    assert decrypt_secret("") is None


def test_two_encryptions_differ_but_decrypt_same():
    # Fernet uses a random IV -> different ciphertext, same plaintext.
    a, b = encrypt_secret("x"), encrypt_secret("x")
    assert a != b
    assert decrypt_secret(a) == decrypt_secret(b) == "x"
