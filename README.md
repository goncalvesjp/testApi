# Testeur de projets SoapUI

Outil qui charge un fichier de projet SoapUI (`soapui-project.xml`), exécute
les requêtes REST/SOAP qu'il contient contre l'API réelle, évalue les
assertions définies (statut HTTP, contenu, XPath, JsonPath, SLA...) et produit
un rapport détaillé attendu vs reçu — en ligne de commande ou via une IHM
PyQt6.

## Prérequis

- Python 3
- `make` (les commandes ci-dessous passent toutes par le `Makefile`)

## Installation

```bash
make venv
```

Équivalent manuel :

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Utilisation

### IHM graphique

```bash
make run
```

1. **Ouvrir un projet SoapUI…** — sélectionner un fichier `.xml`
2. **Propriétés du projet…** (optionnel) — surcharger `${BaseUrl}` ou toute
   autre propriété du projet sans toucher au XML (utile pour basculer
   staging/prod). Chaque propriété propose une liste déroulante des valeurs
   déjà utilisées (historique persisté dans `~/.soapui_tester/settings.json`,
   indépendant du projet) : taper une nouvelle valeur puis cliquer le bouton
   **+** en bout de ligne l'ajoute à la liste immédiatement (sans attendre le
   OK du dialogue). Voir [sample/settings-example.json](sample/settings-example.json)
   pour un exemple pré-rempli avec 3 valeurs de `BaseUrl` (prod/staging/dev) à
   copier vers `~/.soapui_tester/settings.json` pour essayer tout de suite
3. **▶ Lancer les tests** — exécution dans un thread séparé, l'arbre se
   colore en direct (vert = PASS, rouge = FAIL, violet = ERROR, gris =
   SKIPPED)
4. Cliquer sur un test step affiche son détail dans le panneau de droite :
   onglets **Requête** / **Réponse** / **Assertions** (avec la colonne
   Attendu vs Reçu) / **Modifier**
5. **Modifier** — éditer le nom, l'état activé/désactivé, la méthode,
   l'endpoint, le corps, les en-têtes et les assertions (type, nom,
   configuration au format `clé: valeur` par ligne) d'un test step, puis
   cliquer **Appliquer les modifications à cette étape** pour les répercuter
   en mémoire (visible immédiatement dans l'arbre et lors du prochain
   lancement des tests)
6. **Clic droit sur un test step ou un test case** — **Dupliquer** : crée une
   copie indépendante (nom suffixé `(copie)`, `(copie 2)`...) ajoutée à la fin
   du test case (ou de la suite pour un test case), sélectionnée
   automatiquement pour être renommée/modifiée via l'onglet **Modifier**.
   L'original n'est jamais impacté.
7. **💾 Enregistrer le projet** — écrit toutes les modifications appliquées
   dans le fichier `soapui-project.xml` source (confirmation demandée avant
   d'écraser le fichier). Seuls les éléments touchés sont modifiés dans le
   XML ; tout le reste (interfaces, steps non supportés, réglages projet...)
   est préservé tel quel. Limite : pour un test step REST, l'URL affichée
   dans l'IHM fusionne l'endpoint et le `resourcePath` d'origine ; à
   l'enregistrement, l'URL complète est réécrite dans `<con:endpoint>` et
   `resourcePath` est vidé — le comportement à l'exécution est identique,
   seule la structure interne du XML diffère légèrement de l'original
   SoapUI
7. **Exporter le rapport HTML…** — sauvegarde le rapport consultable hors de
   l'appli

### Ligne de commande (scripts, CI)

```bash
.venv/bin/python main.py chemin/vers/projet.xml -o rapport.html
```

Options : `--timeout <secondes>` (défaut 30), `--insecure` (ignore les
erreurs de certificat SSL), `-o/--report` (chemin du rapport HTML, défaut
`report.html`). Code de sortie `0` si tout passe, `1` si au moins une
assertion échoue ou qu'une requête part en erreur.

### Exemples fournis

| Fichier | API testée | But |
|---|---|---|
| [sample/sample-soapui-project.xml](sample/sample-soapui-project.xml) | httpbin.org | démo avec 2 assertions en échec volontaire (pour voir le rendu du diff) |
| [sample/exemple-jsonplaceholder.xml](sample/exemple-jsonplaceholder.xml) | jsonplaceholder.typicode.com | template propre (tout passe), à copier comme point de départ |

```bash
.venv/bin/python main.py sample/exemple-jsonplaceholder.xml -o rapport.html
```

Pour adapter un exemple à ta propre API : changer la propriété `BaseUrl`
(une seule valeur pilote tous les endpoints), le `resourcePath` de chaque
`<con:config>`, et le corps/les assertions de chaque requête.

## Tests

```bash
make test
```

Lance la suite `pytest` (`tests/`) en mode Qt "offscreen" (aucune fenêtre
n'apparaît). Tous les tests sont hors-ligne (les appels HTTP sont simulés
via `unittest.mock`, aucune dépendance réseau).

## Packaging (exécutables autonomes)

### macOS

```bash
make macos
```

Produit `dist/macos/SoapUITester.app` via [PyInstaller](https://pyinstaller.org/).

### Linux

```bash
make linux
```

Produit `dist/linux/soapui-tester` (binaire ELF x86_64 autonome), construit
dans un conteneur Ubuntu via [`container`](https://github.com/apple/container)
(macOS 15+, Apple Silicon ; cible `amd64`/Rosetta car PyQt6 n'a pas de wheel
Linux arm64 sur PyPI). Le binaire dépend de quelques bibliothèques système
Qt/X11 généralement déjà présentes sur un bureau Linux (`libgl1`, `libegl1`,
`libglib2.0-0`, la pile `libxcb-*`, `libdbus-1-3`, `libfontconfig1`).

`make linux-native` construit directement sur une vraie machine/VM Linux
(sans conteneur). `make dist` enchaîne `macos` + `linux` puis archive les
résultats en `.zip`/`.tar.gz`.

### Nettoyer les artefacts de build

```bash
make clean
```

## Architecture

```
main.py                          Point d'entrée (CLI argparse + lancement IHM)
soapui_tester/
  parser.py                      soapui-project.xml -> modèles Python
  models.py                      Project / TestSuite / TestCase / TestStep / Assertion
  serializer.py                  Réécrit les modifications d'un Project dans son soapui-project.xml source
  runner.py                      Exécute les requêtes HTTP (requests) et les assertions
  assertions.py                  Un évaluateur par type d'assertion SoapUI
  results.py                     RunResult / SuiteResult / CaseResult / StepResult / AssertionResult
  report.py                      Génère le rapport HTML (et un résumé texte pour la CLI)
  gui.py                         IHM PyQt6 (QMainWindow + QThread pour l'exécution + édition des test steps)
sample/                          Fichiers de projet SoapUI d'exemple
tests/                           Suite pytest (+ pytest-qt pour l'IHM)
packaging/                       Specs PyInstaller (macOS, Linux) + Dockerfile de build Linux
```

### Flux d'exécution

```
fichier .xml SoapUI
        │  parser.parse_project()
        ▼
   Project (models.py)
        │  runner.run_project()  — une requête HTTP par TestStep, assertions.evaluate_assertion() par assertion
        ▼
   RunResult (results.py)
        │  report.save_html_report()  /  gui.py (affichage direct)
        ▼
   rapport HTML  /  IHM
```

### Parsing du XML SoapUI

Le parseur (`parser.py`) matche les balises par **nom local uniquement**
(ignore les préfixes de namespace `con:`/`xsi:`), ce qui le rend tolérant aux
variations de version de SoapUI. Le verbe HTTP d'un test step REST est lu en
priorité sur l'attribut `method` du `<con:restRequest>` ; à défaut, il est
résolu en croisant `service`/`resourcePath`/`methodName` avec la définition
d'interface (`<con:interface><con:resource><con:method>`).

### Assertions supportées

`Valid HTTP Status Codes`, `Simple Contains` / `Simple NotContains`,
`XPath Match` (via `lxml`), `JsonPath Match` / `JsonPath Existence Match`
(via `jsonpath-ng`), `Response SLA`, `SOAP Response` / `SOAP Fault Assertion`.
Tout autre type d'assertion (ou de test step — Groovy Script, Property
Transfer, DataSource, JDBC Request...) est détecté mais marqué `SKIPPED`
dans le rapport : ce sont des fonctionnalités SoapUI qui nécessiteraient un
interpréteur Groovy, hors de portée d'un outil Python pur.

### Substitution de propriétés

Seule la syntaxe simple `${nomPropriete}` (propriétés définies au niveau du
projet, dans `<con:properties>` racine) est résolue, avant l'envoi de chaque
requête (endpoint, corps, en-têtes, paramètres). La syntaxe inter-steps
`${#TestCase#...}` (transfert de valeur entre test steps SoapUI) n'est pas
supportée.

## Personnaliser / étendre

- **Ajouter un type d'assertion** : une fonction dans `assertions.py`
  retournant un `AssertionResult`, à enregistrer dans le dict `_DISPATCH` en
  bas du fichier.
- **Modifier le rendu du rapport** : `report.py` génère du HTML/CSS auto-
  contenu (pas de dépendance externe), avec des `<details>` imbriqués par
  suite/cas/step.
- **IHM** : `gui.py` est écrite à la main (pas de fichier `.ui` Qt Designer
  pour l'instant) ; le `Makefile` conserve la cible `make ui` par cohérence
  avec le squelette de projet générique, mais elle est inerte tant qu'aucun
  `ui/*.ui` n'existe.

## Licence

© 2026 Jean-Pierre Gonçalves. Ce programme est un logiciel libre, distribué
sous licence [GNU GPL v3 ou ultérieure](LICENSE) (`GPL-3.0-or-later`). Il
utilise PyQt6, lui-même sous GPL v3.
