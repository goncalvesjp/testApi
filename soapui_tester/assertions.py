# SPDX-License-Identifier: GPL-3.0-or-later
"""Evaluateurs d'assertions SoapUI.

Chaque evaluateur recoit l'assertion parsee, la reponse HTTP (objet
`requests.Response`, ou None en cas d'echec de la requete) et le temps de
reponse en millisecondes, et retourne un `AssertionResult` avec le expected /
actual pour affichage dans le rapport (c'est le "diff" demande).
"""
import json
import re

from .results import AssertionResult

try:
    from lxml import etree as lxml_etree
except ImportError:  # pragma: no cover
    lxml_etree = None

try:
    from jsonpath_ng.ext import parse as jsonpath_parse
except ImportError:  # pragma: no cover
    jsonpath_parse = None


def _split_codes(raw):
    if isinstance(raw, list):
        raw = ",".join(raw)
    return [c.strip() for c in re.split(r"[,\s]+", raw or "") if c.strip()]


def _body(response) -> str:
    return response.text if response is not None else ""


def _truncate(text: str, limit: int = 800) -> str:
    if text is None:
        return ""
    return text if len(text) <= limit else text[:limit] + "... (tronque)"


def assert_valid_http_status_codes(assertion, response, elapsed_ms):
    codes = _split_codes(assertion.config.get("codes", ""))
    actual = str(response.status_code) if response is not None else "(pas de reponse)"
    status = "PASS" if actual in codes else "FAIL"
    return AssertionResult(
        name=assertion.name,
        type=assertion.type,
        status=status,
        expected=" ou ".join(codes) or "(aucun code configure)",
        actual=actual,
    )


def assert_simple_contains(assertion, response, elapsed_ms, negate=False):
    token = assertion.config.get("token", "")
    ignore_case = str(assertion.config.get("ignoreCase", "false")).lower() == "true"
    use_regex = str(assertion.config.get("useRegEx", "false")).lower() == "true"
    body = _body(response)

    if use_regex:
        flags = re.IGNORECASE if ignore_case else 0
        found = re.search(token, body, flags) is not None
    else:
        haystack = body.lower() if ignore_case else body
        needle = token.lower() if ignore_case else token
        found = needle in haystack

    ok = (not found) if negate else found
    status = "PASS" if ok else "FAIL"
    label = "ne contient PAS" if negate else "contient"
    return AssertionResult(
        name=assertion.name,
        type=assertion.type,
        status=status,
        expected=f"le corps {label} : {token!r}",
        actual=_truncate(body),
    )


def assert_simple_not_contains(assertion, response, elapsed_ms):
    return assert_simple_contains(assertion, response, elapsed_ms, negate=True)


def _strip_ns_declarations(path: str):
    ns_map = {}
    clean_lines = []
    for line in (path or "").splitlines():
        m = re.match(r"\s*declare namespace\s+(\w+)\s*=\s*'([^']*)'\s*;?", line.strip(), re.IGNORECASE)
        if m:
            ns_map[m.group(1)] = m.group(2)
        elif line.strip():
            clean_lines.append(line)
    return "\n".join(clean_lines).strip(), ns_map


def assert_xpath_match(assertion, response, elapsed_ms):
    raw_path = assertion.config.get("path", "")
    expected = assertion.config.get("content", "")
    body = _body(response)

    if lxml_etree is None:
        return AssertionResult(
            name=assertion.name, type=assertion.type, status="ERROR",
            expected=expected, actual="", message="lxml non installe : XPath indisponible",
        )

    expr, ns_map = _strip_ns_declarations(raw_path)
    try:
        doc = lxml_etree.fromstring(body.encode("utf-8"))
        result = doc.xpath(expr, namespaces=ns_map or None)
    except Exception as exc:
        return AssertionResult(
            name=assertion.name, type=assertion.type, status="ERROR",
            expected=expected, actual="", message=str(exc),
        )

    if isinstance(result, list):
        if not result:
            actual = ""
        else:
            first = result[0]
            if isinstance(first, str):
                actual = first
            else:
                actual = first.text if first.text is not None else lxml_etree.tostring(first, encoding="unicode")
    else:
        actual = str(result)

    status = "PASS" if (actual or "").strip() == (expected or "").strip() else "FAIL"
    return AssertionResult(
        name=assertion.name, type=assertion.type, status=status,
        expected=expected, actual=_truncate(actual or ""),
    )


def assert_jsonpath(assertion, response, elapsed_ms, existence_only=False):
    raw_path = assertion.config.get("path", "")
    expected = assertion.config.get("content", assertion.config.get("expectedContent", ""))
    body = _body(response)

    if jsonpath_parse is None:
        return AssertionResult(
            name=assertion.name, type=assertion.type, status="ERROR",
            expected=expected, actual="", message="jsonpath-ng non installe",
        )

    try:
        data = json.loads(body)
        matches = [m.value for m in jsonpath_parse(raw_path).find(data)]
    except Exception as exc:
        return AssertionResult(
            name=assertion.name, type=assertion.type, status="ERROR",
            expected=expected, actual="", message=str(exc),
        )

    if existence_only:
        status = "PASS" if matches else "FAIL"
        return AssertionResult(
            name=assertion.name, type=assertion.type, status=status,
            expected="le chemin existe", actual="trouve" if matches else "absent",
        )

    actual = str(matches[0]) if matches else "(chemin introuvable)"
    status = "PASS" if matches and actual == str(expected) else "FAIL"
    return AssertionResult(
        name=assertion.name, type=assertion.type, status=status,
        expected=str(expected), actual=_truncate(actual),
    )


def assert_response_sla(assertion, response, elapsed_ms):
    try:
        sla = float(assertion.config.get("SLA", "0"))
    except (TypeError, ValueError):
        sla = 0.0
    status = "PASS" if elapsed_ms <= sla else "FAIL"
    return AssertionResult(
        name=assertion.name, type=assertion.type, status=status,
        expected=f"<= {sla:.0f} ms", actual=f"{elapsed_ms:.0f} ms",
    )


def assert_soap_response(assertion, response, elapsed_ms, expect_fault=False):
    body = _body(response).lower()
    has_fault = "fault" in body and ("<soap" in body or "<env:fault" in body or "<fault" in body)
    ok = has_fault if expect_fault else not has_fault
    status = "PASS" if ok else "FAIL"
    expected = "SOAP Fault present" if expect_fault else "pas de SOAP Fault"
    actual = "SOAP Fault detecte" if has_fault else "pas de SOAP Fault"
    return AssertionResult(
        name=assertion.name, type=assertion.type, status=status,
        expected=expected, actual=actual,
    )


def assert_unsupported(assertion, response, elapsed_ms):
    return AssertionResult(
        name=assertion.name, type=assertion.type, status="SKIPPED",
        expected="", actual="", message="Type d'assertion non supporte par cet outil",
    )


_DISPATCH = {
    "Valid HTTP Status Codes": assert_valid_http_status_codes,
    "Simple Contains": assert_simple_contains,
    "Simple NotContains": assert_simple_not_contains,
    "XPath Match": assert_xpath_match,
    "JsonPath Match": lambda a, r, e: assert_jsonpath(a, r, e, existence_only=False),
    "JsonPath Existence Match": lambda a, r, e: assert_jsonpath(a, r, e, existence_only=True),
    "Response SLA": assert_response_sla,
    "SOAP Response": assert_soap_response,
    "SOAP Fault Assertion": lambda a, r, e: assert_soap_response(a, r, e, expect_fault=True),
    "Not SOAP Fault Assertion": assert_soap_response,
}


def evaluate_assertion(assertion, response, elapsed_ms):
    fn = _DISPATCH.get(assertion.type, assert_unsupported)
    try:
        return fn(assertion, response, elapsed_ms)
    except Exception as exc:  # une assertion ne doit jamais faire planter le run
        return AssertionResult(
            name=assertion.name, type=assertion.type, status="ERROR",
            expected="", actual="", message=str(exc),
        )
