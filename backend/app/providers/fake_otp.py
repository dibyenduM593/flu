"""Simulated MSG91 OTP. In dev mode the code is returned to the caller so the UI can show it."""
import secrets


class FakeOtp:
    def send(self, phone: str) -> str:
        return f"{secrets.randbelow(1_000_000):06d}"
