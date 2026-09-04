"""Tests du moteur d'execution, avec requests mocke (aucun appel reseau)."""
from unittest.mock import MagicMock, patch

from soapui_tester.parser import parse_project
from soapui_tester.runner import run_project

SAMPLE = "sample/sample-soapui-project.xml"


def _fake_request(method, url, **kwargs):
    response = MagicMock()
    response.status_code = 200
    response.headers = {"Content-Type": "application/json"}
    response.text = '{"json": {"message": "bonjour"}}' if "/post" in url else ""
    return response


def test_run_project_resolves_properties_and_evaluates_assertions():
    project = parse_project(SAMPLE)

    with patch("soapui_tester.runner.requests.request", side_effect=_fake_request) as mocked:
        result = run_project(project, timeout=5, verify_ssl=True)

    # les 3 steps ont ete appeles avec l'URL ou ${BaseUrl} est resolu
    called_urls = [call.kwargs["url"] for call in mocked.call_args_list]
    assert called_urls == [
        "https://httpbin.org/status/200",
        "https://httpbin.org/post",
        "https://httpbin.org/status/500",
    ]

    totals = result.totals
    assert totals["total"] == 3
    # le step "POST json echo" du projet d'exemple contient volontairement une
    # assertion "Simple Contains" qui ne peut pas matcher (utile pour
    # demontrer le rapport de diff) : il est donc attendu en FAIL ici.
    assert totals["passed"] == 2
    assert totals["failed"] == 1
    assert totals["errors"] == 0


def test_run_project_reports_step_failure_on_unexpected_status():
    project = parse_project(SAMPLE)

    def always_500(method, url, **kwargs):
        response = MagicMock()
        response.status_code = 500
        response.headers = {}
        response.text = ""
        return response

    with patch("soapui_tester.runner.requests.request", side_effect=always_500):
        result = run_project(project, timeout=5, verify_ssl=True)

    step = result.suite_results[0].case_results[0].step_results[0]
    assert step.status == "FAIL"
    assert step.assertion_results[0].expected == "200"
    assert step.assertion_results[0].actual == "500"
