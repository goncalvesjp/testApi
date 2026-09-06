"""Tests du serializer : ecriture des modifications d'un Project vers son
fichier soapui-project.xml source."""
import shutil

from soapui_tester import serializer
from soapui_tester.models import Assertion
from soapui_tester.parser import parse_project

SAMPLE = "sample/sample-soapui-project.xml"

SOAP_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<con:soapui-project name="Sample SOAP Project" xmlns:con="http://eviware.com/soapui/config">
  <con:properties/>
  <con:testSuite name="Suite">
    <con:testCase name="Case">
      <con:testStep type="request" name="Appel SOAP">
        <con:config xsi:type="con:RequestStep" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
          <con:request name="Appel SOAP" soapAction="urn:action">
            <con:settings/>
            <con:endpoint>https://example.org/soap</con:endpoint>
            <con:request>&lt;env:Envelope/&gt;</con:request>
            <con:assertion type="Valid HTTP Status Codes" id="a1">
              <con:configuration>
                <codes>200</codes>
              </con:configuration>
            </con:assertion>
          </con:request>
        </con:config>
      </con:testStep>
    </con:testCase>
  </con:testSuite>
</con:soapui-project>
"""


def _copy_sample(tmp_path):
    dest = tmp_path / "project.xml"
    shutil.copy(SAMPLE, dest)
    return str(dest)


def test_save_project_persists_rest_step_edits(tmp_path):
    path = _copy_sample(tmp_path)
    project = parse_project(path)
    step = project.test_suites[0].test_cases[0].test_steps[0]

    step.name = "GET status 200 (renomme)"
    step.method = "POST"
    step.endpoint = "https://httpbin.org/status/201"
    step.request_body = '{"a": 1}'
    step.headers = {"X-Test": "1"}
    step.disabled = True
    step.assertions = [Assertion(type="Response SLA", name="SLA rapide", config={"SLA": "1000"})]

    serializer.save_project(project)

    reparsed = parse_project(path)
    edited = reparsed.test_suites[0].test_cases[0].test_steps[0]
    assert edited.name == "GET status 200 (renomme)"
    assert edited.method == "POST"
    assert edited.endpoint == "https://httpbin.org/status/201"
    assert edited.request_body == '{"a": 1}'
    assert edited.headers == {"X-Test": "1"}
    assert edited.disabled is True
    assert len(edited.assertions) == 1
    assert edited.assertions[0].type == "Response SLA"
    assert edited.assertions[0].config["SLA"] == "1000"


def test_save_project_preserves_untouched_steps(tmp_path):
    path = _copy_sample(tmp_path)
    project = parse_project(path)
    project.test_suites[0].test_cases[0].test_steps[0].name = "Renomme"

    serializer.save_project(project)

    reparsed = parse_project(path)
    case = reparsed.test_suites[0].test_cases[0]
    assert len(case.test_steps) == 3

    untouched = case.test_steps[1]
    assert untouched.name == "POST json echo"
    assertion_types = [a.type for a in untouched.assertions]
    assert assertion_types == [
        "Valid HTTP Status Codes",
        "Simple Contains",
        "JsonPath Match",
        "Simple Contains",
    ]

    third = case.test_steps[2]
    assert third.name == "GET status 500 attendu (echouera)"
    assert third.disabled is False


def test_duplicate_test_step_gets_unique_name_and_is_independent(tmp_path):
    path = _copy_sample(tmp_path)
    project = parse_project(path)
    case = project.test_suites[0].test_cases[0]
    original = case.test_steps[0]

    duplicate = serializer.duplicate_test_step(project._xml_namespace, case, original)

    assert duplicate is not original
    assert duplicate.name == "GET status 200 (copie)"
    assert len(case.test_steps) == 4
    assert case.test_steps[-1] is duplicate

    # Modifier la copie ne doit pas affecter l'original (pas de partage d'etat).
    duplicate.method = "DELETE"
    duplicate.assertions[0].config["codes"] = "500"
    assert original.method == "GET"
    assert original.assertions[0].config["codes"] == "200"

    serializer.save_project(project)
    reparsed = parse_project(path)
    reparsed_case = reparsed.test_suites[0].test_cases[0]
    assert [s.name for s in reparsed_case.test_steps] == [
        "GET status 200",
        "POST json echo",
        "GET status 500 attendu (echouera)",
        "GET status 200 (copie)",
    ]
    dup_reparsed = reparsed_case.test_steps[-1]
    assert dup_reparsed.method == "DELETE"
    assert dup_reparsed.assertions[0].config["codes"] == "500"
    # L'original n'a pas ete touche par la sauvegarde de sa copie.
    assert reparsed_case.test_steps[0].method == "GET"


def test_duplicate_test_step_name_deduplicates_across_multiple_copies(tmp_path):
    path = _copy_sample(tmp_path)
    project = parse_project(path)
    case = project.test_suites[0].test_cases[0]
    original = case.test_steps[0]

    first = serializer.duplicate_test_step(project._xml_namespace, case, original)
    second = serializer.duplicate_test_step(project._xml_namespace, case, original)

    assert first.name == "GET status 200 (copie)"
    assert second.name == "GET status 200 (copie 2)"


def test_duplicate_test_case_clones_all_steps_independently(tmp_path):
    path = _copy_sample(tmp_path)
    project = parse_project(path)
    suite = project.test_suites[0]
    case = suite.test_cases[0]

    duplicate = serializer.duplicate_test_case(project._xml_namespace, suite, case)

    assert duplicate is not case
    assert duplicate.name == "Get and Post (copie)"
    assert len(suite.test_cases) == 2
    assert len(duplicate.test_steps) == len(case.test_steps) == 3
    assert [s.name for s in duplicate.test_steps] == [s.name for s in case.test_steps]

    duplicate.test_steps[0].endpoint = "https://example.org/changed"
    assert case.test_steps[0].endpoint != "https://example.org/changed"

    serializer.save_project(project)
    reparsed = parse_project(path)
    assert [c.name for c in reparsed.test_suites[0].test_cases] == ["Get and Post", "Get and Post (copie)"]
    assert reparsed.test_suites[0].test_cases[1].test_steps[0].endpoint == "https://example.org/changed"
    assert reparsed.test_suites[0].test_cases[0].test_steps[0].endpoint == "${BaseUrl}/status/200"


def test_save_project_persists_soap_step_edits(tmp_path):
    path = tmp_path / "soap_project.xml"
    path.write_text(SOAP_SAMPLE, encoding="utf-8")

    project = parse_project(str(path))
    step = project.test_suites[0].test_cases[0].test_steps[0]
    assert step.step_type == "request"
    assert step.endpoint == "https://example.org/soap"
    assert step.soap_action == "urn:action"

    step.endpoint = "https://example.org/soap/v2"
    step.soap_action = "urn:action:v2"
    step.request_body = "<env:Envelope>v2</env:Envelope>"

    serializer.save_project(project)

    reparsed = parse_project(str(path))
    edited = reparsed.test_suites[0].test_cases[0].test_steps[0]
    assert edited.endpoint == "https://example.org/soap/v2"
    assert edited.soap_action == "urn:action:v2"
    assert edited.request_body == "<env:Envelope>v2</env:Envelope>"
