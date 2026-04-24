# system_utils

A small collection of scripts I use to manage my personal *nix systems (macOS, Ubuntu, and Synology DSM). macOS-specific scripts (AppleScripts, `duti`/LaunchServices helpers, etc.) live separately, in `mac-scripting/` outside this repo.

Scripts here install to either `~/bin/` (cross-system scripts, intended to run on every *nix system I manage — bears and Synologies) or `~/.local/bin/` (machine-local or OS-specific scripts). See `CLAUDE.md` for the install-location and Python virtual-environment conventions.

This repo is public. **Never commit** secrets, credentials, API keys, tokens, or personally identifying information — including hostnames or IP addresses of real machines.

## What's here
- **`chezmoi-all`** — Run a `chezmoi` command across every chezmoi-managed host in one shot. Reads the host list from `config/chezmoi-hosts.json`.
- **`rebuild-chezmoi-cache`** — Regenerate `config/chezmoi-hosts.json` from a curated set of device-description files maintained outside this repo.
- **`system-status-check/`** — Self-contained Python package that runs nightly on a single orchestrator host, probes every managed system over SSH, and emits a JSON + Markdown status report. Has its own README and sets the target pattern for new utilities here: XDG-aligned venv, `~/.local/bin` install, `src/` layout, fixture-driven parser tests.

## Installation
`make all` installs the cross-system scripts to `~/bin/` and refreshes `config/chezmoi-hosts.json`. `system-status-check/` installs separately via its own `install.sh`.
