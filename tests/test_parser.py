"""Tests du parseur de projets SoapUI."""
from soapui_tester.parser import parse_project

SAMPLE = "sample/sample-soapui-project.xml"


def test_parse_sample_project_structure():
    project = parse_project(SAMPLE)
    assert project.name == "Sample HttpBin Project"
    assert project.properties.get("BaseUrl") == "https://httpbin.org"
    assert len(project.test_suites) == 1

    suite = project.test_suites[0]
    assert suite.name == "HttpBin TestSuite"
    assert len(suite.test_cases) == 1

    case = suite.test_cases[0]
    assert len(case.test_steps) == 3


def test_rest_step_method_and_endpoint_are_resolved():
    project = parse_project(SAMPLE)
    step = project.test_suites[0].test_cases[0].test_steps[0]
    assert step.step_type == "restrequest"
    assert step.method == "GET"
    # la propriete ${BaseUrl} n'est substituee qu'a l'execution, pas au parsing
    assert step.endpoint == "${BaseUrl}/status/200"
    assert step.is_executable


def test_assertions_are_parsed_with_configuration():
    project = parse_project(SAMPLE)
    post_step = project.test_suites[0].test_cases[0].test_steps[1]
    assert post_step.method == "POST"
    assertion_types = [a.type for a in post_step.assertions]
    assert "Valid HTTP Status Codes" in assertion_types
    assert "Simple Contains" in assertion_types
    assert "JsonPath Match" in assertion_types

    contains = next(a for a in post_step.assertions if a.type == "Simple Contains" and a.config.get("token") == "bonjour")
    assert contains.config["ignoreCase"] == "false"
