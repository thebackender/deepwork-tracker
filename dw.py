#!/usr/bin/env python3
"""Deep work tracker.

Usage:
  dw add                           ask for each field
  dw add 90 thesis "Wrote intro"   add a record in one line
  dw stats                         open the statistics page in the browser

A record's time is the session's start time (now minus the duration).
Edit deepwork_logs.md by hand to fix past records; the next `dw add`
commits those edits separately as "Manual edits".
"""
import json
import re
import subprocess
import sys
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_FILE = ROOT / "deepwork_logs.md"
WEB_DIR = ROOT / "web"
GOAL_HOURS = 10_000


# --- File format --------------------------------------------------------------
# Only read_records() and write_record() know the file is a Markdown table.
# To switch formats, rewrite these two functions.

HEADER = (
    "# Deep Work Log\n"
    "\n"
    "| Date | Time | Duration | Tag | Description |\n"
    "|------|------|----------|-----|-------------|\n"
)
CELL_SPLIT = re.compile(r"(?<!\\)\|")  # split on | but not on \|


def read_records():
    """Return all records as dicts, oldest first. Unreadable rows are reported and skipped."""
    if not LOG_FILE.exists():
        return []
    records = []
    lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
    for num, line in enumerate(lines, 1):
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = CELL_SPLIT.split(line)[1:]
        if cells and not cells[-1].strip():
            cells.pop()
        cells = [c.strip() for c in cells]
        if not cells or cells[0] == "Date" or set(cells[0]) <= set("-: "):
            continue  # header or separator row
        try:
            date, time, minutes, tag, description = cells
            datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
            minutes = int(minutes)
            if minutes <= 0:
                raise ValueError
        except ValueError:
            print(f"Skipping line {num} of {LOG_FILE.name}, can't read it: {line}", file=sys.stderr)
            continue
        records.append({
            "date": date,
            "time": time,
            "minutes": minutes,
            "tag": tag,
            "description": description.replace("\\|", "|"),
        })
    records.sort(key=lambda r: (r["date"], r["time"]))
    return records


def write_record(rec):
    """Append one record as a table row, creating the file with a header if needed."""
    text = LOG_FILE.read_text(encoding="utf-8") if LOG_FILE.exists() else ""
    description = rec["description"].replace("|", "\\|")
    row = f"| {rec['date']} | {rec['time']} | {rec['minutes']} | {rec['tag']} | {description} |\n"
    with LOG_FILE.open("a", encoding="utf-8", newline="\n") as f:
        if not text.strip():
            f.write(HEADER)
        elif not text.endswith("\n"):
            f.write("\n")
        f.write(row)


# --- Git ------------------------------------------------------------------------

def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)


def has_uncommitted_edits():
    try:
        result = git("status", "--porcelain", "--", LOG_FILE.name)
    except FileNotFoundError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def commit(message):
    """Commit only the log file, leaving anything else in the repo untouched."""
    try:
        git("add", "--", LOG_FILE.name)
        result = git("commit", "-m", message, "--", LOG_FILE.name)
    except FileNotFoundError:
        print("git is not installed, so the change was saved but not committed.")
        return
    if result.returncode != 0:
        print("git commit failed:", (result.stderr or result.stdout).strip())


# --- Commands -------------------------------------------------------------------

def parse_minutes(text):
    try:
        minutes = int(text)
    except ValueError:
        raise ValueError(f"Duration must be whole minutes, got {text!r}") from None
    if not 0 < minutes <= 24 * 60:
        raise ValueError("Duration must be between 1 and 1440 minutes")
    return minutes


def check_tag(text):
    tag = text.strip()
    if not tag or "|" in tag:
        raise ValueError("Tag can't be empty or contain |")
    return tag


def recent_tags(records):
    """Tags ordered by most recent use."""
    tags = []
    for r in reversed(records):
        if r["tag"] not in tags:
            tags.append(r["tag"])
    return tags


def ask(prompt, check, default=""):
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{prompt}{suffix}: ").strip() or default
        try:
            return check(value)
        except ValueError as e:
            print(e)


def cmd_add(args):
    records = read_records()
    if args and len(args) < 3:
        sys.exit('Usage: dw add <minutes> <tag> "<description>"   (or just: dw add)')
    if args:
        try:
            minutes = parse_minutes(args[0])
            tag = check_tag(args[1])
        except ValueError as e:
            sys.exit(str(e))
        description = " ".join(args[2:]).strip()
    else:
        tags = recent_tags(records)
        minutes = ask("Duration (min)", parse_minutes)
        if tags:
            print("Tags:", ", ".join(tags[:10]))
        tag = ask("Tag", check_tag, tags[0] if tags else "")
        description = input("Description: ").strip()

    if has_uncommitted_edits():
        commit("Manual edits")

    start = datetime.now() - timedelta(minutes=minutes)
    rec = {
        "date": start.strftime("%Y-%m-%d"),
        "time": start.strftime("%H:%M"),
        "minutes": minutes,
        "tag": tag,
        "description": description,
    }
    write_record(rec)
    commit(f"Add {minutes} min {tag}: {description}".rstrip(": "))

    done = (sum(r["minutes"] for r in records) + minutes) / 60
    left = max(0, GOAL_HOURS - done)
    print(f"Saved: {rec['date']} {rec['time']} | {minutes} min | {tag} | {description}")
    print(f"Total: {done:,.1f} h done, {left:,.1f} h left to {GOAL_HOURS:,}")


def write_data_js():
    """Export records as JSON for the browser (pages opened from disk can't read files)."""
    data = {
        "goalHours": GOAL_HOURS,
        "generated": datetime.now().isoformat(timespec="minutes"),
        "records": read_records(),
    }
    path = WEB_DIR / "data.js"
    path.write_text("window.DEEPWORK = " + json.dumps(data, ensure_ascii=False) + ";\n",
                    encoding="utf-8")
    return len(data["records"])


def cmd_stats():
    count = write_data_js()
    page = WEB_DIR / "index.html"
    webbrowser.open(page.as_uri())
    print(f"Opened {page} ({count} records)")


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    command, rest = args[0], args[1:]
    if command == "add":
        cmd_add(rest)
    elif command == "stats":
        cmd_stats()
    else:
        sys.exit(f"Unknown command: {command}\n{__doc__}")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        sys.exit("\nCancelled.")
