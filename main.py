#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Point d'entree : lance l'IHM PyQt (sans argument) ou execute un projet
SoapUI en mode ligne de commande (avec un chemin de fichier)."""
import argparse
import sys

from soapui_tester import generate_text_summary, parse_project, run_project, save_html_report


def run_cli(args) -> int:
    project = parse_project(args.project_file)
    print(f"Projet charge : {project.name} "
          f"({sum(len(ts.test_cases) for ts in project.test_suites)} test case(s))")

    result = run_project(project, timeout=args.timeout, verify_ssl=not args.insecure)

    print()
    print(generate_text_summary(result))

    save_html_report(result, args.report)
    print(f"\nRapport HTML ecrit dans : {args.report}")

    totals = result.totals
    return 0 if (totals["failed"] == 0 and totals["errors"] == 0) else 1


def run_gui() -> int:
    from soapui_tester.gui import main as gui_main
    return gui_main()


def main():
    parser = argparse.ArgumentParser(description="Testeur de projets SoapUI (headless ou IHM PyQt)")
    parser.add_argument("project_file", nargs="?", help="Chemin vers un fichier soapui-project.xml")
    parser.add_argument("-o", "--report", default="report.html", help="Chemin du rapport HTML de sortie")
    parser.add_argument("--timeout", type=float, default=30.0, help="Timeout HTTP en secondes")
    parser.add_argument("--insecure", action="store_true", help="Ignorer les erreurs de certificat SSL")
    parser.add_argument("--gui", action="store_true", help="Forcer le lancement de l'IHM")
    args = parser.parse_args()

    if args.gui or not args.project_file:
        sys.exit(run_gui())
    else:
        sys.exit(run_cli(args))


if __name__ == "__main__":
    main()
