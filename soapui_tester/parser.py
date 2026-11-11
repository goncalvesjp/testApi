# SPDX-License-Identifier: GPL-3.0-or-later
"""Parseur de fichiers de projet SoapUI (soapui-project.xml) vers les modeles internes.

Le parsing ignore volontairement les prefixes de namespace (con:, xsi:, ...) et
matche uniquement sur le nom local des balises, ce qui rend le parseur plus
tolerant aux variations de version de SoapUI.

Portee couverte : test steps REST ("restrequest") et SOAP ("request"), avec
leurs assertions courantes. Les steps Groovy Script, Property Transfer,
DataSource, JDBC Request, etc. sont detectes mais marques comme non supportes
(ils apparaissent dans le rapport avec un statut "SKIPPED").
"""
import re
import xml.etree.ElementTree as ET

from .models import Assertion, Project, TestCase, TestStep, TestSuite

_EXECUTABLE_TYPES = {"restrequest", "request", "httprequest"}
_CONTAINER_NAMES = {
    "restrequest": ("restRequest",),
    "request": ("request",),
    "httprequest": ("restRequest", "httpRequest", "request"),
}


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _find(elem, name):
    if elem is None:
        return None
    for child in elem:
        if _local(child.tag) == name:
            return child
    return None


def _find_any(elem, names):
    for name in names:
        found = _find(elem, name)
        if found is not None:
            return found
    return None


def _findall(elem, name):
    if elem is None:
        return []
    return [c for c in elem if _local(c.tag) == name]


def _text(elem, default=""):
    if elem is None or elem.text is None:
        return default
    return elem.text


def substitute_properties(text, properties: dict) -> str:
    if not text or "${" not in text:
        return text

    def repl(match):
        key = match.group(1)
        return properties.get(key, match.group(0))

    return re.sub(r"\$\{([^}#][^}]*)\}", repl, text)


def _parse_properties(elem) -> dict:
    props = {}
    props_elem = _find(elem, "properties")
    for prop in _findall(props_elem, "property"):
        name = _text(_find(prop, "name"))
        value = _text(_find(prop, "value"))
        if name:
            props[name] = value
    return props


def _parse_configuration(assertion_elem) -> dict:
    config = {}
    conf_elem = _find(assertion_elem, "configuration")
    if conf_elem is None:
        return config
    for child in conf_elem:
        key = _local(child.tag)
        value = child.text if child.text is not None else ""
        if key in config:
            if isinstance(config[key], list):
                config[key].append(value)
            else:
                config[key] = [config[key], value]
        else:
            config[key] = value
    return config


def _parse_assertions(container_elem) -> list:
    assertions = []
    for a in _findall(container_elem, "assertion"):
        assertions.append(
            Assertion(
                type=a.get("type", ""),
                name=a.get("name", a.get("type", "")),
                config=_parse_configuration(a),
            )
        )
    return assertions


def _parse_headers(container_elem) -> dict:
    """Best-effort : les en-tetes HTTP custom sont stockes comme un fragment
    XML serialise a l'interieur d'un <con:setting id="...request-headers">."""
    headers = {}
    settings_elem = _find(container_elem, "settings")
    for setting in _findall(settings_elem, "setting"):
        setting_id = setting.get("id", "")
        if "request-headers" not in setting_id:
            continue
        raw = setting.text
        if not raw or "entry" not in raw:
            continue
        try:
            fragment = ET.fromstring(raw)
        except ET.ParseError:
            continue
        for entry in fragment.iter():
            if _local(entry.tag) == "entry":
                key = entry.get("key")
                value = entry.get("value", "")
                if key:
                    headers[key] = value
    return headers


def _resolve_rest_method(interface_methods: dict, service: str, resource_path: str, method_name: str) -> str:
    norm_path = (resource_path or "").strip("/")
    key = (service, norm_path, method_name)
    if key in interface_methods:
        return interface_methods[key]
    # repli : chercher par nom de methode uniquement dans le meme service
    for (svc, _path, mname), http_method in interface_methods.items():
        if svc == service and mname == method_name:
            return http_method
    return None


def _index_rest_interfaces(root) -> tuple:
    """Retourne (interface_methods, interface_endpoints) pour resoudre les
    verbes HTTP et endpoints par defaut des requetes REST."""
    interface_methods = {}
    interface_endpoints = {}

    def walk_resource(resource_elem, parent_path, service):
        path = resource_elem.get("path", "")
        full_path = (parent_path.rstrip("/") + "/" + path.lstrip("/")).strip("/")
        for method in _findall(resource_elem, "method"):
            method_name = method.get("name", "")
            http_method = method.get("method", "GET")
            interface_methods[(service, full_path, method_name)] = http_method
        for sub in _findall(resource_elem, "resource"):
            walk_resource(sub, full_path, service)

    for interface in _findall(root, "interface"):
        service = interface.get("name", "")
        endpoints_elem = _find(interface, "endpoints")
        endpoints = [_text(e) for e in _findall(endpoints_elem, "endpoint") if _text(e)]
        if endpoints:
            interface_endpoints[service] = endpoints[0]
        base_path = interface.get("basePath", "")
        for resource in _findall(interface, "resource"):
            walk_resource(resource, base_path, service)

    return interface_methods, interface_endpoints


def _parse_rest_step(step_elem, config_elem, interface_methods, interface_endpoints) -> TestStep:
    container = _find(config_elem, "restRequest")
    service = config_elem.get("service", "")
    resource_path = config_elem.get("resourcePath", "")
    method_name = config_elem.get("methodName", "")

    method = None
    if container is not None:
        method = container.get("method")
    if not method:
        method = _resolve_rest_method(interface_methods, service, resource_path, method_name)
    if not method:
        method = "GET"

    endpoint = _text(_find(container, "endpoint")) if container is not None else ""
    if not endpoint:
        endpoint = interface_endpoints.get(service, "")

    body_elem = _find(container, "request") if container is not None else None
    body = body_elem.text if body_elem is not None and body_elem.text else ""

    media_type = container.get("mediaType", "") if container is not None else ""
    headers = _parse_headers(container) if container is not None else {}

    query_params = {}
    params_elem = _find(container, "parameters") if container is not None else None
    for entry in _findall(params_elem, "entry"):
        key = entry.get("key")
        if key:
            query_params[key] = entry.get("value", "")

    full_path = (resource_path or "").lstrip("/")
    url = endpoint.rstrip("/")
    if full_path:
        url = f"{url}/{full_path}"

    assertions = _parse_assertions(container) if container is not None else []

    step = TestStep(
        name=step_elem.get("name", ""),
        step_type="restrequest",
        method=method.upper(),
        endpoint=url,
        request_body=body,
        media_type=media_type,
        headers=headers,
        query_params=query_params,
        assertions=assertions,
        disabled=step_elem.get("disabled") == "true",
    )
    step._xml_container_elem = container
    step._xml_config_elem = config_elem
    return step


def _parse_soap_step(step_elem, config_elem) -> TestStep:
    container = _find(config_elem, "request")
    if container is None:
        return TestStep(name=step_elem.get("name", ""), step_type="unsupported:request", disabled=True)

    endpoint = _text(_find(container, "endpoint"))
    body_elem = _find(container, "request")
    body = body_elem.text if body_elem is not None and body_elem.text else ""
    soap_action = container.get("soapAction")
    headers = _parse_headers(container)
    assertions = _parse_assertions(container)

    step = TestStep(
        name=step_elem.get("name", ""),
        step_type="request",
        method="POST",
        endpoint=endpoint,
        request_body=body,
        media_type="text/xml; charset=UTF-8",
        soap_action=soap_action,
        headers=headers,
        assertions=assertions,
        disabled=step_elem.get("disabled") == "true",
    )
    step._xml_container_elem = container
    step._xml_config_elem = config_elem
    return step


def _parse_test_step(step_elem, interface_methods, interface_endpoints) -> TestStep:
    step_type = step_elem.get("type", "")
    config_elem = _find(step_elem, "config")

    if step_type == "restrequest":
        step = _parse_rest_step(step_elem, config_elem, interface_methods, interface_endpoints)
    elif step_type == "request":
        step = _parse_soap_step(step_elem, config_elem)
    elif step_type == "httprequest":
        # meme logique que REST, sans resolution d'interface
        step = _parse_rest_step(step_elem, config_elem, {}, {})
    else:
        step = TestStep(
            name=step_elem.get("name", ""),
            step_type=f"unsupported:{step_type}",
            disabled=True,
        )

    # Reference vers l'element XML source, utilisee par serializer.py pour
    # ecrire les modifications faites depuis l'IHM (nom / desactivation),
    # y compris pour les types de step non supportes.
    step._xml_step_elem = step_elem
    return step


def parse_project(path: str) -> Project:
    tree = ET.parse(path)
    root = tree.getroot()
    namespace = root.tag.split("}", 1)[0] + "}" if "}" in root.tag else ""

    project_name = root.get("name", "Projet SoapUI")
    properties = _parse_properties(root)
    interface_methods, interface_endpoints = _index_rest_interfaces(root)

    test_suites = []
    for ts_elem in _findall(root, "testSuite"):
        test_cases = []
        for tc_elem in _findall(ts_elem, "testCase"):
            steps = [
                _parse_test_step(step_elem, interface_methods, interface_endpoints)
                for step_elem in _findall(tc_elem, "testStep")
            ]
            case = TestCase(
                name=tc_elem.get("name", ""),
                test_steps=steps,
                disabled=tc_elem.get("disabled") == "true",
            )
            # Reference vers l'element XML source, utilisee par
            # serializer.duplicate_test_step() pour inserer un nouveau
            # <testStep> au bon endroit.
            case._xml_elem = tc_elem
            test_cases.append(case)
        suite = TestSuite(name=ts_elem.get("name", ""), test_cases=test_cases)
        # Idem, pour serializer.duplicate_test_case().
        suite._xml_elem = ts_elem
        test_suites.append(suite)

    project = Project(name=project_name, test_suites=test_suites, properties=properties, source_path=path)
    # Conserves pour permettre a serializer.save_project() de reecrire le
    # fichier source en ne modifiant que ce qui a change dans l'IHM.
    project._xml_tree = tree
    project._xml_namespace = namespace
    return project
