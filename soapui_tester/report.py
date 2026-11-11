# SPDX-License-Identifier: GPL-3.0-or-later
"""Generation du rapport HTML (et resume texte) a partir d'un RunResult."""
import html

_STATUS_COLORS = {
    "PASS": "#1b8a4c",
    "FAIL": "#c0392b",
    "ERROR": "#a33ba0",
    "SKIPPED": "#8a8f98",
}

_CSS = """
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 24px;
       background: #f5f6f8; color: #1b1f24; }
h1 { margin: 0 0 4px 0; font-size: 22px; }
.subtitle { color: #555; margin-bottom: 20px; font-size: 13px; }
.summary { display: flex; gap: 12px; margin-bottom: 24px; flex-wrap: wrap; }
.badge { padding: 10px 16px; border-radius: 8px; color: white; font-weight: 600; font-size: 13px; min-width: 90px; text-align: center; }
details { background: white; border: 1px solid #d8dbe0; border-radius: 8px; margin-bottom: 8px; padding: 6px 12px; }
details details { margin-left: 12px; margin-top: 8px; }
summary { cursor: pointer; padding: 8px 4px; font-weight: 600; list-style: none; display: flex; align-items: center; gap: 10px; }
summary::-webkit-details-marker { display: none; }
.status-pill { display: inline-block; padding: 2px 10px; border-radius: 12px; color: white; font-size: 11px; font-weight: 700; }
.meta { color: #666; font-weight: 400; font-size: 12px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 16px 0; font-size: 12px; }
th, td { border: 1px solid #e0e2e6; padding: 6px 8px; text-align: left; vertical-align: top; }
th { background: #eef0f3; }
pre { background: #f0f1f3; border-radius: 6px; padding: 10px; overflow-x: auto; white-space: pre-wrap; word-break: break-word; font-size: 12px; margin: 4px 0 12px 0; }
.section-title { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: #666; margin: 10px 0 4px 0; }
.diff-fail td.actual { background: #fdecea; }
.diff-fail td.expected { background: #eafaf0; }
"""


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _pill(status: str) -> str:
    color = _STATUS_COLORS.get(status, "#666")
    return f'<span class="status-pill" style="background:{color}">{_esc(status)}</span>'


def _headers_table(headers: dict) -> str:
    if not headers:
        return "<p class='meta'>(aucun)</p>"
    rows = "".join(f"<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>" for k, v in headers.items())
    return f"<table><tr><th>En-tete</th><th>Valeur</th></tr>{rows}</table>"


def _assertions_table(assertion_results) -> str:
    if not assertion_results:
        return "<p class='meta'>Aucune assertion definie pour ce step.</p>"
    rows = []
    for ar in assertion_results:
        row_class = "diff-fail" if ar.status == "FAIL" else ""
        rows.append(
            f"<tr class='{row_class}'>"
            f"<td>{_esc(ar.name)}</td>"
            f"<td>{_esc(ar.type)}</td>"
            f"<td>{_pill(ar.status)}</td>"
            f"<td class='expected'><pre>{_esc(ar.expected)}</pre></td>"
            f"<td class='actual'><pre>{_esc(ar.actual)}</pre></td>"
            f"<td>{_esc(ar.message)}</td>"
            f"</tr>"
        )
    return (
        "<table><tr><th>Assertion</th><th>Type</th><th>Statut</th>"
        "<th>Attendu</th><th>Recu</th><th>Message</th></tr>" + "".join(rows) + "</table>"
    )


def _step_block(step) -> str:
    open_attr = " open" if step.status in ("FAIL", "ERROR") else ""
    parts = [f"<details{open_attr}><summary>{_pill(step.status)} {_esc(step.name)} "
             f"<span class='meta'>{_esc(step.method)} {_esc(step.url)} — {step.elapsed_ms:.0f} ms</span></summary>"]

    if step.error_message:
        parts.append(f"<p class='meta'>⚠ {_esc(step.error_message)}</p>")

    parts.append("<div class='section-title'>Requete</div>")
    parts.append(_headers_table(step.request_headers))
    if step.request_body:
        parts.append(f"<pre>{_esc(step.request_body)}</pre>")

    if step.response_status is not None:
        parts.append(f"<div class='section-title'>Reponse — HTTP {step.response_status}</div>")
        parts.append(_headers_table(step.response_headers))
        parts.append(f"<pre>{_esc(step.response_body)}</pre>")

    parts.append("<div class='section-title'>Assertions</div>")
    parts.append(_assertions_table(step.assertion_results))
    parts.append("</details>")
    return "".join(parts)


def _case_block(case) -> str:
    open_attr = " open" if case.status in ("FAIL", "ERROR") else ""
    steps_html = "".join(_step_block(s) for s in case.step_results)
    return (
        f"<details{open_attr}><summary>{_pill(case.status)} {_esc(case.name)} "
        f"<span class='meta'>{len(case.step_results)} step(s)</span></summary>{steps_html}</details>"
    )


def _suite_block(suite) -> str:
    statuses = [c.status for c in suite.case_results]
    suite_status = "PASS"
    if "ERROR" in statuses:
        suite_status = "ERROR"
    elif "FAIL" in statuses:
        suite_status = "FAIL"
    elif statuses and all(s == "SKIPPED" for s in statuses):
        suite_status = "SKIPPED"
    cases_html = "".join(_case_block(c) for c in suite.case_results)
    return (
        f"<details open><summary>{_pill(suite_status)} {_esc(suite.name)} "
        f"<span class='meta'>{len(suite.case_results)} test case(s)</span></summary>{cases_html}</details>"
    )


def generate_html_report(run_result) -> str:
    totals = run_result.totals
    summary_badges = "".join(
        f'<div class="badge" style="background:{_STATUS_COLORS.get(k.upper(), "#555") if k != "total" else "#33383f"}">'
        f'{v}<br><span style="font-weight:400;font-size:11px">{k.upper()}</span></div>'
        for k, v in totals.items()
    )
    suites_html = "".join(_suite_block(s) for s in run_result.suite_results)

    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Rapport de tests — {_esc(run_result.project_name)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>Rapport de tests API — {_esc(run_result.project_name)}</h1>
<div class="subtitle">Execute le {_esc(run_result.started_at)} — duree {run_result.duration_s:.2f} s</div>
<div class="summary">{summary_badges}</div>
{suites_html}
</body>
</html>"""


def save_html_report(run_result, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(generate_html_report(run_result))


def generate_text_summary(run_result) -> str:
    totals = run_result.totals
    lines = [
        f"Projet : {run_result.project_name}",
        f"Duree  : {run_result.duration_s:.2f} s",
        f"Total={totals['total']} PASS={totals['passed']} FAIL={totals['failed']} "
        f"ERROR={totals['errors']} SKIPPED={totals['skipped']}",
        "",
    ]
    for suite in run_result.suite_results:
        lines.append(f"TestSuite: {suite.name}")
        for case in suite.case_results:
            lines.append(f"  [{case.status}] TestCase: {case.name}")
            for step in case.step_results:
                lines.append(f"    [{step.status}] {step.name} ({step.method} {step.url}) — {step.elapsed_ms:.0f} ms")
                for ar in step.assertion_results:
                    if ar.status != "PASS":
                        lines.append(
                            f"        - {ar.name} [{ar.type}] => {ar.status} "
                            f"(attendu={ar.expected!r} recu={ar.actual!r} {ar.message})"
                        )
    return "\n".join(lines)
