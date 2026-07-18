from app.fingerprint import error_signature, fingerprint, normalize


def test_normalize_strips_variable_parts():
    a = normalize("ValidationError: order 8231 missing field 'amount'")
    b = normalize("ValidationError: order 9107 missing field 'amount'")
    assert a == b == "ValidationError: order # missing field 'amount'"


def test_normalize_uuids_and_hex():
    assert "<uuid>" in normalize("failed for 123e4567-e89b-12d3-a456-426614174000")
    assert "<hex>" in normalize("segfault at 0xDEADBEEF")


def test_signature_prefers_exception_header():
    sig = error_signature('{"error": "payload level"}', {"x-exception": "HeaderError: boom 42"})
    assert sig == "HeaderError: boom #"


def test_signature_falls_back_to_payload_error_field():
    sig = error_signature('{"error": "DB timeout after 30s"}', {})
    assert sig == "DB timeout after #s"


def test_same_cause_same_fingerprint_different_cause_different():
    h = {"x-exception": "GatewayTimeout: upstream 504 for txn 9001"}
    h2 = {"x-exception": "GatewayTimeout: upstream 504 for txn 1234"}
    h3 = {"x-exception": "ValidationError: missing amount"}
    fp1, _ = fingerprint("rejected", "payments", "{}", h)
    fp2, _ = fingerprint("rejected", "payments", "{}", h2)
    fp3, _ = fingerprint("rejected", "payments", "{}", h3)
    assert fp1 == fp2
    assert fp1 != fp3


def test_reason_and_origin_separate_groups():
    fp_rejected, _ = fingerprint("rejected", "orders", "{}", {})
    fp_expired, _ = fingerprint("expired", "orders", "{}", {})
    fp_other_queue, _ = fingerprint("rejected", "payments", "{}", {})
    assert len({fp_rejected, fp_expired, fp_other_queue}) == 3
