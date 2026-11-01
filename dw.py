#!/usr/bin/env python3
"""Deep work tracker.

Usage:
  dw add                           ask for each field
  dw add 90 thesis "Wrote intro"   add a record in one line
  dw stats                         open the statistics page in the browser
  dw backup                        back up all records now (.md + .xlsx)

deepwork_logs.md holds every record and is the only source of truth.
A record's time is the session's start time (now minus the duration).
To fix past records, edit deepwork_logs.md by hand.

Backup: when the first record of a new day is added, the log (every record
from the start up to the last logged day) is copied to
<DW_BACKUP_DIR>/deepwork_logs-YYYY-MM.md, one read-only file per month, plus an Excel copy
with the same name in <DW_XLSX_BACKUP_DIR>. Set both in .env (see .env.example);
default ~/deepwork-backup for both. The log itself lives at <DW_LOG_FILE>
(default: deepwork_logs.md next to dw.py).
"""
import json
import os
import re
import stat
import sys
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

import xlsx_backup

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
GOAL_HOURS = 10_000
READ_ONLY = stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH
WRITABLE = stat.S_IREAD | stat.S_IWRITE | stat.S_IRGRP | stat.S_IROTH
NO_WRITE = 0o222      # write bits: without them, files in a folder can't be created, renamed or deleted
BACKUP_NAME = re.compile(r"deepwork_logs-\d{4}-\d{2}\.(md|xlsx)(\.tmp)?")  # .tmp: left by an interrupted save


def read_env(path):
    """Read KEY=VALUE lines from a .env file. Blank lines and # comments are ignored."""
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    return values


def setting_path(name, default):
    """Path from a setting. ~ and $VARS are expanded; relative paths count from this folder,
    so dw works the same from any current directory."""
    value = ENV.get(name)
    if not value:
        return Path(default)
    return ROOT / Path(os.path.expandvars(value)).expanduser()  # ROOT / absolute = absolute


# Settings come from the environment first, then .env, then the default.
ENV = {**read_env(ROOT / ".env"), **os.environ}
BACKUP_DIR = setting_path("DW_BACKUP_DIR", Path.home() / "deepwork-backup")
XLSX_BACKUP_DIR = setting_path("DW_XLSX_BACKUP_DIR", BACKUP_DIR)
LOG_FILE = setting_path("DW_LOG_FILE", ROOT / "deepwork_logs.md")


# --- File format --------------------------------------------------------------
# Only parse_records() and write_record() know the log is a Markdown table.
# To switch formats, rewrite these two functions.

HEADER = (
    "# Deep Work Log\n"
    "\n"
    "| Date | Time | Duration | Project | Description |\n"
    "|------|------|----------|---------|-------------|\n"
)
CELL_SPLIT = re.compile(r"(?<!\\)\|")  # split on | but not on \|


def read_records():
    """Return all records from the log, oldest first. Unreadable rows are reported and skipped."""
    if not LOG_FILE.exists():
        return []
    return parse_records(LOG_FILE.read_text(encoding="utf-8"))


def parse_records(text, report=True):
    """Return the records in the log's text, oldest first."""
    records = []
    for num, line in enumerate(text.splitlines(), 1):
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
            date, time, minutes, project, description = cells
            datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
            minutes = int(minutes)
            if minutes <= 0:
                raise ValueError
        except ValueError:
            if report:
                print(f"Skipping line {num} of {LOG_FILE.name}, can't read it: {line}", file=sys.stderr)
            continue
        records.append({
            "date": date,
            "time": time,
            "minutes": minutes,
            "project": project,
            "description": description.replace("\\|", "|"),
        })
    records.sort(key=lambda r: (r["date"], r["time"]))
    return records


def one_line(text):
    """Collapse newlines, tabs and repeated spaces: a record must stay on one table row."""
    return " ".join(text.split())


def write_record(rec):
    """Append one record to the log, creating the file with a header if needed."""
    text = LOG_FILE.read_text(encoding="utf-8") if LOG_FILE.exists() else ""
    description = rec["description"].replace("|", "\\|")
    row = f"| {rec['date']} | {rec['time']} | {rec['minutes']} | {rec['project']} | {description} |\n"
    with LOG_FILE.open("a", encoding="utf-8", newline="\n") as f:
        if not text.strip():
            f.write(HEADER)
        elif not text.endswith("\n"):
            f.write("\n")
        f.write(row)


# --- Monthly backup of the log -------------------------------------------------
# Taken when the first record of a new day is added. At that moment the log holds
# every record from the start up to the last logged day, so the backup never
# contains today's (possibly unfinished) day. The file is named after the month of
# its latest record: the current month's file is replaced on each new day, and once
# the month is over its file stays final. Each backup also gets an Excel copy with the same
# name (see xlsx_backup.py). Files are read-only and the folders are locked, so backups
# can't be edited or deleted by accident.

def save_locked(folder, name, data):
    """Write data to folder/name as a read-only file, unlocking the folder only while saving.

    The folder must hold nothing but backups, because it gets locked as a whole.
    The new file is written next to the old one and then swapped in, so a failed
    write (e.g. a full disk) leaves the previous backup intact.
    """
    path = folder / name
    folder.mkdir(parents=True, exist_ok=True)
    others = [f.name for f in folder.iterdir()
              if not BACKUP_NAME.fullmatch(f.name) and not f.name.startswith(".")]  # .git is fine
    if others:
        raise OSError(f"{folder} holds other files too ({', '.join(sorted(others)[:3])}), "
                      "so it won't be locked. Point the backup setting in .env to a folder of its own.")
    locked_mode = stat.S_IMODE(folder.stat().st_mode) & ~NO_WRITE
    folder.chmod(locked_mode | stat.S_IWUSR)
    tmp = folder / (name + ".tmp")
    try:
        tmp.write_bytes(data)
        if tmp.read_bytes() != data:
            raise OSError(f"{tmp} doesn't match what was written")
        tmp.chmod(READ_ONLY)
        if path.exists():
            path.chmod(WRITABLE)  # some systems refuse to replace a read-only file
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.chmod(WRITABLE)
            tmp.unlink()
        folder.chmod(locked_mode)
    return path


def backup(latest_date):
    """Save the log as deepwork_logs-YYYY-MM.md, plus an Excel copy with the same name.
    Returns True if the .md backup was saved.

    Reports errors instead of raising, so a failed backup never stops `dw add`.
    """
    name = f"deepwork_logs-{latest_date[:7]}"
    try:
        data = LOG_FILE.read_bytes()
        path = save_locked(BACKUP_DIR, name + ".md", data)
        print(f"Backup: {path} (records up to {latest_date})")
    except OSError as e:
        print(f"Backup failed: {e}")
        return False
    try:
        records = parse_records(data.decode("utf-8"), report=False)
        path = save_locked(XLSX_BACKUP_DIR, name + ".xlsx", xlsx_backup.records_to_xlsx(records))
        print(f"Backup: {path}")
    except Exception as e:  # the .md backup above is what matters; never stop dw add here
        print(f"Excel backup failed: {e}")
    return True


# --- Commands -------------------------------------------------------------------

def parse_minutes(text):
    try:
        minutes = int(text)
    except ValueError:
        raise ValueError(f"Duration must be whole minutes, got {text!r}") from None
    if not 0 < minutes <= 24 * 60:
        raise ValueError("Duration must be between 1 and 1440 minutes")
    return minutes


def check_log_file(creating):
    """Make sure LOG_FILE is where the settings say. A missing log usually means a wrong
    path in .env, so `dw add` asks before starting a new one and other commands stop."""
    if LOG_FILE.exists():
        return
    hint = "Check DW_LOG_FILE in .env." if ENV.get("DW_LOG_FILE") else "Set DW_LOG_FILE in .env if it lives elsewhere."
    if not LOG_FILE.parent.is_dir():
        sys.exit(f"Log folder doesn't exist: {LOG_FILE.parent}\n{hint}")
    if not creating:
        sys.exit(f"No log at {LOG_FILE}\n{hint}")
    print(f"No log at {LOG_FILE}\n{hint}")
    if input("Start a new, empty log there? [y/N]: ").strip().lower() not in ("y", "yes"):
        sys.exit("Nothing saved.")


def check_project(text):
    project = one_line(text)
    if not project or "|" in project:
        raise ValueError("Project can't be empty or contain |")
    return project


def recent_projects(records):
    """Projects ordered by most recent use."""
    projects = []
    for r in reversed(records):
        if r["project"] not in projects:
            projects.append(r["project"])
    return projects


def ask(prompt, check, default=""):
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{prompt}{suffix}: ").strip() or default
        try:
            return check(value)
        except ValueError as e:
            print(e)


def cmd_add(args):
    if args and len(args) < 3:
        sys.exit('Usage: dw add <minutes> <project> "<description>"   (or just: dw add)')
    check_log_file(creating=True)
    records = read_records()
    if args:
        try:
            minutes = parse_minutes(args[0])
            project = check_project(args[1])
        except ValueError as e:
            sys.exit(str(e))
        description = one_line(" ".join(args[2:]))
    else:
        projects = recent_projects(records)
        minutes = ask("Duration (min)", parse_minutes)
        if projects:
            print("Projects:", ", ".join(projects[:10]))
        project = ask("Project", check_project, projects[0] if projects else "")
        description = one_line(input("Description: "))

    start = datetime.now() - timedelta(minutes=minutes)
    rec = {
        "date": start.strftime("%Y-%m-%d"),
        "time": start.strftime("%H:%M"),
        "minutes": minutes,
        "project": project,
        "description": description,
    }
    latest_date = max((r["date"] for r in records), default=None)
    if latest_date and rec["date"] > latest_date:
        backup(latest_date)  # first record of a new day: save everything before it
    write_record(rec)

    done = (sum(r["minutes"] for r in records) + minutes) / 60
    left = max(0, GOAL_HOURS - done)
    print(f"Saved: {rec['date']} {rec['time']} | {minutes} min | {project} | {description}")
    print(f"Total: {done:,.1f} h done, {left:,.1f} h left to {GOAL_HOURS:,}")


def write_data_js(records):
    """Export records as JSON for the browser (pages opened from disk can't read files)."""
    data = {
        "goalHours": GOAL_HOURS,
        "generated": datetime.now().isoformat(timespec="minutes"),
        "records": records,
    }
    path = WEB_DIR / "data.js"
    path.write_text("window.DEEPWORK = " + json.dumps(data, ensure_ascii=False) + ";\n",
                    encoding="utf-8")


def cmd_stats():
    check_log_file(creating=False)
    records = read_records()
    write_data_js(records)
    page = WEB_DIR / "index.html"
    webbrowser.open(page.as_uri())
    print(f"Opened {page} ({len(records)} records)")


def cmd_backup():
    check_log_file(creating=False)
    records = read_records()
    if not records:
        print("Nothing to back up yet.")
        return
    if not backup(records[-1]["date"]):  # whole log, named after the newest record's month
        sys.exit(1)


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
    elif command == "backup":
        cmd_backup()
    else:
        sys.exit(f"Unknown command: {command}\n{__doc__}")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        sys.exit("\nCancelled.")
