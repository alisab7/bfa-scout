"""
app/auth/validators.py — shared input validators for auth flows.

Phase 8.1 / 8.1.1: password complexity policy
  - Min 8 characters  (Phase 8.1 originally specified 12; revised to 8 in
                       Phase 8.1.1 — see function docstring and CHANGELOG v1.8.3)
  - At least one lowercase letter
  - At least one uppercase letter
  - At least one digit
  - Max 128 characters (DoS prevention)

Special characters are encouraged but not required — too restrictive in
practice for users who type on Arabic/English keyboards interchangeably.
"""

import re


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Check *password* against the BFA-Scout complexity policy.

    Returns:
        (True, '')              if the password meets all requirements.
        (False, error_message)  otherwise.

    Policy (Phase 8.1.1):
      - Min 8 characters
      - At least one lowercase letter
      - At least one uppercase letter
      - At least one digit
      - At least one special character
      - Max 128 characters (DoS prevention)

    NOTE: Do NOT call this on existing stored hashes — only on plaintext
    passwords supplied during create / reset / change flows.
    """
    if not password:
        return False, 'Password is required.'
    if len(password) < 8:
        return False, 'Password must be at least 8 characters.'
    if len(password) > 128:
        return False, 'Password must be at most 128 characters.'
    if not re.search(r'[a-z]', password):
        return False, 'Password must contain at least one lowercase letter.'
    if not re.search(r'[A-Z]', password):
        return False, 'Password must contain at least one uppercase letter.'
    if not re.search(r'\d', password):
        return False, 'Password must contain at least one digit.'
    if not re.search(r'[!@#$%^&*()\-_=+\[\]{};:\'",.<>/?\\|`~]', password):
        return False, 'Password must contain at least one special character.'
    return True, ''
