#!/usr/bin/env bash
# install.sh — set up system-status-check on grizzledbear.
#
# Idempotent. Run after pulling a fresh copy of the repo.
#
# Creates/refreshes:
#   - XDG venv at $XDG_DATA_HOME/python/envs/system-status-check (default: ~/.local/share/...)
#   - Launcher at ~/.local/bin/system-status-check (rewritten from launcher template)
#   - Config scaffold at ~/.config/system-status-check/hosts.yaml (only if missing)
#
# Systemd units are installed separately — see the systemd/ directory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_SRC_DIR="${SCRIPT_DIR}/src"

XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"

VENV_DIR="${XDG_DATA_HOME}/python/envs/system-status-check"
LAUNCHER_PATH="${HOME}/.local/bin/system-status-check"
CONFIG_DIR="${XDG_CONFIG_HOME}/system-status-check"
CONFIG_FILE="${CONFIG_DIR}/hosts.yaml"
CONFIG_EXAMPLE="${SCRIPT_DIR}/hosts.yaml.example"

log() { printf '[install] %s\n' "$*"; }

# 1. Python venv
if [[ ! -d "${VENV_DIR}" ]]; then
    log "creating venv at ${VENV_DIR}"
    mkdir -p "$(dirname "${VENV_DIR}")"
    python3 -m venv "${VENV_DIR}"
else
    log "venv exists at ${VENV_DIR}"
fi

log "installing/updating dependencies"
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip
"${VENV_DIR}/bin/pip" install --quiet -r "${SCRIPT_DIR}/requirements.txt"

# 2. Launcher
mkdir -p "$(dirname "${LAUNCHER_PATH}")"
log "writing launcher at ${LAUNCHER_PATH}"
sed \
    -e "s|__VENV_DIR__|${VENV_DIR}|g" \
    -e "s|__PKG_SRC_DIR__|${PKG_SRC_DIR}|g" \
    "${SCRIPT_DIR}/system-status-check.launcher" > "${LAUNCHER_PATH}"
chmod +x "${LAUNCHER_PATH}"

# 3. Config scaffold (do not overwrite)
mkdir -p "${CONFIG_DIR}"
if [[ ! -f "${CONFIG_FILE}" ]]; then
    log "seeding ${CONFIG_FILE} from hosts.yaml.example — edit before running"
    cp "${CONFIG_EXAMPLE}" "${CONFIG_FILE}"
    chmod 600 "${CONFIG_FILE}"
else
    log "config exists at ${CONFIG_FILE} (leaving as-is)"
fi

log "done."
log ""
log "Next steps:"
log "  1. Edit ${CONFIG_FILE} with real SSH aliases"
log "  2. Try a single-host run:   ${LAUNCHER_PATH} --dry-run --host <alias> --check reachability"
log "  3. Install systemd units from ${SCRIPT_DIR}/systemd/ once happy"
