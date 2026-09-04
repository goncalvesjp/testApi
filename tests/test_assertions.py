"""Tests des évaluateurs d'assertions, sans appel réseau (réponse HTTP simulée)."""
from soapui_tester.assertions import evaluate_assertion
from soapui_tester.models import Assertion


class FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


def test_valid_http_status_codes_pass():
    assertion = Assertion(type="Valid HTTP Status Codes", name="a", config={"codes": "200,201"})
    result = evaluate_assertion(assertion, FakeResponse(200), 10)
    assert result.status == "PASS"


def test_valid_http_status_codes_fail():
    assertion = Assertion(type="Valid HTTP Status Codes", name="a", config={"codes": "200"})
    result = evaluate_assertion(assertion, FakeResponse(500), 10)
    assert result.status == "FAIL"
    assert result.actual == "500"


def test_simple_contains_pass():
    assertion = Assertion(type="Simple Contains", name="a", config={"token": "bonjour"})
    result = evaluate_assertion(assertion, FakeResponse(200, "bonjour le monde"), 10)
    assert result.status == "PASS"


def test_simple_contains_ignore_case():
    assertion = Assertion(type="Simple Contains", name="a", config={"token": "BONJOUR", "ignoreCase": "true"})
    result = evaluate_assertion(assertion, FakeResponse(200, "bonjour le monde"), 10)
    assert result.status == "PASS"


def test_simple_not_contains_fails_when_token_present():
    assertion = Assertion(type="Simple NotContains", name="a", config={"token": "bonjour"})
    result = evaluate_assertion(assertion, FakeResponse(200, "bonjour"), 10)
    assert result.status == "FAIL"


def test_jsonpath_match_pass():
    assertion = Assertion(type="JsonPath Match", name="a", config={"path": "$.json.message", "content": "bonjour"})
    body = '{"json": {"message": "bonjour"}}'
    result = evaluate_assertion(assertion, FakeResponse(200, body), 10)
    assert result.status == "PASS"


def test_jsonpath_match_fail_on_mismatch():
    assertion = Assertion(type="JsonPath Match", name="a", config={"path": "$.json.message", "content": "salut"})
    body = '{"json": {"message": "bonjour"}}'
    result = evaluate_assertion(assertion, FakeResponse(200, body), 10)
    assert result.status == "FAIL"
    assert result.actual == "bonjour"


def test_response_sla_pass_and_fail():
    assertion = Assertion(type="Response SLA", name="a", config={"SLA": "1000"})
    assert evaluate_assertion(assertion, FakeResponse(200), 500).status == "PASS"
    assert evaluate_assertion(assertion, FakeResponse(200), 1500).status == "FAIL"


def test_unsupported_assertion_is_skipped():
    assertion = Assertion(type="Script Assertion", name="a", config={})
    result = evaluate_assertion(assertion, FakeResponse(200), 10)
    assert result.status == "SKIPPED"
