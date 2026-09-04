"""Modeles de donnees representant un projet SoapUI charge en memoire."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Assertion:
    type: str
    name: str = ""
    config: dict = field(default_factory=dict)


@dataclass
class TestStep:
    name: str
    step_type: str  # "restrequest", "request" (SOAP), ou "unsupported:<type>"
    method: str = "GET"
    endpoint: str = ""
    request_body: str = ""
    media_type: str = ""
    soap_action: Optional[str] = None
    headers: dict = field(default_factory=dict)
    query_params: dict = field(default_factory=dict)
    assertions: list = field(default_factory=list)
    disabled: bool = False

    @property
    def is_executable(self) -> bool:
        return self.step_type in ("restrequest", "request") and not self.disabled


@dataclass
class TestCase:
    name: str
    test_steps: list = field(default_factory=list)
    disabled: bool = False


@dataclass
class TestSuite:
    name: str
    test_cases: list = field(default_factory=list)


@dataclass
class Project:
    name: str
    test_suites: list = field(default_factory=list)
    properties: dict = field(default_factory=dict)
    source_path: str = ""
