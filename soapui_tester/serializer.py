"""Ecriture des modifications d'un Project (models.py) vers son fichier
soapui-project.xml source.

Contrairement a parser.py (lecture seule), ce module ne regenere pas le XML
depuis zero : il modifie en place l'arbre ElementTree conserve par
parse_project() sur chaque TestStep (via les attributs prives
`_xml_step_elem` / `_xml_container_elem` / `_xml_config_elem` poses par le
parseur, et `_xml_elem` sur TestCase/TestSuite), afin de preserver tout ce que
le parseur ne modelise pas (interfaces, steps non supportes, reglages
projet...).

`duplicate_test_step()` / `duplicate_test_case()` suivent le meme principe :
plutot que de regenerer un `<testStep>`/`<testCase>` XML de toutes pieces, ils
clonent (deepcopy) l'element source puis le resynchronisent via
`sync_test_step()`, ce qui preserve les eventuels details XML non modelises
par TestStep/TestCase.

Limite connue : pour un test step REST, l'URL editee dans l'IHM (qui fusionne
`<con:endpoint>` et l'attribut `resourcePath` du `<con:config>`) est
entierement ecrite dans `<con:endpoint>` et `resourcePath` est vide a la
sauvegarde. Le comportement a l'execution est identique, mais la structure du
XML differe legerement de l'original.
"""
import copy
import xml.etree.ElementTree as ET

from .models import Assertion, TestCase, TestStep
from .parser import _find, _findall

_SOAPUI_NAMESPACE = "http://eviware.com/soapui/config"


def _ns_tag(namespace: str, name: str) -> str:
    return f"{namespace}{name}" if namespace else name


def _get_or_create(parent, namespace: str, name: str):
    elem = _find(parent, name)
    if elem is None:
        elem = ET.SubElement(parent, _ns_tag(namespace, name))
    return elem


def _sync_headers(container, namespace: str, headers: dict) -> None:
    settings_elem = _get_or_create(container, namespace, "settings")
    setting = next(
        (s for s in _findall(settings_elem, "setting") if "request-headers" in s.get("id", "")),
        None,
    )
    if not headers:
        if setting is not None:
            settings_elem.remove(setting)
        return
    if setting is None:
        setting = ET.SubElement(settings_elem, _ns_tag(namespace, "setting"))
        setting.set("id", "request-headers")
    fragment = ET.Element("xml-fragment")
    for key, value in headers.items():
        entry = ET.SubElement(fragment, "entry")
        entry.set("key", key)
        entry.set("value", value)
    setting.text = ET.tostring(fragment, encoding="unicode")


def _sync_assertions(container, namespace: str, assertions: list) -> None:
    for elem in _findall(container, "assertion"):
        container.remove(elem)
    for index, assertion in enumerate(assertions, start=1):
        a_elem = ET.SubElement(container, _ns_tag(namespace, "assertion"))
        a_elem.set("type", assertion.type)
        a_elem.set("name", assertion.name or assertion.type)
        a_elem.set("id", f"a{index}")
        if not assertion.config:
            continue
        conf_elem = ET.SubElement(a_elem, _ns_tag(namespace, "configuration"))
        for key, value in assertion.config.items():
            for item in value if isinstance(value, list) else [value]:
                child = ET.SubElement(conf_elem, key)
                child.text = item


def sync_test_step(step, namespace: str) -> None:
    """Reporte les champs actuels de `step` sur l'element XML source qui lui
    a ete associe au parsing. Ne fait rien si le step n'a pas ete parse
    depuis un fichier (pas d'element XML associe)."""
    step_elem = getattr(step, "_xml_step_elem", None)
    if step_elem is None:
        return

    step_elem.set("name", step.name)
    if step.disabled:
        step_elem.set("disabled", "true")
    else:
        step_elem.attrib.pop("disabled", None)

    container = getattr(step, "_xml_container_elem", None)
    if container is None:
        return

    if step.step_type == "restrequest":
        container.set("method", (step.method or "GET").upper())
        if step.media_type:
            container.set("mediaType", step.media_type)
        else:
            container.attrib.pop("mediaType", None)

        _get_or_create(container, namespace, "endpoint").text = step.endpoint
        config_elem = getattr(step, "_xml_config_elem", None)
        if config_elem is not None:
            # L'URL complete est desormais portee par <endpoint> ; voir la
            # limite documentee en tete de module.
            config_elem.set("resourcePath", "")

        params_elem = _get_or_create(container, namespace, "parameters")
        for elem in _findall(params_elem, "entry"):
            params_elem.remove(elem)
        for key, value in step.query_params.items():
            entry = ET.SubElement(params_elem, _ns_tag(namespace, "entry"))
            entry.set("key", key)
            entry.set("value", value)

    elif step.step_type == "request":
        _get_or_create(container, namespace, "endpoint").text = step.endpoint
        if step.soap_action:
            container.set("soapAction", step.soap_action)
        else:
            container.attrib.pop("soapAction", None)

    body_elem = _get_or_create(container, namespace, "request")
    body_elem.text = step.request_body or None

    _sync_headers(container, namespace, step.headers)
    _sync_assertions(container, namespace, step.assertions)


def save_project(project, path: str = None) -> str:
    """Reecrit le fichier soapui-project.xml source de `project` (ou `path`
    si fourni) avec les valeurs actuelles de tous ses test steps."""
    tree = getattr(project, "_xml_tree", None)
    if tree is None:
        raise ValueError(
            "Ce projet n'a pas ete charge depuis un fichier XML : rien a enregistrer."
        )
    namespace = getattr(project, "_xml_namespace", "")

    for suite in project.test_suites:
        for case in suite.test_cases:
            for step in case.test_steps:
                sync_test_step(step, namespace)

    if namespace:
        ET.register_namespace("con", namespace.strip("{}"))

    target = path or project.source_path
    tree.write(target, encoding="UTF-8", xml_declaration=True)
    project.source_path = target
    return target


def _unique_name(existing_names, base_name: str) -> str:
    candidate = f"{base_name} (copie)"
    if candidate not in existing_names:
        return candidate
    counter = 2
    while f"{base_name} (copie {counter})" in existing_names:
        counter += 1
    return f"{base_name} (copie {counter})"


def _clone_step_fields(step: TestStep) -> TestStep:
    return TestStep(
        name=step.name,
        step_type=step.step_type,
        method=step.method,
        endpoint=step.endpoint,
        request_body=step.request_body,
        media_type=step.media_type,
        soap_action=step.soap_action,
        headers=dict(step.headers),
        query_params=dict(step.query_params),
        assertions=[Assertion(type=a.type, name=a.name, config=dict(a.config)) for a in step.assertions],
        disabled=step.disabled,
    )


def _bind_step_container(step: TestStep, step_elem) -> None:
    step._xml_step_elem = step_elem
    config_elem = _find(step_elem, "config")
    if step.step_type == "restrequest":
        step._xml_container_elem = _find(config_elem, "restRequest") if config_elem is not None else None
        step._xml_config_elem = config_elem
    elif step.step_type == "request":
        step._xml_container_elem = _find(config_elem, "request") if config_elem is not None else None


def _append_before_properties(parent_elem, new_child) -> None:
    """Insere `new_child` juste avant le premier <properties> enfant de
    `parent_elem` s'il existe (pour respecter l'ordre attendu par le schema
    SoapUI), sinon l'ajoute simplement en dernier enfant."""
    properties_elems = _findall(parent_elem, "properties")
    if properties_elems:
        parent_elem.insert(list(parent_elem).index(properties_elems[0]), new_child)
    else:
        parent_elem.append(new_child)


def duplicate_test_step(namespace: str, case: TestCase, step: TestStep) -> TestStep:
    """Cree une copie independante de `step` (nom different, editable
    separement), ajoutee a la fin de `case.test_steps`. Si `step` est relie a
    un element XML source, un `<testStep>` clone est insere dans le meme
    `<testCase>` et immediatement synchronise avec les valeurs du clone."""
    new_step = _clone_step_fields(step)
    new_step.name = _unique_name([s.name for s in case.test_steps], step.name)

    source_elem = getattr(step, "_xml_step_elem", None)
    case_elem = getattr(case, "_xml_elem", None)
    if source_elem is not None and case_elem is not None:
        new_elem = copy.deepcopy(source_elem)
        new_elem.set("name", new_step.name)
        _append_before_properties(case_elem, new_elem)
        _bind_step_container(new_step, new_elem)
        sync_test_step(new_step, namespace)

    case.test_steps.append(new_step)
    return new_step


def duplicate_test_case(namespace: str, suite, case: TestCase) -> TestCase:
    """Cree une copie independante de `case` (nom different, avec des copies
    independantes de tous ses test steps), ajoutee a la fin de
    `suite.test_cases`."""
    new_case = TestCase(
        name=_unique_name([c.name for c in suite.test_cases], case.name),
        test_steps=[],
        disabled=case.disabled,
    )

    suite_elem = getattr(suite, "_xml_elem", None)
    case_elem = getattr(case, "_xml_elem", None)
    if suite_elem is not None and case_elem is not None:
        new_case_elem = copy.deepcopy(case_elem)
        new_case_elem.set("name", new_case.name)
        _append_before_properties(suite_elem, new_case_elem)
        new_case._xml_elem = new_case_elem

        for original_step, step_elem in zip(case.test_steps, _findall(new_case_elem, "testStep")):
            new_step = _clone_step_fields(original_step)
            _bind_step_container(new_step, step_elem)
            sync_test_step(new_step, namespace)
            new_case.test_steps.append(new_step)
    else:
        new_case.test_steps = [_clone_step_fields(s) for s in case.test_steps]

    suite.test_cases.append(new_case)
    return new_case
