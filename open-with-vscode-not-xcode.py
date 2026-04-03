#!/usr/bin/env python3
"""
unxcode.py — Remove Xcode file type associations and/or set explicit VS Code defaults.

Two complementary modes:

1. Plist scan (default behavior):
   Reads the macOS LaunchServices plist for any explicit user-level entries mapped
   to Xcode, then uses duti to reassign them.  On a fresh Xcode install these entries
   are usually absent (Xcode registers via its own Info.plist, not the user plist),
   so this mode may report "nothing to do."

2. --set-defaults:
   Iterates over a curated list of common code/text UTIs that Xcode claims and
   explicitly assigns them to VS Code (or --reassign target) via duti.  This creates
   the user-level overrides that take precedence over Xcode's built-in claims.
   Use this mode when double-clicking .py, .sh, .json, etc. still opens Xcode.

Requirements:
    brew install duti

Usage:
    python3 unxcode.py [--dry-run] [--reassign <bundle-id>] [--set-defaults]

Options:
    --dry-run              Show what would be changed without making any changes.
    --reassign <bundle-id> Bundle ID to reassign to.
                           Default: com.microsoft.vscode
                           Common alternatives:
                             com.apple.TextEdit
                             com.sublimetext.4
                             com.coteditor.CotEditor
                           Use 'none' to strip the custom association (reverts to
                           system default after an lsregister reset — see below).
    --set-defaults         Explicitly assign the curated list of code UTIs to the
                           target app.  Recommended first-run mode on a new machine.

Examples:
    # Scan plist for any existing Xcode entries and reassign to VS Code
    python3 unxcode.py

    # Explicitly set all common code UTIs to VS Code (use this when .py still opens Xcode)
    python3 unxcode.py --set-defaults

    # Preview what --set-defaults would do without changing anything
    python3 unxcode.py --set-defaults --dry-run

    # Assign to TextEdit instead of VS Code
    python3 unxcode.py --set-defaults --reassign com.apple.TextEdit

    # Strip custom associations; system defaults take over after lsregister reset
    python3 unxcode.py --reassign none

Notes:
    - After running, restart any open applications for changes to take effect.
    - If using --reassign none, rebuild the LaunchServices database afterward:
        /System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/\\
LaunchServices.framework/Versions/A/Support/lsregister \\
-kill -r -domain local -domain system -domain user
    - When Xcode is first launched on a new machine it re-registers its UTI claims.
      Run this script again after first launch to re-clean.
    - Code written by Claude Sonnet 4.6, reviewed by Bruce Wilson (usethedata@gmail.com)
"""

import argparse
import plistlib
import subprocess
import sys
from pathlib import Path

XCODE_BUNDLE_ID = "com.apple.dt.Xcode"
DEFAULT_REASSIGN = "com.microsoft.vscode"

LS_PLIST = (
    Path.home()
    / "Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist"
)

ROLE_KEY_MAP = {
    "LSHandlerRoleAll": "all",
    "LSHandlerRoleViewer": "viewer",
    "LSHandlerRoleEditor": "editor",
    "LSHandlerRoleShell": "shell",
}

# UTIs that Xcode claims but are better handled by a code editor.
# Derived from Xcode.app/Contents/Info.plist CFBundleDocumentTypes.
# Xcode-specific types (xcodeproj, xcworkspace, playgrounds, etc.) are intentionally
# excluded — leave those with Xcode.
VSCODE_UTIS = [
    # Python
    ("public.python-script", "all"),
    # Shell / scripting
    ("public.shell-script", "all"),
    ("public.bash-script", "all"),
    ("public.zsh-script", "all"),
    ("public.ksh-script", "all"),
    ("public.csh-script", "all"),
    ("public.tcsh-script", "all"),
    ("public.script", "all"),
    # Web / scripting languages
    ("public.ruby-script", "all"),
    ("public.perl-script", "all"),
    ("public.php-script", "all"),
    # C family
    ("public.c-source", "all"),
    ("public.c-header", "all"),
    ("public.c-plus-plus-source", "all"),
    ("public.c-plus-plus-header", "all"),
    ("public.precompiled-c-header", "all"),
    ("public.precompiled-c-plus-plus-header", "all"),
    ("public.objective-c-source", "all"),
    ("public.objective-c-plus-plus-source", "all"),
    # Assembly
    ("public.assembly-source", "all"),
    ("public.nasm-assembly-source", "all"),
    # Data / config formats
    ("public.json", "all"),
    ("public.xml", "all"),
    ("public.yaml", "all"),
    ("public.geojson", "all"),
    ("public.make-source", "all"),
    # Property lists
    ("com.apple.property-list", "all"),
    ("com.apple.xml-property-list", "all"),
    ("com.apple.dt.document.ascii-property-list", "all"),
    # Markdown
    ("net.daringfireball.markdown", "all"),
    # Plain text
    ("public.plain-text", "all"),
    # Generic source / text (broad — catches many extension-less code files)
    ("public.source-code", "all"),
    # Module maps, mig, iig
    ("public.module-map", "all"),
    ("public.mig-source", "all"),
    ("com.apple.iig-source", "all"),
]


def read_plist() -> dict:
    if not LS_PLIST.exists():
        sys.exit(f"LaunchServices plist not found: {LS_PLIST}")
    result = subprocess.run(
        ["plutil", "-convert", "xml1", "-o", "-", str(LS_PLIST)],
        capture_output=True,
    )
    if result.returncode != 0:
        sys.exit(f"Failed to read plist: {result.stderr.decode()}")
    return plistlib.loads(result.stdout)


def find_xcode_associations(plist_data: dict) -> list[tuple[str, str]]:
    """Return [(content_type, role_str), ...] for every handler mapped to Xcode."""
    found = []
    for handler in plist_data.get("LSHandlers", []):
        content_type = handler.get("LSHandlerContentType") or handler.get(
            "LSHandlerURLScheme"
        )
        if not content_type:
            continue
        for role_key, role_str in ROLE_KEY_MAP.items():
            if handler.get(role_key) == XCODE_BUNDLE_ID:
                found.append((content_type, role_str))
    return found


def strip_xcode_association(plist_data: dict, content_type: str, role_key: str, dry_run: bool):
    """Remove an LSHandler entry from the plist and write it back."""
    handlers = plist_data.get("LSHandlers", [])
    modified = False
    for handler in handlers:
        ct = handler.get("LSHandlerContentType") or handler.get("LSHandlerURLScheme")
        if ct == content_type and handler.get(role_key) == XCODE_BUNDLE_ID:
            print(f"  {'(dry run) ' if dry_run else ''}removing {content_type} [{role_key}] from plist")
            if not dry_run:
                del handler[role_key]
                remaining_roles = [k for k in handler if k.startswith("LSHandlerRole")]
                if not remaining_roles:
                    handlers.remove(handler)
            modified = True
    if modified and not dry_run:
        with open(LS_PLIST, "wb") as f:
            plistlib.dump(plist_data, f, fmt=plistlib.FMT_BINARY)


def run_duti(bundle_id: str, content_type: str, role: str, dry_run: bool):
    cmd = ["duti", "-s", bundle_id, content_type, role]
    print(f"  {'(dry run) ' if dry_run else ''}duti -s {bundle_id} {content_type} {role}")
    if not dry_run:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"    WARNING: {result.stderr.strip()}")


def cmd_set_defaults(target: str, dry_run: bool):
    print(f"{'[DRY RUN] ' if dry_run else ''}Assigning {len(VSCODE_UTIS)} UTIs to: {target}\n")
    for content_type, role in VSCODE_UTIS:
        run_duti(target, content_type, role, dry_run)
    if not dry_run:
        print("\nDone. Restart open applications for changes to take effect.")
        print(
            "Note: if Xcode is launched fresh on this machine, it will re-register\n"
            "its UTI claims. Run this script again afterward to re-clean."
        )


def cmd_scan(target: str, dry_run: bool):
    plist_data = read_plist()
    associations = find_xcode_associations(plist_data)

    if not associations:
        print("No Xcode associations found in LaunchServices plist.")
        print("If files still open in Xcode, run with --set-defaults to create explicit overrides.")
        return

    print(f"Found {len(associations)} Xcode association(s):\n")
    for content_type, role in sorted(associations):
        print(f"  {content_type}  ({role})")

    label = target if target != "none" else "(strip — revert to system default)"
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Reassigning to: {label}\n")

    role_str_to_key = {v: k for k, v in ROLE_KEY_MAP.items()}

    for content_type, role in sorted(associations):
        if target == "none":
            strip_xcode_association(
                plist_data, content_type, role_str_to_key[role], dry_run
            )
        else:
            run_duti(target, content_type, role, dry_run)

    if not dry_run:
        print("\nDone.")
        if target == "none":
            print(
                "Run the following to rebuild the LaunchServices database so "
                "system defaults take effect:\n\n"
                "  /System/Library/Frameworks/CoreServices.framework/Versions/A"
                "/Frameworks/LaunchServices.framework/Versions/A/Support/"
                "lsregister -kill -r -domain local -domain system -domain user"
            )
        else:
            print(
                "Restart any open applications for changes to take effect.\n"
                "Note: if Xcode is launched fresh on this machine, it will re-register\n"
                "its UTI claims. Run this script again afterward to re-clean."
            )


def main():
    parser = argparse.ArgumentParser(
        description="Reassign file type associations away from Xcode.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making any changes",
    )
    parser.add_argument(
        "--reassign",
        default=DEFAULT_REASSIGN,
        metavar="BUNDLE_ID",
        help=f"Target bundle ID (default: {DEFAULT_REASSIGN}). Use 'none' to strip.",
    )
    parser.add_argument(
        "--set-defaults",
        action="store_true",
        help="Explicitly assign all curated code UTIs to the target app",
    )
    args = parser.parse_args()

    if args.reassign == "none" and args.set_defaults:
        sys.exit("--set-defaults cannot be combined with --reassign none")

    if args.set_defaults:
        cmd_set_defaults(args.reassign, args.dry_run)
    else:
        cmd_scan(args.reassign, args.dry_run)


if __name__ == "__main__":
    main()
