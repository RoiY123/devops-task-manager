"""Guards for the cheap password hashing that conftest.py swaps in for tests."""
from pwdlib import PasswordHash

from app.backend import security


# What the stored hash text says: Argon2id, 64 MiB memory, 3 passes, 4 threads.
PRODUCTION_SETTINGS = "$argon2id$v=19$m=65536,t=3,p=4$"


def test_production_hashes_passwords_with_strong_argon2_settings(
    production_password_hash: PasswordHash,
) -> None:
    # The real production hasher, once: about 90 ms.
    hashed = production_password_hash.hash("a-real-password-123")

    assert hashed.startswith(PRODUCTION_SETTINGS)
    assert production_password_hash.verify("a-real-password-123", hashed)
    assert not production_password_hash.verify("a-wrong-password-1", hashed)


def test_production_dummy_hash_costs_the_same_as_a_real_one(
    production_dummy_password_hash: str,
) -> None:
    # Unknown emails are checked against this; equal settings keep the timing equal.
    assert production_dummy_password_hash.startswith(PRODUCTION_SETTINGS)


def test_tests_really_use_the_cheap_settings() -> None:
    # Proves the swap is active, so a speed regression points here first.
    assert security.hash_password("password123").startswith("$argon2id$v=19$m=1024,t=1,p=1$")
