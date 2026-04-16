#!/usr/bin/env python3
"""
set-file-associations.py — Apply preferred file-type-to-app associations via duti.

Documents and enforces a curated set of file type overrides. Edit the MAPPINGS
list below to add or change associations. Each entry is a tuple of:

    (description, uti_or_extension, bundle_id, role)

    description         Human-readable label for the output
    uti_or_extension    UTI (e.g. 'public.mp3') or file extension (e.g. '.py')
    bundle_id           App bundle ID (use lowercase; macOS is case-insensitive)
    role                'all', 'editor', 'viewer', or 'shell'

Requirements:
    brew install duti

Usage:
    python3 set-file-associations.py [--dry-run]

Options:
    --dry-run   Show what would be changed without making any changes.

To find a bundle ID:
    mdls -name kMDItemCFBundleIdentifier /Applications/SomeApp.app

To find the UTI for a file type:
    mdls -name kMDItemContentType /path/to/file.mp3
"""

import argparse
import subprocess
import sys

# ---------------------------------------------------------------------------
# Edit this list to document and enforce your preferred associations.
# ---------------------------------------------------------------------------
MAPPINGS = [
    # Audio/video — QuickTime Player
    ("MP3 audio",           "public.mp3",    "com.apple.quicktimeplayerx", "all"),
    ("MPEG-4 audio/video",  "public.mpeg-4", "com.apple.quicktimeplayerx", "all"),

    # Spreadsheets — Excel
    ("CSV",  "public.comma-separated-values-text", "com.microsoft.excel", "all"),

    # Calendar files — BusyCal
    ("iCalendar file (.ics)",  "com.apple.ical.ics", "com.busymac.busycal-setapp", "all"),
    ("vCalendar file (.vcs)",  "com.apple.ical.vcs", "com.busymac.busycal-setapp", "all"),
    ("webcal URL scheme",      "webcal",             "com.busymac.busycal-setapp", "all"),

    # Log/output files — VS Code
    ("Log files (.log)",    ".log", "com.microsoft.VSCode", "all"),
    ("Error files (.err)",  ".err", "com.microsoft.VSCode", "all"),
    ("Output files (.out)", ".out", "com.microsoft.VSCode", "all"),
]
# ---------------------------------------------------------------------------


def run_duti(bundle_id: str, uti: str, role: str, dry_run: bool) -> bool:
    cmd = ["duti", "-s", bundle_id, uti, role]
    print(f"  {'(dry run) ' if dry_run else ''}duti -s {bundle_id} {uti} {role}")
    if not dry_run:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"    WARNING: {result.stderr.strip()}")
            return False
    return True


def check_duti():
    result = subprocess.run(["which", "duti"], capture_output=True)
    if result.returncode != 0:
        sys.exit("duti not found. Install with: brew install duti")


def main():
    parser = argparse.ArgumentParser(
        description="Apply preferred file type associations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making any changes",
    )
    args = parser.parse_args()

    check_duti()

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Applying {len(MAPPINGS)} file association(s):\n")

    errors = 0
    for description, uti, bundle_id, role in MAPPINGS:
        print(f"  {description}  →  {bundle_id}")
        ok = run_duti(bundle_id, uti, role, args.dry_run)
        if not ok:
            errors += 1

    print()
    if args.dry_run:
        print("Dry run complete — no changes made.")
    elif errors:
        print(f"Done with {errors} warning(s). Check output above.")
    else:
        print("Done. Restart open applications for changes to take effect.")


if __name__ == "__main__":
    main()
