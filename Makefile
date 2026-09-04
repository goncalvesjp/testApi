APP_NAME    := SoapUITester
LINUX_BIN   := soapui-tester
VERSION     := $(shell cat VERSION)

PYTHON      := python3
VENV        := .venv
# Invoque pip comme module de l'interpreteur du venv plutot que le script
# .venv/bin/pip : ce script porte un shebang fige sur le chemin absolu du
# venv au moment de son installation, et casse si le projet est deplace.
PIP         := $(VENV)/bin/python -m pip
PYI         := $(VENV)/bin/pyinstaller
PYUIC       := $(VENV)/bin/pyuic6

UI_DIR      := ui
GUI_DIR     := gui
UI_SOURCES  := $(wildcard $(UI_DIR)/*.ui)
UI_GENERATED := $(patsubst $(UI_DIR)/%.ui,$(GUI_DIR)/ui_%.py,$(UI_SOURCES))

# CLI de conteneurs pour `make linux` : `container` (Apple, natif macOS) par
# defaut. Passe CONTAINER=docker si tu preferes/as Docker Desktop a la place.
CONTAINER   := container

DIST_DIR    := dist
BUILD_DIR   := build

.PHONY: help venv ui test run macos linux linux-native dist dist-macos dist-linux clean

help:
	@echo "Cibles disponibles :"
	@echo "  make venv          - cree .venv (deps + PyInstaller)"
	@echo "  make ui            - regenere gui/ui_*.py depuis ui/*.ui (pyuic6, si present)"
	@echo "  make test          - lance la suite pytest (Qt offscreen)"
	@echo "  make run           - lance l'app depuis les sources (IHM PyQt)"
	@echo "  make macos         - construit $(DIST_DIR)/macos/$(APP_NAME).app"
	@echo "  make linux         - construit $(DIST_DIR)/linux/ via 'container' (cross-build depuis macOS)"
	@echo "  make linux-native  - construit $(DIST_DIR)/$(LINUX_BIN) localement (a lancer sur une machine Linux)"
	@echo "  make dist          - macos + linux, puis archive dist/*.zip et *.tar.gz"
	@echo "  make clean         - supprime build/ dist/ et les environnements virtuels"

$(VENV)/bin/python3:
	$(PYTHON) -m venv $(VENV)

venv: $(VENV)/bin/python3
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements.txt pytest pytest-qt pyinstaller

## Regenere gui/ui_*.py a partir de ui/*.ui (edite les .ui avec Qt Designer, pas les .py generes).
## Non utilise pour l'instant : l'IHM de ce projet (soapui_tester/gui.py) est ecrite a la main,
## sans fichier .ui. Cible conservee pour coherence avec le squelette, sans effet tant que ui/
## est vide.
$(GUI_DIR)/ui_%.py: $(UI_DIR)/%.ui | venv
	$(PYUIC) $< -o $@

ui: venv $(UI_GENERATED)

test: venv
	QT_QPA_PLATFORM=offscreen $(VENV)/bin/python -m pytest tests/ -v

run: venv
	$(VENV)/bin/python main.py

## macOS : bundle .app natif, construit localement.
macos: venv
	$(PYI) packaging/macos.spec --noconfirm --clean \
		--distpath $(DIST_DIR)/macos --workpath $(BUILD_DIR)/macos
	@echo "-> $(DIST_DIR)/macos/$(APP_NAME).app"

## Linux : cross-build depuis macOS via `container` (aucun outil Linux requis en local).
## Cible amd64 (Rosetta) : PyQt6 n'a pas de wheel Linux arm64 sur PyPI.
linux:
	$(CONTAINER) system start
	$(CONTAINER) build --arch amd64 -t $(LINUX_BIN)-builder \
		-f packaging/Dockerfile.linux .
	mkdir -p $(DIST_DIR)/linux
	$(CONTAINER) run --rm --arch amd64 --rosetta \
		-v $(CURDIR)/$(DIST_DIR)/linux:/out $(LINUX_BIN)-builder
	@echo "-> $(DIST_DIR)/linux/$(LINUX_BIN)"

## Linux : build direct, a lancer sur une vraie machine/VM Linux (pas de conteneur).
linux-native:
	$(PYTHON) -m venv .venv-linux
	.venv-linux/bin/pip install -q --upgrade pip
	.venv-linux/bin/pip install -q -r requirements.txt pyinstaller
	.venv-linux/bin/pyinstaller packaging/linux.spec --noconfirm --clean \
		--distpath $(DIST_DIR) --workpath $(BUILD_DIR)/linux
	@echo "-> $(DIST_DIR)/$(LINUX_BIN)"

dist-macos: macos
	cd $(DIST_DIR)/macos && zip -qr ../$(APP_NAME)-macos-$(VERSION).zip $(APP_NAME).app
	@echo "-> $(DIST_DIR)/$(APP_NAME)-macos-$(VERSION).zip"

dist-linux: linux
	tar -czf $(DIST_DIR)/$(LINUX_BIN)-linux-$(VERSION).tar.gz -C $(DIST_DIR)/linux $(LINUX_BIN)
	@echo "-> $(DIST_DIR)/$(LINUX_BIN)-linux-$(VERSION).tar.gz"

dist: dist-macos dist-linux

clean:
	rm -rf $(BUILD_DIR) $(DIST_DIR) $(VENV) .venv-linux
	find . -name "__pycache__" -type d -exec rm -rf {} +
