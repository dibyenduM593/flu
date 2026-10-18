"""MSG91 OTP (control.msg91.com/api/v5/otp), authkey header.

MSG91_OTP_VERIFY=flu (default): Flu generates the code and MSG91 only delivers it, so identity.verify_otp keeps
checking Flu's own hash, attempts and expiry. MSG91_OTP_VERIFY=msg91: MSG91 generates the code, send() returns
None and verify() asks MSG91. India needs a DLT-approved template either way; the DLT template id and sender id are
set on the MSG91 template (register_dlt_template), not on each send.

MSG91 reports most failures as HTTP 200 with {"type": "error"}, so every call branches on `type`.
The test suite runs this against httpx.MockTransport only."""
import re
import secrets

import httpx

from ..config import settings
from .base import ProviderError, ProviderUnavailable

OTP_LENGTH = 6
OTP_EXPIRY_MIN = 5  # matches OtpCode.expires_at in identity.send_otp


class Msg91Otp:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.http = httpx.Client(base_url=settings.msg91_base_url, transport=transport, timeout=15,
                                 headers={"authkey": settings.msg91_auth_key})

    @property
    def verifies(self) -> bool:
        return settings.msg91_otp_verify == "msg91"

    def _call(self, method: str, path: str, params: dict, body: dict | None = None) -> dict:
        try:
            r = self.http.request(method, path, params=params, json=body)
        except httpx.TransportError as e:
            raise ProviderUnavailable("msg91_unreachable", str(e)) from e
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code in (401, 403, 429) or r.status_code >= 500:
            raise ProviderUnavailable(f"msg91_http_{r.status_code}", data.get("message") or r.text[:200])
        if r.status_code >= 400:
            raise ProviderError(f"msg91_http_{r.status_code}", data.get("message") or r.text[:200])
        return data

    # POST /api/v5/otp?template_id=&mobile=91XXXXXXXXXX[&otp=]
    def send(self, phone: str) -> str | None:
        code = None if self.verifies else f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"
        params = {"template_id": settings.msg91_template_id, "mobile": _mobile(phone),
                  "otp_length": OTP_LENGTH, "otp_expiry": OTP_EXPIRY_MIN, "realTimeResponse": 1}
        if code:
            params["otp"] = code
        d = self._call("POST", "/api/v5/otp", params, {})
        if d.get("type") != "success":
            # Template, sender or DLT configuration errors: nothing the user can fix.
            raise ProviderUnavailable("msg91_send_failed", d.get("message") or "MSG91 did not accept the OTP")
        return code

    # GET /api/v5/otp/verify?otp=&mobile=
    def verify(self, phone: str, code: str) -> bool:
        d = self._call("GET", "/api/v5/otp/verify", {"otp": code, "mobile": _mobile(phone)})
        if d.get("type") == "success":
            return True
        msg = (d.get("message") or "").lower()
        if "not match" in msg or "expired" in msg or "already verified" in msg or "invalid otp" in msg:
            return False
        raise ProviderUnavailable("msg91_verify_failed", d.get("message") or "MSG91 could not verify the OTP")

    # POST /api/v5/otp/updateOtpTemplate: one-time setup tying the MSG91 template to its DLT registration.
    # `template` must match the DLT-approved text exactly and contain ##OTP##.
    def register_dlt_template(self, template: str) -> dict:
        if "##OTP##" not in template:
            raise ProviderError("template_invalid", "the OTP template must contain ##OTP##")
        d = self._call("POST", "/api/v5/otp/updateOtpTemplate", {}, {
            "templateId": settings.msg91_template_id, "template": template,
            "dltTemplateId": settings.msg91_dlt_te_id, "senderId": settings.msg91_sender_id})
        if d.get("type") != "success":
            raise ProviderError("template_update_failed", d.get("message") or "MSG91 rejected the template")
        return d


def _mobile(phone: str) -> str:
    """+91 98765 43210 -> 919876543210 (MSG91 wants the country code without '+')."""
    digits = re.sub(r"\D", "", phone)
    return digits if len(digits) > 10 else "91" + digits[-10:]
