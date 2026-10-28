"""Test-run only: PBKDF2 with few iterations so the automated tests finish quickly.
The hash format is unchanged ("pbkdf2_sha256$..."). Never used when the server runs."""
from django.contrib.auth.hashers import PBKDF2PasswordHasher


class FastPBKDF2PasswordHasher(PBKDF2PasswordHasher):
    iterations = 1000
