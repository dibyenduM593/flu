"""Live provider adapters (Razorpay, Cashfree Verification Suite, MSG91) against httpx.MockTransport: request shapes,
response mapping and error handling, plus kyc.submit and the OTP login path running through them. No network."""
import base64
import json
from dataclasses import replace
from urllib.parse import parse_qs

import httpx
import pytest

from app import providers
from app.config import settings
from app.providers import kyc_live, otp_live
from app.providers.base import ProviderError, ProviderUnavailable
from app.providers.kyc_live import CashfreeKyc
from app.providers.otp_live import Msg91Otp
from app.providers.razorpay_live import RazorpayLive
from razorpay_mock import RazorpayMock


class Recorder:
    """MockTransport handler that records requests and answers from a list of (status, json) or a callable."""

    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if callable(r):
            return r(req)
        status, body = r
        return httpx.Response(status, json=body)

    @property
    def transport(self):
        return httpx.MockTransport(self)

    def body(self, i: int = -1) -> dict:
        return json.loads(self.requests[i].content)

    def query(self, i: int = -1) -> dict:
        return {k: v[0] for k, v in parse_qs(self.requests[i].url.query.decode()).items()}


ADDRESS = {"street1": "12 MG Road", "street2": "Koregaon Park", "city": "Pune", "state": "Maharashtra",
           "postal_code": "411001"}


# ------------------------------------------------------------------ Razorpay
def test_razorpay_order_uses_basic_auth_and_paise():
    rec = Recorder((200, {"id": "order_1", "entity": "order", "amount": 500000, "currency": "INR", "status": "created"}))
    out = RazorpayLive(transport=rec.transport).create_order(500000, "topup_abc", {"org_id": "o1", "n": 7})
    req = rec.requests[0]
    assert (req.method, str(req.url)) == ("POST", "https://api.razorpay.com/v1/orders")
    assert req.headers["authorization"] == "Basic " + base64.b64encode(
        f"{settings.razorpay_key_id}:{settings.razorpay_key_secret}".encode()).decode()
    assert rec.body() == {"amount": 500000, "currency": "INR", "receipt": "topup_abc", "notes": {"org_id": "o1", "n": "7"}}
    assert out["id"] == "order_1"


def test_razorpay_transfer_hold_release_reverse():
    mock = RazorpayMock(settings.razorpay_key_id, settings.razorpay_key_secret)
    rzp = RazorpayLive(transport=mock.transport)
    t = rzp.create_transfer("pay_1", "acc_1", 25000, {"hire_id": "h1"}, on_hold=True)
    assert t["entity"] == "transfer" and t["on_hold"] and t["amount"] == 25000
    method, path, body = mock.calls[-1]
    assert (method, path) == ("POST", "/v1/payments/pay_1/transfers")
    assert body == {"transfers": [{"account": "acc_1", "amount": 25000, "currency": "INR", "notes": {"hire_id": "h1"},
                                   "on_hold": True}]}
    assert rzp.reverse_transfer(t["id"], 5000)["entity"] == "reversal"
    assert mock.calls[-1] == ("POST", f"/v1/transfers/{t['id']}/reversals", {"amount": 5000})
    assert rzp.release_transfer(t["id"])["on_hold"] is False
    assert mock.calls[-1] == ("PATCH", f"/v1/transfers/{t['id']}", {"on_hold": False})
    assert rzp.transfer_settlement(t["id"]) is None  # released, not settled yet
    s = mock.settle("acc_1")
    got = rzp.transfer_settlement(t["id"])
    assert got["utr"] == s["utr"] and got["status"] == "processed"
    assert [x["id"] for x in rzp.settlement_transfers(s["id"])] == [t["id"]]


def test_razorpay_list_paginates():
    rows = [{"id": f"trf_{i}"} for i in range(103)]

    def page(req):
        q = parse_qs(req.url.query.decode())
        skip, count = int(q["skip"][0]), int(q["count"][0])
        return httpx.Response(200, json={"entity": "collection", "items": rows[skip:skip + count]})

    rec = Recorder(page)
    assert len(RazorpayLive(transport=rec.transport).list("transfer")) == 103
    assert [(r.url.path, rec.query(i)["skip"]) for i, r in enumerate(rec.requests)] == [("/v1/transfers", "0"),
                                                                                        ("/v1/transfers", "100")]


@pytest.mark.parametrize("status,body,exc,code", [
    (400, {"error": {"code": "BAD_REQUEST_ERROR", "description": "The amount must be at least INR 1.00"}},
     ProviderError, "BAD_REQUEST_ERROR"),
    (401, {"error": {"code": "BAD_REQUEST_ERROR", "description": "Authentication failed"}}, ProviderUnavailable,
     "BAD_REQUEST_ERROR"),
    (502, {}, ProviderUnavailable, "razorpay_http_502"),
])
def test_razorpay_errors(status, body, exc, code):
    rec = Recorder((status, body))
    with pytest.raises(exc) as e:
        RazorpayLive(transport=rec.transport).get_payment("pay_x")
    assert e.value.code == code
    if status == 400:
        assert type(e.value) is ProviderError and "at least INR 1.00" in str(e.value)


def test_razorpay_network_error_is_unavailable():
    def boom(req):
        raise httpx.ConnectTimeout("timed out", request=req)
    with pytest.raises(ProviderUnavailable):
        RazorpayLive(transport=httpx.MockTransport(boom)).release_transfer("trf_1")


def _linked_account_responder(fail_stakeholder=False):
    def respond(req):
        p = req.url.path
        if p == "/v2/accounts":
            return httpx.Response(200, json={"id": "acc_new1", "type": "route", "status": "created"})
        if p.endswith("/stakeholders"):
            if fail_stakeholder:
                return httpx.Response(400, json={"error": {"code": "BAD_REQUEST_ERROR", "description": "Invalid PAN"}})
            return httpx.Response(200, json={"id": "sth_1", "entity": "stakeholder"})
        if p.endswith("/products"):
            return httpx.Response(200, json={"id": "acc_prd_1", "product_name": "route",
                                             "activation_status": "needs_clarification", "requirements": [{}]})
        return httpx.Response(200, json={"id": "acc_prd_1", "activation_status": "activated", "requirements": []})
    return respond


def test_razorpay_linked_account_for_individual():
    rec = Recorder(_linked_account_responder())
    out = RazorpayLive(transport=rec.transport).create_linked_account(
        "Riya Kulkarni", "riya@example.com", "1234", phone="+919000000001", pan="ABCPK1234F", ifsc="hdfc0001234",
        account_number="50100012341234", reference_id="0192f6a0-7c1e-7d2a-8b3c-1234567890ab", address=ADDRESS)
    assert [(r.method, r.url.path) for r in rec.requests] == [
        ("POST", "/v2/accounts"), ("POST", "/v2/accounts/acc_new1/stakeholders"),
        ("POST", "/v2/accounts/acc_new1/products"), ("PATCH", "/v2/accounts/acc_new1/products/acc_prd_1/")]
    acc = rec.body(0)
    assert acc["type"] == "route" and acc["business_type"] == "individual" and acc["phone"] == "9000000001"
    assert "legal_info" not in acc  # an individual's PAN goes on the stakeholder
    assert 3 <= len(acc["reference_id"]) <= 20 and acc["reference_id"].isalnum()
    assert acc["profile"]["addresses"]["registered"] == {**ADDRESS, "country": "IN"}
    assert rec.body(1)["kyc"] == {"pan": "ABCPK1234F"}
    assert rec.body(2) == {"product_name": "route", "tnc_accepted": True}
    assert rec.body(3)["settlements"] == {"account_number": "50100012341234", "ifsc_code": "HDFC0001234",
                                          "beneficiary_name": "Riya Kulkarni"}
    assert out == {"id": "acc_new1", "entity": "account", "legal_business_name": "Riya Kulkarni",
                   "email": "riya@example.com", "status": "activated", "bank_tail": "1234", "product_id": "acc_prd_1",
                   "requirements": []}


@pytest.mark.parametrize("kwargs,code", [
    ({"ifsc": None, "account_number": None}, "bank_account_required"),
    ({"email": None}, "email_required"),
    ({"address": {"city": "Pune"}}, "address_required"),
])
def test_razorpay_linked_account_preconditions(kwargs, code):
    rec = Recorder((500, {}))
    args = {"email": "riya@example.com", "ifsc": "HDFC0001234", "account_number": "50100012341234", "address": ADDRESS,
            **kwargs}
    email = args.pop("email")
    with pytest.raises(ProviderError) as e:
        RazorpayLive(transport=rec.transport).create_linked_account("Riya", email, "1234", **args)
    assert e.value.code == code and not rec.requests


def test_razorpay_linked_account_partial_failure_names_the_account():
    rec = Recorder(_linked_account_responder(fail_stakeholder=True))
    with pytest.raises(ProviderError) as e:
        RazorpayLive(transport=rec.transport).create_linked_account(
            "Riya", "riya@example.com", "1234", pan="BADPAN", ifsc="HDFC0001234", account_number="50100012341234",
            address=ADDRESS)
    assert "acc_new1" in str(e.value) and e.value.code == "BAD_REQUEST_ERROR"


# ------------------------------------------------------------------ Cashfree
@pytest.fixture
def cf_settings(monkeypatch):
    s = replace(settings, cashfree_client_id="CF_TEST_ID", cashfree_client_secret="cf_test_secret")
    monkeypatch.setattr(kyc_live, "settings", s)
    return s


def test_cashfree_pan_maps_score_to_unit_range(cf_settings):
    rec = Recorder((200, {"pan": "ABCPK1234F", "type": "Individual", "reference_id": 4411, "valid": True,
                          "registered_name": "RIYA KULKARNI", "name_match_score": "92.00",
                          "name_match_result": "GOOD_PARTIAL_MATCH", "pan_status": "VALID"}))
    out = CashfreeKyc(transport=rec.transport).verify_pan("abcpk1234f", "Riya Kulkarni")
    req = rec.requests[0]
    assert (req.method, str(req.url)) == ("POST", "https://api.cashfree.com/verification/pan")
    assert req.headers["x-client-id"] == "CF_TEST_ID" and req.headers["x-client-secret"] == "cf_test_secret"
    assert "x-cf-signature" not in req.headers
    assert rec.body() == {"pan": "ABCPK1234F", "name": "Riya Kulkarni"}
    assert out == {"valid": True, "registered_name": "RIYA KULKARNI", "name_match": 0.92, "ref": "cf_pan_4411"}


def test_cashfree_pan_failures(cf_settings):
    assert CashfreeKyc(transport=Recorder((500, {})).transport).verify_pan("NOTAPAN", "x") == \
        {"valid": False, "reason": "invalid_pan_format"}  # rejected locally, no call
    low = Recorder((200, {"valid": True, "registered_name": "Someone Else", "name_match_score": 41, "reference_id": 1}))
    assert CashfreeKyc(transport=low.transport).verify_pan("ABCPK1234F", "Riya Kulkarni")["name_match"] == 0.41
    dead = Recorder((200, {"valid": False, "pan_status": "INVALID", "reference_id": 2}))
    assert CashfreeKyc(transport=dead.transport).verify_pan("ABCPK1234F", "Riya")["reason"] == "pan_invalid"
    bad = Recorder((400, {"type": "validation_error", "code": "pan_invalid", "message": "Invalid PAN"}))
    assert CashfreeKyc(transport=bad.transport).verify_pan("ABCPK1234F", "Riya")["valid"] is False
    # No score (name match not enabled): Flu's own comparison.
    noscore = Recorder((200, {"valid": True, "registered_name": "KULKARNI RIYA", "reference_id": 3}))
    assert CashfreeKyc(transport=noscore.transport).verify_pan("ABCPK1234F", "Riya Kulkarni")["name_match"] == 1.0


@pytest.mark.parametrize("status,body", [(401, {"type": "authentication_error", "code": "authentication_failed"}),
                                         (403, {"code": "ip_validation_failed"}),
                                         (422, {"code": "insufficient_balance"}), (429, {}), (500, {})])
def test_cashfree_outages_are_not_kyc_failures(cf_settings, status, body):
    with pytest.raises(ProviderUnavailable):
        CashfreeKyc(transport=Recorder((status, body)).transport).verify_pan("ABCPK1234F", "Riya")


def test_cashfree_bank_account(cf_settings):
    ok = Recorder((200, {"reference_id": 9001, "name_at_bank": "RIYA  KULKARNI", "account_status": "VALID",
                         "account_status_code": "ACCOUNT_IS_VALID", "name_match_score": "100.00", "utr": "1234"}))
    out = CashfreeKyc(transport=ok.transport).penny_drop("hdfc0001234", "50100012341234", None, "Riya Kulkarni")
    assert ok.requests[0].url.path == "/verification/bank-account/sync"
    assert ok.body() == {"bank_account": "50100012341234", "ifsc": "HDFC0001234", "name": "Riya Kulkarni"}
    assert out == {"valid": True, "registered_name": "RIYA  KULKARNI", "name_match": 1.0, "ref": "cf_bav_9001"}
    bad = Recorder((200, {"account_status": "INVALID", "account_status_code": "INVALID_IFSC_FAIL"}))
    assert CashfreeKyc(transport=bad.transport).penny_drop("HDFC0001234", "50100012341234", None, "Riya") == \
        {"valid": False, "reason": "invalid_ifsc"}
    assert CashfreeKyc(transport=bad.transport).penny_drop("HDFC0001234", "12", None, "Riya")["reason"] == \
        "invalid_account_number"


def test_cashfree_upi(cf_settings):
    rec = Recorder((200, {"reference_id": 77, "status": "VALID", "name_at_bank": "Riya Kulkarni", "vpa": "riya@okhdfc"}))
    out = CashfreeKyc(transport=rec.transport).penny_drop(None, None, "riya@okhdfc", "Riya Kulkarni")
    assert rec.requests[0].url.path == "/verification/upi"
    assert rec.body()["vpa"] == "riya@okhdfc" and rec.body()["verification_id"].startswith("flu")
    assert out["valid"] and out["name_match"] == 1.0 and out["ref"] == "cf_upi_77"
    nope = Recorder((200, {"status": "INVALID"}))
    assert CashfreeKyc(transport=nope.transport).penny_drop(None, None, "riya@okhdfc", "Riya")["reason"] == "invalid_vpa"


def test_cashfree_signature_header(cf_settings, monkeypatch):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    monkeypatch.setattr(kyc_live, "settings", replace(cf_settings, cashfree_public_key=pem))
    rec = Recorder((200, {"valid": True, "registered_name": "Riya", "name_match_score": 100, "reference_id": 1}))
    CashfreeKyc(transport=rec.transport).verify_pan("ABCPK1234F", "Riya")
    plain = key.decrypt(base64.b64decode(rec.requests[0].headers["x-cf-signature"]),
                        padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None)).decode()
    client_id, ts = plain.split(".")
    assert client_id == "CF_TEST_ID" and ts.isdigit()


# ------------------------------------------------------------------ MSG91
@pytest.fixture
def msg91(monkeypatch):
    def use(verify="flu"):
        monkeypatch.setattr(otp_live, "settings", replace(settings, msg91_auth_key="msg91key", msg91_template_id="tmpl_1",
                                                          msg91_dlt_te_id="1107160000000000001", msg91_sender_id="FLUAPP",
                                                          msg91_otp_verify=verify))
    return use


def test_msg91_send_with_flu_code(msg91):
    msg91("flu")
    rec = Recorder((200, {"type": "success", "request_id": "r1"}))
    code = Msg91Otp(transport=rec.transport).send("+919876543210")
    req, q = rec.requests[0], rec.query()
    assert (req.method, req.url.path) == ("POST", "/api/v5/otp") and req.headers["authkey"] == "msg91key"
    assert q["template_id"] == "tmpl_1" and q["mobile"] == "919876543210" and q["otp_expiry"] == "5"
    assert len(code) == 6 and code.isdigit() and q["otp"] == code


def test_msg91_generates_and_verifies(msg91):
    msg91("msg91")
    rec = Recorder((200, {"type": "success", "request_id": "r1"}), (200, {"type": "success", "message": "OTP verified success"}),
                   (200, {"type": "error", "message": "OTP not match"}))
    otp = Msg91Otp(transport=rec.transport)
    assert otp.send("+919876543210") is None and "otp" not in rec.query(0)
    assert otp.verify("+919876543210", "4821") is True
    assert (rec.requests[1].url.path, rec.query(1)) == ("/api/v5/otp/verify", {"otp": "4821", "mobile": "919876543210"})
    assert otp.verify("+919876543210", "0000") is False


def test_msg91_errors(msg91):
    msg91("flu")
    with pytest.raises(ProviderUnavailable):  # MSG91 reports config errors as HTTP 200 + type=error
        Msg91Otp(transport=Recorder((200, {"type": "error", "message": "The provided template ID is invalid."})).transport) \
            .send("+919876543210")
    with pytest.raises(ProviderUnavailable):
        Msg91Otp(transport=Recorder((401, {"type": "error", "message": "Invalid authkey", "code": "201"})).transport) \
            .verify("+919876543210", "1234")


def test_msg91_dlt_template_registration(msg91):
    msg91("flu")
    rec = Recorder((200, {"type": "success", "message": "Template updated"}))
    Msg91Otp(transport=rec.transport).register_dlt_template("##OTP## is your Flu login code. -Flu")
    assert rec.requests[0].url.path == "/api/v5/otp/updateOtpTemplate"
    assert rec.body() == {"templateId": "tmpl_1", "template": "##OTP## is your Flu login code. -Flu",
                          "dltTemplateId": "1107160000000000001", "senderId": "FLUAPP"}
    with pytest.raises(ProviderError):
        Msg91Otp(transport=rec.transport).register_dlt_template("your code")


# ------------------------------------------------------------------ services through the live adapters
def test_otp_login_through_msg91_verification(db, msg91, monkeypatch):
    from app.services import identity
    msg91("msg91")
    rec = Recorder((200, {"type": "success", "request_id": "r1"}), (200, {"type": "error", "message": "OTP not match"}),
                   (200, {"type": "success", "message": "OTP verified success"}))
    monkeypatch.setattr(providers, "otp", lambda: Msg91Otp(transport=rec.transport))
    monkeypatch.setattr(identity, "settings", replace(settings, provider_mode="live"))
    out = identity.send_otp(db, "9000000002")
    assert out["sent"] and "dev_otp" not in out
    from app.errors import ApiError
    with pytest.raises(ApiError) as e:
        identity.verify_otp(db, "9000000002", "111111", None)
    assert e.value.code == "otp_invalid"
    assert identity.verify_otp(db, "9000000002", "482193", None)["access_token"]


def test_otp_send_outage_is_a_502(db, msg91, monkeypatch):
    from app.errors import ApiError
    from app.services import identity
    msg91("flu")
    monkeypatch.setattr(providers, "otp", lambda: Msg91Otp(transport=Recorder((503, {})).transport))
    with pytest.raises(ApiError) as e:
        identity.send_otp(db, "9000000002")
    assert (e.value.status, e.value.code) == (502, "otp_unavailable")


def _new_creator(db, phone: str):
    from app.models import CreatorProfile, User
    u = db.query(User).filter_by(phone=phone).first()
    if not u:
        u = User(phone=phone, role="creator")
        db.add(u)
        db.flush()
        db.add(CreatorProfile(user_id=u.id, display_name="Kavya Menon"))
        db.commit()
    from app.models import CreatorProfile as CP
    return db.get(CP, u.id)


def _cashfree_ok(req):
    p = req.url.path
    if p.endswith("/pan"):
        return httpx.Response(200, json={"valid": True, "registered_name": "KAVYA MENON", "name_match_score": "100.00",
                                         "pan_status": "VALID", "reference_id": 1})
    return httpx.Response(200, json={"account_status": "VALID", "name_at_bank": "KAVYA MENON",
                                     "name_match_score": "55.00" if "mismatch" in req.content.decode() else "96.00",
                                     "reference_id": 2})


def test_kyc_submit_with_live_adapters(db, monkeypatch, cf_settings):
    from app.errors import ApiError
    from app.models import KycRecord, OpsItem, User
    from app.services import kyc
    cp = _new_creator(db, "+919777700001")
    accounts = Recorder(_linked_account_responder())
    monkeypatch.setattr(providers, "kyc", lambda: CashfreeKyc(transport=httpx.MockTransport(_cashfree_ok)))
    monkeypatch.setattr(providers, "razorpay", lambda db: RazorpayLive(transport=accounts.transport))

    with pytest.raises(ApiError) as e:  # Route needs an address; nothing reaches Razorpay
        kyc.submit(db, cp, "ABCPM1234K", "Kavya Menon", "HDFC0001234", "50100099990001", None, None, "kavya@example.com")
    assert e.value.code == "address_required" and not accounts.requests
    assert db.query(OpsItem).filter_by(type="kyc_fail", entity_id=cp.user_id).first().details["provider_message"]

    with pytest.raises(ApiError) as e:  # bank name too far from the PAN name
        kyc.submit(db, cp, "ABCPM1234K", "Kavya Menon mismatch", "HDFC0001234", "50100099990001", None, None,
                   "kavya@example.com", ADDRESS)
    assert e.value.code == "bank_name_mismatch"

    rec = kyc.submit(db, cp, "ABCPM1234K", "Kavya Menon", "HDFC0001234", "50100099990001", None, None,
                     "kavya@example.com", ADDRESS)
    assert rec.status == "verified" and rec.linked_account_id == "acc_new1" and rec.name_match == 1.0
    assert db.get(User, cp.user_id).email == "kavya@example.com"
    assert db.get(KycRecord, cp.user_id).pan_last4 == "234K"


def test_kyc_provider_outage_leaves_kyc_retryable(db, monkeypatch, cf_settings):
    from app.errors import ApiError
    from app.models import KycRecord
    from app.services import kyc
    cp = _new_creator(db, "+919777700002")
    monkeypatch.setattr(providers, "kyc", lambda: CashfreeKyc(transport=Recorder((503, {})).transport))
    with pytest.raises(ApiError) as e:
        kyc.submit(db, cp, "ABCPM1234K", "Kavya Menon", "HDFC0001234", "50100099990001", None, None)
    assert (e.value.status, e.value.code) == (502, "kyc_provider_unavailable")
    db.rollback()
    rec = db.get(KycRecord, cp.user_id)
    assert rec is None or rec.status != "failed"
