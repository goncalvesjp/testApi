# SPDX-License-Identifier: GPL-3.0-or-later
"""Modeles de resultats produits par l'execution d'un projet."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AssertionResult:
    name: str
    type: str
    status: str  # PASS, FAIL, ERROR, SKIPPED
    expected: str = ""
    actual: str = ""
    message: str = ""


@dataclass
class StepResult:
    name: str
    step_type: str
    status: str  # PASS, FAIL, ERROR, SKIPPED
    method: str = ""
    url: str = ""
    request_headers: dict = field(default_factory=dict)
    request_body: str = ""
    response_status: Optional[int] = None
    response_headers: dict = field(default_factory=dict)
    response_body: str = ""
    elapsed_ms: float = 0.0
    error_message: str = ""
    assertion_results: list = field(default_factory=list)


@dataclass
class CaseResult:
    name: str
    status: str
    step_results: list = field(default_factory=list)


@dataclass
class SuiteResult:
    name: str
    case_results: list = field(default_factory=list)


@dataclass
class RunResult:
    project_name: str
    suite_results: list = field(default_factory=list)
    started_at: str = ""
    duration_s: float = 0.0

    @property
    def totals(self) -> dict:
        total = passed = failed = errors = skipped = 0
        for suite in self.suite_results:
            for case in suite.case_results:
                for step in case.step_results:
                    total += 1
                    if step.status == "PASS":
                        passed += 1
                    elif step.status == "FAIL":
                        failed += 1
                    elif step.status == "ERROR":
                        errors += 1
                    else:
                        skipped += 1
        return {"total": total, "passed": passed, "failed": failed, "errors": errors, "skipped": skipped}
