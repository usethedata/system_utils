# system-status-check — Design

Living design document for the `system-status-check` package. Describes the tool as it currently exists; updated when the tool changes. For end-user "how do I install / run this," see `README.md`. For the project history and plan-time context, see `Progs/lessons-learned.md` (kept outside this public repo).

## Purpose

A single nightly report that summarizes the update status of every *nix host an operator manages. Descriptive only — does **not** apply any updates. The report is consumed by a downstream "daily brief" workflow that adds commentary; this tool is the data layer.

## Scope

### What it checks
- **Per-host reachability** (gates the rest)
- **chezmoi drift** — local target drift, source-repo uncommitted/ahead/behind
- **Homebrew outdated** (macOS)
- **apt upgradable** (Ubuntu) — with phased-update filtering
- **Synology DSM available package updates** (DSM)
- **Synology DSM available OS updates** (DSM)

### What it deliberately does not do
- Apply updates of any kind
- CVSS / severity tagging
- Disk, backup-freshness, cert-expiration, Tailscale, Time Machine, etc. checks (these are candidates for future modules)
- iOS/iPadOS device coverage

## Architecture

### Pattern
- **Orchestrator** runs on one designated host (the "orchestrator host"), sequentially over a configured host list.
- For each host + applicable check, the orchestrator dispatches a small bash snippet via `ssh <alias> bash -s` (or runs locally if the host is the orchestrator itself).
- Each remote snippet emits stdout that the corresponding check parser consumes; stderr is captured separately for error context.
- The orchestrator aggregates per-host results into one top-level JSON document, then a renderer step produces a Markdown view.
- Both files are written to a Dropbox-synced report directory, with self-describing filenames (`system-status-check-YYYY-MM-DD.{json,md}`) that the daily brief can wikilink from an Obsidian note.

### Why sequential
Operator preference; simpler logs, easier debugging. Per-host budget is generous — the full run takes well under a minute against six hosts in our deployment.

### Language
- Orchestrator and renderer: Python 3 in a single package.
- Remote snippets: small bash heredocs inlined in the SSH call. **No dependencies installed on remote hosts** — the only requirements on a remote are the OS-native tools (`chezmoi`, `apt-get`, `brew`, `synopkg`, `synoupgrade`).

### Modularity
One module per capability under `src/system_status_check/checks/`:

| Module | Applies to | Notes |
|---|---|---|
| `reachability.py` | all | `ssh -o BatchMode=yes -o ConnectTimeout=N <alias> true` probe; gates the rest |
| `chezmoi.py` | all | local-drift + source-repo sub-checks |
| `brew.py` | macOS | `brew outdated --json=v2` |
| `apt.py` | Ubuntu | `apt-get update` (sudoers-protected) + `apt list --upgradable` + phased-update filter |
| `synology_packages.py` | Synology DSM | `synopkg checkupdateall` |
| `synology_os.py` | Synology DSM | `sudo synoupgrade --check` (sudoers-protected) |

Each module exports `NAME` and a `run(host_cfg, settings) -> CheckResult-shaped dict` function. Adding a new check means adding one module and an entry in the dispatcher's `_CHECKS` registry, plus listing the check name in the relevant hosts' `checks:` array in `hosts.yaml`.

### Reusable techniques used here
- **Sentinel-fenced multi-output bash scripts.** When a remote check needs to capture multiple commands' output and exit codes in one SSH session, the bash snippet emits paired sentinel markers (`##NAME-BEGIN##` … `##NAME-END rc=N##`) and the Python parser splits on those. Used by the chezmoi and apt checks. Cheaper than one SSH call per command; more robust than relying on shell pipes.
- **PATH prelude in the SSH wrapper.** Non-interactive SSH on most *nix systems gets a sparser PATH than an interactive login shell. The `ssh.run()` helper prepends a known-good PATH (`~/bin`, `~/.local/bin`, `/usr/local/bin`, `/opt/homebrew/bin`, `/snap/bin`, `/usr/syno/bin`, `/usr/syno/sbin`, plus standard system dirs) so checks find the OS-native tools without depending on the remote's login-shell setup.

### Reporting philosophy
The Markdown is **informational, not evaluative**. No "OK / WARN / ERROR" labels in the user-facing output. The JSON keeps a structured `status` field per check for programmatic consumers (the daily brief, future severity-enrichment work); the Markdown renderer ignores that field and conveys state through typography.

The typography codex (assumes a reader theme where bold = red, italic = blue):

| Meaning | Style |
|---|---|
| Category label (check name in details) | **bold** |
| System name in summary list | **bold** with internal link |
| Clean / no updates | plain text |
| Notable count or value | *italic* |
| Strong alert (Stale, Unreachable, Out of Sync) | ***bold-italic*** |

Rationale: a status report is information, not a verdict. The reader decides what's actionable. Aggressive severity labels train readers to either over-react to noise or develop banner blindness; pure information with selective emphasis avoids both.

## Configuration

### `hosts.yaml`
Machine-local config at `~/.config/system-status-check/hosts.yaml` on the orchestrator host. Not synced, not chezmoi-managed. Shape:

```yaml
hosts:
  - alias: <ssh-alias-1>
    os: macos                            # macos | ubuntu | synology
    checks: [reachability, chezmoi, brew]
  - alias: <ssh-alias-2>
    os: macos
    checks: [reachability, chezmoi, brew]
    unreachable_is_expected: true        # mutes the warning bucket for laptops
  - alias: <ssh-alias-3>
    os: ubuntu
    checks: [reachability, chezmoi, apt]
    local: true                          # runs locally (no SSH); for the orchestrator's own host
  - alias: <ssh-alias-4>
    os: synology
    checks: [reachability, chezmoi, synology_os, synology_packages]

settings:
  ssh_connect_timeout_seconds: 10
  per_check_timeout_seconds: 120
  report_dir: "~/Dropbox/BEWMain/MainVault/Data/system-status"
  log_dir: "~/Dropbox/BEWMain/Data/logs"
  flagged_packages:
    brew:
      - node
      - python@*
      - openssl@*
```

### Per-host SSH resolution
The tool uses bare aliases (`ssh <alias>`); per-host resolution (HostName, User, Port, IdentityFile, etc.) is delegated to `~/.ssh/config` on the orchestrator. **No hostnames, IPs, ports, keys, or usernames appear in this repo.** A bare alias that doesn't resolve in `~/.ssh/config` is a prerequisite to fix before deploying.

## Per-check specifications

Each check returns a dict of this shape (consumed by the dispatcher and renderer):

```
{
  "status": "ok" | "warn" | "error" | "unreachable" | "skipped",
  "items": [...],          # check-specific structured rows
  "counts": {...},          # named counts; rendered selectively in Markdown
  "raw": "...",             # optional: short verbatim excerpt of stdout
  "error": "...",           # only if status = error
  "warnings": ["...", ...], # optional: in-band notes (e.g., stale apt cache hint)
}
```

### chezmoi (two sub-checks, one SSH call)
1. **Local drift** — `chezmoi status`. Two-column status codes + path. Items: `[{path, source_state, target_state}]`.
2. **Source-repo state** — `chezmoi git -- fetch --quiet` (best-effort; tolerated on failure) then `chezmoi git -- status --porcelain=v1 --branch`. Counts: `source_uncommitted`, `source_ahead_of_remote`, `source_behind_remote`. The fetch is required because the porcelain status reads local remote-tracking refs; without a fetch, "behind remote" reports stale data.

Rolled-up status: `ok` if all sub-counts are zero, `warn` otherwise.

A previous iteration also ran `chezmoi update --dry-run`. That command prompts interactively when the target state has drifted locally, and non-interactive SSH has no TTY, so the prompt fails. The local-drift count and the source-behind-remote count together already answer the "is this machine in sync?" question along every axis we care about, so the dry-run sub-check was removed.

### Homebrew (macOS)
- Command: `brew outdated --json=v2`. Structured output; no `brew update` needed (Homebrew's auto-update keeps the formulae index fresh).
- Items: `[{name, type: formula|cask, installed_versions, current_version, pinned, flagged?}]`.
- The `flagged_packages.brew` glob list in `hosts.yaml` annotates packages whose upgrade tends to require operator follow-up (e.g., `node`, `python@*` may trigger macOS TCC re-grants on cloud-storage paths).
- `brew` is never privileged.

### apt (Ubuntu)
- Cache-refresh: `sudo -n apt-get update -qq` (requires a sudoers drop-in granting NOPASSWD for that exact command). The check **always attempts the refresh**; on failure it reads `/var/lib/apt/periodic/update-success-stamp` and surfaces a `Stale` flag in the report when the last successful refresh is more than 24h old.
- Listing: `apt list --upgradable`.
- **Phased-update filtering.** Ubuntu's archive serves package updates to a stable percentage of users at a time. `apt list --upgradable` shows phased packages even when `apt upgrade` won't actually install them. The check parses `apt-get -s upgrade` for the "deferred due to phasing" section and removes those packages from the actionable list. The deferred count is preserved in JSON `counts.deferred_phased` for telemetry but is not rendered.
- Items: `[{name, current_version, candidate_version, origin, arch}]`.

### Synology packages (DSM)
- Command: `synopkg checkupdateall`. Returns a JSON-shaped array; empty list is `[]` when nothing is pending. Unprivileged.
- The `checkupdate` (singular) variant of `synopkg` requires a package-name argument — it is not the list-all command. `checkupdateall` is.
- Items: `[{id, name, available_version, beta}]`.

### Synology OS (DSM)
- Command: `sudo -n /usr/syno/sbin/synoupgrade --check`. **Sudoers gotcha:** DSM's default `/etc/sudoers` blocks non-interactive sudo (`sudo -n`) via a TTY requirement, even when a NOPASSWD rule is present. The sudoers drop-in **must** include `Defaults:<user> !requiretty` for non-interactive execution to succeed. (See "Operational notes" below.)
- Known clean output: literal `UPGRADE_CHECKNEWDSM` on stdout, and **rc=255** (not 0). The parser keys off the stdout token, not the rc.
- Independent fallback: each Synology emails its administrator when a DSM update is ready. If this check ever misbehaves, that email is the authoritative signal.
- Items: `{raw: "<verbatim stdout>"}`.

### Reachability
- Command: `ssh -o BatchMode=yes -o ConnectTimeout=<N> <alias> true`.
- On failure, every other configured check for that host returns `status: unreachable` without dispatching.
- Summary accounting (JSON): a host with `unreachable_is_expected: true` (e.g., a laptop) contributes to `hosts_warn` rather than `hosts_unreachable` when unreachable. `hosts_unreachable` is reserved for hosts that were expected to be reachable and weren't.
- Markdown rendering: any unreachable host shows `***Unreachable***` in both the summary line and details section, regardless of `unreachable_is_expected`. The expectation flag affects only the JSON-side counter accounting, not the rendered report.

## Output format

### JSON (primary; for programmatic consumers)
```json
{
  "schema_version": 1,
  "run": {
    "started_at": "2026-04-24T04:00:00-04:00",
    "finished_at": "2026-04-24T04:00:34-04:00",
    "elapsed_seconds": 34.0,
    "orchestrator_host": "<orchestrator-hostname>",
    "script_version": "0.1.0"
  },
  "summary": {
    "hosts_total": 6,
    "hosts_ok": 4,
    "hosts_warn": 1,
    "hosts_error": 0,
    "hosts_unreachable": 1,
    "updates_pending_total": 17
  },
  "hosts": [
    {
      "alias": "<host-alias>",
      "os": "macos",
      "overall_status": "warn",
      "checks": {
        "reachability": {"status": "ok"},
        "chezmoi": {"status": "ok", "counts": {...}},
        "brew": {"status": "warn", "counts": {"outdated": 5, "flagged": 1}, "items": [...]}
      }
    }
  ],
  "errors": []
}
```

### Markdown (human-readable)
- No top-level H1 (filename serves as title in Obsidian).
- Leading metadata bullet block: `Started`, `Finished`, `Elapsed`, `Orchestrator`, `Detailed Log` (rendered as a `vscode://file/...` link translated to the macOS-side Dropbox path so it opens correctly in the macOS Obsidian environment).
- `# Summary` — one bullet per host, alphabetical, system name bold and linked to its Detail anchor.
- `# Details` — `## SystemName` per host, alphabetical. Each system lists its checks in canonical order: chezmoi first, then per-OS package managers (Synology: OS before Packages).
- An unreachable host in the Details section shows only `- ***Unreachable***`; the rendered details are intentionally minimal in that case.

See "Reporting philosophy" above for the typography rules.

## File and path layout

| Path | Purpose |
|---|---|
| `~/.local/bin/system-status-check` | Launcher (thin wrapper that activates the venv and invokes `python -m system_status_check.main`) |
| `${XDG_DATA_HOME:-$HOME/.local/share}/python/envs/system-status-check/` | Virtual environment |
| `~/.config/system-status-check/hosts.yaml` | Per-host config (machine-local; not synced) |
| `~/.config/systemd/user/system-status-check.{service,timer}` | systemd user units (Linux orchestrator host) |
| `<report_dir>/system-status-check-YYYY-MM-DD.{json,md}` | Reports (date-stamped, overwritten on rerun by design) |
| `<log_dir>/system-status-check-YYYYMMDD-HHMMSS.log` | Run log (per-run timestamped) |

Filenames follow the "Generated file naming" convention in `Progs/CLAUDE.md`: a tool-name slug + date/timestamp, so any filename stands on its own without depending on its containing path for context.

## Scheduling

On a Linux orchestrator host: a systemd user timer (`OnCalendar=*-*-* 04:00:00`, `Persistent=true`). Requires `loginctl enable-linger <user>` so the user manager runs without an active login session.

The reports are produced before the operator's morning routine. `Persistent=true` means a run that's missed because the host was off at 04:00 fires at next boot.

No reliance on cron. No reliance on any other host being awake — every check is initiated from the orchestrator.

## Report and log file semantics

- **Report files** are date-stamped and **overwritten** on any rerun the same day. The scheduled run produces the canonical report; manual reruns (debugging, `--host`, `--check`) overwrite it. To preserve a previous day's report before rerunning, copy it aside manually. `--dry-run` writes to `/tmp/` instead, so debugging runs don't clobber the canonical report.
- **Log files** are per-run timestamped. Every invocation produces a new file.

## Retention

This tool does **not** manage its own file lifecycle. Retention for reports and logs is handled centrally by the operator's broader file-lifecycle infrastructure. Keeping lifecycle management in one place is a deliberate choice — having multiple tools each set their own retention window scatters policy.

## Operational notes

### Sudoers drop-ins required
Two checks need `sudo -n`. Each remote host needs a narrowly scoped sudoers drop-in.

**Linux (Ubuntu) hosts that run the apt check:**
```
# /etc/sudoers.d/system-status-check
<user> ALL=(root) NOPASSWD: /usr/bin/apt-get update -qq
<user> ALL=(root) NOPASSWD: /usr/bin/apt-get update
```

**Synology DSM hosts that run the synology_os check:**
```
# /etc/sudoers.d/system-status-check
Defaults:<synology-ssh-user> !requiretty
<synology-ssh-user> ALL=(root) NOPASSWD: /usr/syno/sbin/synoupgrade --check
```
The `!requiretty` line is mandatory on DSM — without it, NOPASSWD doesn't apply to non-TTY sessions and the check fails with "a password is required."

Validate either drop-in with `visudo -c -f /etc/sudoers.d/system-status-check` (Linux). DSM has no `visudo`; check the file mode (`0440`) and re-test the command after install.

### SSH prerequisites
- Bare-alias resolution in `~/.ssh/config` on the orchestrator for every host in `hosts.yaml`.
- Key-based auth (no password prompt) — the reachability probe uses `BatchMode=yes`.
- Each remote host has the orchestrator's public key in `~/.ssh/authorized_keys`.

## Future enhancements (roadmap)

- **CVSS / security-severity enrichment** — cross-reference outdated package names against vulnerability feeds (Ubuntu USN, Homebrew advisory list, DSM release notes); mark high-severity entries in the JSON for the daily brief to surface.
- **Additional checkers** — cert expirations, Time Machine status, Tailscale `status`, disk-usage thresholds, backup-freshness for each NAS.
- **macOS system software updates** — `softwareupdate -l` (non-privileged listing).
- **Mac App Store available updates** — `mas outdated` (requires the `mas` CLI installed and signed in on each Mac).
- **Upstream updates for locally running MCPs** — file-based version checks against the relevant `Progs/ai/` clones; consolidates an existing manual procedure into this report.
- **Write-back into a task system** — auto-file a task when a high-severity entry appears.
- **Disruptive-update tracking, with (conditional) package-pinning support.** A two-tier roadmap, gated on whether the lower tier is sufficient.

  **Tier 1 — flagged_packages as informational annotation (likely to do).** Build out the existing `flagged_packages` mechanism so the report visibly tags updates that have historically required manual follow-up (e.g., `node` and `python@*` on macOS may trigger TCC re-grants on cloud-storage paths after upgrade; a Linux kernel bump implies a reboot; a DSM package update may need a maintenance window). Concrete work:
    - Surface the flagged count in the Summary line, not only in the per-package details. (Currently the details show a `⚑` suffix on flagged items, but the Summary doesn't reflect them at all.)
    - Document the semantic clearly: "flagged" means *informational* — needs extra care when the operator chooses to upgrade. The tool does not block or skip the upgrade; it just calls it out.
    - Extend the config beyond brew. `hosts.yaml`'s `flagged_packages` map is already structured per-OS-key; wire the apt, synology_packages, and (potentially) synology_os checks to read their own flagged lists. Glob patterns like `python@*` work via `fnmatch`.

  **Tier 2 — native pin/hold integration (might do).** If Tier 1 turns out to be insufficient and the operator wants the system to recognize "I've actively decided not to upgrade this," integrate with the package managers' own pin/hold mechanisms (`brew pin <formula>`, `sudo apt-mark hold <package>`). Required work:
    - Capture pinned/held state. Homebrew already returns `pinned` in its JSON output (the brew check already passes this through). apt would need a separate `apt-mark showhold` call.
    - Decide how pinned/held items render. Three options to evaluate at that point:
      - *Status quo*: contribute to the "updates pending" count, annotated in details with `(pinned)`.
      - *Filter entirely*: treat as not-actionable, similar to how Ubuntu phased updates are handled today.
      - *Split count*: render the Summary as e.g. `Brew: 12 updates pending, 1 pinned`.
    - Casks have no first-class pin in Homebrew — would need a separate exclusion convention if cask-pinning matters.

  Tier 2 is explicitly conditional. If Tier 1 plus the operator's mental model suffices, this tier doesn't get built.

## Known limitations

- **synology_os parser is half-validated.** We've only seen the clean path (`UPGRADE_CHECKNEWDSM`, rc=255). Behavior when a real DSM update is pending is inferred from the existing parser logic and is captured verbatim in the report's `raw` field. The DSM email notification remains the authoritative independent signal until a real update appears and the parser is refined.
- **silverbear-style "expected unreachable" hosts can mask real outages.** A laptop that's been unreachable for many consecutive nights still reports as a quiet warn rather than escalating. A "last seen" / consecutive-unreachable-N-nights concept would help; not implemented in v1.
- **chezmoi `git -- fetch` runs nightly.** Trivial network cost, but worth noting if hosts are bandwidth-constrained.

## Follow-ups tracked elsewhere

These items are tracked in `Progs/TODO.md` because they cross multiple tools or affect the broader infrastructure:
- Migrate `chezmoi-all` to read its host list from a `hosts.yaml` distributed via chezmoi; retire `system_utils/config/chezmoi-hosts.json` and the canonical-in-Dropbox + local-cache pattern.
- Cross-bear cleanup of `~/bin` to make chezmoi the distribution mechanism for cross-host scripts.
- Migrate other projects' venvs to the XDG-aligned target pattern.
