"""Execution des tests d'un projet SoapUI parse et generation des resultats."""
import datetime
import time

import requests

from .assertions import evaluate_assertion
from .parser import substitute_properties
from .results import CaseResult, RunResult, StepResult, SuiteResult


def _apply_properties(step, properties: dict):
    endpoint = substitute_properties(step.endpoint, properties)
    body = substitute_properties(step.request_body, properties)
    headers = {k: substitute_properties(v, properties) for k, v in step.headers.items()}
    query_params = {k: substitute_properties(v, properties) for k, v in step.query_params.items()}
    return endpoint, body, headers, query_params


def _run_step(step, properties: dict, timeout: float, verify_ssl: bool) -> StepResult:
    endpoint, body, headers, query_params = _apply_properties(step, properties)

    if step.soap_action:
        headers.setdefault("SOAPAction", step.soap_action)
    if step.media_type and "Content-Type" not in headers:
        headers.setdefault("Content-Type", step.media_type)

    if not endpoint:
        return StepResult(
            name=step.name, step_type=step.step_type, status="ERROR",
            method=step.method, url=endpoint, request_headers=headers, request_body=body,
            error_message="Endpoint vide : impossible d'executer la requete",
        )

    result = StepResult(
        name=step.name, step_type=step.step_type, status="ERROR",
        method=step.method, url=endpoint, request_headers=headers, request_body=body,
    )

    start = time.perf_counter()
    try:
        response = requests.request(
            method=step.method,
            url=endpoint,
            headers=headers,
            params=query_params or None,
            data=body.encode("utf-8") if body else None,
            timeout=timeout,
            verify=verify_ssl,
        )
    except requests.RequestException as exc:
        result.error_message = str(exc)
        result.elapsed_ms = (time.perf_counter() - start) * 1000
        result.assertion_results = [
            evaluate_assertion(a, None, result.elapsed_ms) for a in step.assertions
        ]
        result.status = "ERROR"
        return result

    elapsed_ms = (time.perf_counter() - start) * 1000
    result.elapsed_ms = elapsed_ms
    result.response_status = response.status_code
    result.response_headers = dict(response.headers)
    result.response_body = response.text

    assertion_results = [evaluate_assertion(a, response, elapsed_ms) for a in step.assertions]
    result.assertion_results = assertion_results

    if any(ar.status == "ERROR" for ar in assertion_results):
        result.status = "ERROR"
    elif any(ar.status == "FAIL" for ar in assertion_results):
        result.status = "FAIL"
    else:
        result.status = "PASS"

    return result


def run_project(
    project,
    timeout: float = 30.0,
    verify_ssl: bool = True,
    on_step_start=None,
    on_step_done=None,
    cancel_event=None,
    extra_properties: dict = None,
) -> RunResult:
    properties = dict(project.properties)
    if extra_properties:
        properties.update(extra_properties)

    run_result = RunResult(
        project_name=project.name,
        started_at=datetime.datetime.now().isoformat(timespec="seconds"),
    )

    overall_start = time.perf_counter()

    for suite in project.test_suites:
        suite_result = SuiteResult(name=suite.name)
        for case in suite.test_cases:
            case_result = CaseResult(name=case.name, status="SKIPPED" if case.disabled else "PASS")
            if not case.disabled:
                for step in case.test_steps:
                    if cancel_event is not None and cancel_event.is_set():
                        break

                    if on_step_start:
                        on_step_start(suite.name, case.name, step.name)

                    if not step.is_executable:
                        step_result = StepResult(
                            name=step.name,
                            step_type=step.step_type,
                            status="SKIPPED",
                            error_message="Type de test step non supporte" if not step.disabled else "Step desactive",
                        )
                    else:
                        step_result = _run_step(step, properties, timeout, verify_ssl)

                    case_result.step_results.append(step_result)
                    if on_step_done:
                        on_step_done(suite.name, case.name, step.name, step_result)

            statuses = [s.status for s in case_result.step_results]
            if "ERROR" in statuses:
                case_result.status = "ERROR"
            elif "FAIL" in statuses:
                case_result.status = "FAIL"
            elif statuses and all(s == "SKIPPED" for s in statuses):
                case_result.status = "SKIPPED"
            elif not case.disabled:
                case_result.status = "PASS"

            suite_result.case_results.append(case_result)
        run_result.suite_results.append(suite_result)

    run_result.duration_s = time.perf_counter() - overall_start
    return run_result
