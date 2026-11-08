import hmac
import hashlib
from core.security import (
    verify_hmac_sha1_signature,
    generate_verification_code,
    encrypt_payload,
    decrypt_payload,
)


def test_hmac_sha1_verification():
    secret = "test-secret-12345"
    payload = b"<feed><entry><title>Test Video</title></entry></feed>"
    computed_sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha1).hexdigest()
    header = f"sha1={computed_sig}"

    # Valid signature
    assert verify_hmac_sha1_signature(payload, header, secret) is True

    # Invalid secret
    assert verify_hmac_sha1_signature(payload, header, "wrong-secret") is False

    # Corrupted payload
    assert verify_hmac_sha1_signature(b"tampered payload", header, secret) is False


def test_verification_code_format():
    code = generate_verification_code(6)
    assert code.startswith("VERIFY-")
    assert len(code) == 13  # "VERIFY-" (7 chars) + 6 chars
    # Ensure ambiguous chars not present
    for bad_char in ["0", "O", "1", "I"]:
        assert bad_char not in code.split("-")[1]


def test_encryption_and_decryption():
    secret_text = "Login: creator@gmail.com | Pass: SuperSecretP@ss99 | 2FA: 123456"
    ciphertext = encrypt_payload(secret_text)
    assert ciphertext != secret_text

    decrypted = decrypt_payload(ciphertext)
    assert decrypted == secret_text

