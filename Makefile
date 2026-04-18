BINDIR := $(HOME)/bin
CONFDIR := $(HOME)/.config/chezmoi-all
INFRA_DIR := $(BEWMAIN)/MainVault/Reference/Cyberinfrastructure

.PHONY: all install-scripts chezmoi-cache install-config
# .PHONY: cron

all: install-scripts chezmoi-cache install-config

install-scripts: $(BINDIR)/brew-nightly-update.sh $(BINDIR)/brew-monthly-inventory.sh \
                 $(BINDIR)/chezmoi-all $(BINDIR)/chezmoi-all-dryrun \
                 $(BINDIR)/rebuild-chezmoi-cache

$(BINDIR)/brew-nightly-update.sh: brew-nightly-update.sh
	install -m 0755 brew-nightly-update.sh $(BINDIR)/brew-nightly-update.sh

$(BINDIR)/brew-monthly-inventory.sh: brew-monthly-inventory.sh
	install -m 0755 brew-monthly-inventory.sh $(BINDIR)/brew-monthly-inventory.sh

$(BINDIR)/chezmoi-all: chezmoi-all
	install -m 0755 chezmoi-all $(BINDIR)/chezmoi-all

$(BINDIR)/chezmoi-all-dryrun: chezmoi-all-dryrun
	install -m 0755 chezmoi-all-dryrun $(BINDIR)/chezmoi-all-dryrun

$(BINDIR)/rebuild-chezmoi-cache: rebuild-chezmoi-cache
	install -m 0755 rebuild-chezmoi-cache $(BINDIR)/rebuild-chezmoi-cache

chezmoi-cache: config/chezmoi-hosts.json

config/chezmoi-hosts.json: $(INFRA_DIR)/README.md
	rebuild-chezmoi-cache

# Install a local copy of the host cache so launchd-triggered runs of
# chezmoi-all don't need to read from the CloudStorage/Dropbox path
# (which requires Full Disk Access for launchd-spawned processes).
install-config: $(CONFDIR)/chezmoi-hosts.json

$(CONFDIR)/chezmoi-hosts.json: config/chezmoi-hosts.json
	mkdir -p $(CONFDIR)
	install -m 0644 config/chezmoi-hosts.json $(CONFDIR)/chezmoi-hosts.json

# cron: cron.conf
# 	python3 install-cron.py
