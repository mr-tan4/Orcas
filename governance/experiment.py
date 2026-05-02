#!/usr/bin/env python3
"""Experiment lifecycle management — hypothesis → experiment → verification → distillation → ingestion.

Usage:
  python experiment.py new --title "..." --hypothesis "..."
  python experiment.py list [--status hypothesis|experiment|verified]
  python experiment.py show EXP-YYYYMMDD-NNN
  python experiment.py status EXP-YYYYMMDD-NNN
  python experiment.py update EXP-YYYYMMDD-NNN --status verified

Output: experiments/EXP-YYYYMMDD-NNN.md
"""

import argparse
import datetime
import json
import os
import re
import sys

EXPERIMENTS_DIR = "./experiments"

TEMPLATE = """---
experiment_id: {exp_id}
title: {title}
hypothesis: {hypothesis}
date: {date}
status: {status}
tags: {tags}
---

## Hypothesis

**I believe**: {hypothesis}

**If the hypothesis holds, I expect to observe**:

**If the hypothesis fails, I expect to observe**:

## Experiment Design

**Task**:
**Tools**:
**Constraints**:
**Definition of success**:

## Experiment Log

**Actual process**:

**Deviations**:

**Unexpected findings**:

## Verification

**Conclusion**:
**Evidence**:

| Original hypothesis | Holds? | Actual observation | Deviation analysis |
|---------------------|--------|-------------------|-------------------|
| | | | |

## Distillation

**Pattern**:
**Applicable conditions**:
**Boundaries**:
**Methodology contribution**:

## Ingestion

- [ ] KG: create experiment entity
- [ ] KG: build hypothesis→experiment→finding→pattern relation chain
- [ ] Methodology: update methodology document
"""


# ── Minimal YAML frontmatter helpers (stdlib only) ────────────────────


def _parse_frontmatter(text):
    """Parse minimal YAML frontmatter from markdown file content.

    Handles: simple k: v, quoted strings, inline lists, folded scalars (>).
    This is not a full YAML parser — sufficient for experiment metadata.
    """
    m = re.match(r'^---\n(.*?)\n---', text, re.DOTALL)
    if not m:
        return {}
    raw = m.group(1)

    result = {}
    current_key = None
    current_lines = []
    in_folded = False

    for line in raw.split('\n'):
        # New key-value pair (non-indented)
        kv_match = re.match(r'^([\w_]+)\s*:\s*(.*)', line)
        if kv_match and not line.startswith(' '):
            # Flush pending folded value
            if current_key and in_folded and current_lines:
                result[current_key] = ' '.join(
                    v for v in current_lines if v)
                current_lines = []
                in_folded = False
            elif current_key and current_lines:
                result[current_key] = ' '.join(
                    v.strip() for v in current_lines if v.strip())
                current_lines = []

            current_key = kv_match.group(1)
            value = kv_match.group(2).strip()

            if value == '>':
                in_folded = True
            elif value.startswith('[') and value.endswith(']'):
                try:
                    result[current_key] = json.loads(value)
                except json.JSONDecodeError:
                    result[current_key] = [v.strip().strip('"\'')
                                           for v in value[1:-1].split(',')]
            elif value == '' or value == 'null':
                result[current_key] = ''
            else:
                result[current_key] = value.strip('"\'')
        elif current_key and (line.startswith(' ') or line.startswith('\t')):
            current_lines.append(line.strip())

    # Flush last value
    if current_key and in_folded and current_lines:
        result[current_key] = ' '.join(v for v in current_lines if v)
    elif current_key and current_lines:
        result[current_key] = ' '.join(
            v.strip() for v in current_lines if v.strip())

    return result


def _format_frontmatter(fm):
    """Format dict as YAML frontmatter string."""
    lines = []
    for key, value in fm.items():
        if isinstance(value, list):
            items = json.dumps(value, ensure_ascii=False)
            lines.append(f"{key}: {items}")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif value is None:
            lines.append(f"{key}: null")
        else:
            lines.append(f"{key}: {value}")
    return '\n'.join(lines) + '\n'


def load_frontmatter(path):
    """Parse YAML frontmatter from experiment markdown file."""
    with open(path) as f:
        content = f.read()
    return _parse_frontmatter(content)


def write_file(path, fm, body):
    """Write frontmatter dict + body to markdown file."""
    fm_str = _format_frontmatter(fm)
    content = f"---\n{fm_str}---\n{body}"
    with open(path, 'w') as f:
        f.write(content)


# ── Experiment ID generation ──────────────────────────────────────────


def next_id(experiments_dir):
    """Generate next experiment ID: EXP-YYYYMMDD-NNN."""
    today = datetime.date.today().strftime("%Y%m%d")
    os.makedirs(experiments_dir, exist_ok=True)
    existing = [f for f in os.listdir(experiments_dir)
                if f.startswith(f"EXP-{today}")]
    if not existing:
        return f"EXP-{today}-001"
    nums = []
    for f in existing:
        m = re.match(rf'EXP-{today}-(\d+)\.md', f)
        if m:
            nums.append(int(m.group(1)))
    return f"EXP-{today}-{max(nums)+1:03d}"


# ── Commands ──────────────────────────────────────────────────────────


def cmd_new(args, experiments_dir):
    exp_id = next_id(experiments_dir)
    date = datetime.date.today().strftime("%Y-%m-%d")
    tags = args.tags or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]

    content = TEMPLATE.format(
        exp_id=exp_id,
        title=args.title,
        hypothesis=args.hypothesis,
        date=date,
        status="hypothesis",
        tags=json.dumps(tags),
    )
    path = os.path.join(experiments_dir, f"{exp_id}.md")
    os.makedirs(experiments_dir, exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)
    print(f"Created experiment: {exp_id}")
    print(f"  File: {path}")
    print(f"  Status: hypothesis")
    return exp_id


def cmd_list(args, experiments_dir):
    if not os.path.exists(experiments_dir):
        print("No experiments found")
        return
    files = sorted(
        [f for f in os.listdir(experiments_dir) if f.endswith('.md')],
        reverse=True)
    if not files:
        print("No experiments found")
        return
    for fname in files:
        path = os.path.join(experiments_dir, fname)
        fm = load_frontmatter(path)
        status = fm.get('status', 'unknown')
        if args.status and status != args.status:
            continue
        emoji = {"hypothesis": "\U0001f4dd", "experiment": "\U0001f52c",
                 "verified": "✅", "extracted": "\U0001f4a1",
                 "ingested": "\U0001f4da", "refuted": "❌",
                 "partial": "⚠️"}
        e = emoji.get(status, "❓")
        print(f"  {e} {fm.get('experiment_id', fname)} [{status}] "
              f"{fm.get('title', '')}")


def cmd_show(args, experiments_dir):
    path = os.path.join(experiments_dir, f"{args.experiment_id}.md")
    if not os.path.exists(path):
        print(f"Experiment {args.experiment_id} not found")
        return
    with open(path) as f:
        print(f.read())


def cmd_status(args, experiments_dir):
    path = os.path.join(experiments_dir, f"{args.experiment_id}.md")
    if not os.path.exists(path):
        print(f"Experiment {args.experiment_id} not found")
        return
    fm = load_frontmatter(path)
    lifecycle = ["hypothesis", "experiment", "verified",
                 "extracted", "ingested"]
    current = fm.get('status', 'unknown')
    progress = []
    for s in lifecycle:
        if s == current:
            progress.append(f"▶ {s}")
        elif (current in lifecycle
              and lifecycle.index(s) < lifecycle.index(current)):
            progress.append(f"✓ {s}")
        else:
            progress.append(f"○ {s}")
    print(f"  {fm.get('experiment_id')}: {fm.get('title')}")
    print(f"  Status: {current}")
    print(f"  Progress: {' → '.join(progress)}")
    print(f"  Date: {fm.get('date')}")
    print(f"  Tags: {fm.get('tags', [])}")


def cmd_update(args, experiments_dir):
    """Update experiment status."""
    exp_id = args.experiment_id
    path = os.path.join(experiments_dir, f"{exp_id}.md")
    if not os.path.exists(path):
        print(f"Experiment {exp_id} not found")
        return
    with open(path) as f:
        content = f.read()

    fm = load_frontmatter(path)
    old_status = fm.get('status', 'unknown')

    if args.status:
        fm['status'] = args.status

    m = re.match(r'^---\n.*?\n---\n(.*)', content, re.DOTALL)
    if not m:
        print("Cannot parse file structure")
        return
    body = m.group(1)

    write_file(path, fm, body)

    emoji = {"hypothesis": "\U0001f4dd", "experiment": "\U0001f52c",
             "verified": "✅", "extracted": "\U0001f4a1",
             "ingested": "\U0001f4da", "refuted": "❌",
             "partial": "⚠️"}
    e_new = emoji.get(args.status, "→")
    e_old = emoji.get(old_status, "?")
    print(f"  {e_old} [{old_status}] → {e_new} [{args.status}] {exp_id}")


# ── CLI ───────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Experiment lifecycle management")
    parser.add_argument("--dir", default=EXPERIMENTS_DIR,
                        help="Experiments directory (default: ./experiments)")
    sub = parser.add_subparsers(dest="cmd")

    # new
    p_new = sub.add_parser("new", help="Create new experiment (hypothesis phase)")
    p_new.add_argument("--title", required=True)
    p_new.add_argument("--hypothesis", required=True)
    p_new.add_argument("--tags")

    # list
    p_list = sub.add_parser("list", help="List all experiments")
    p_list.add_argument("--status")

    # show
    p_show = sub.add_parser("show", help="Show experiment details")
    p_show.add_argument("experiment_id")

    # status
    p_status = sub.add_parser("status", help="Show experiment status and progress")
    p_status.add_argument("experiment_id")

    # update
    p_update = sub.add_parser("update", help="Update experiment status")
    p_update.add_argument("experiment_id")
    p_update.add_argument("--status", required=True,
                          choices=["hypothesis", "experiment", "verified",
                                   "extracted", "ingested", "refuted",
                                   "partial"])

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return

    experiments_dir = os.path.expanduser(args.dir)

    {
        "new": lambda: cmd_new(args, experiments_dir),
        "list": lambda: cmd_list(args, experiments_dir),
        "show": lambda: cmd_show(args, experiments_dir),
        "status": lambda: cmd_status(args, experiments_dir),
        "update": lambda: cmd_update(args, experiments_dir),
    }[args.cmd]()


if __name__ == "__main__":
    main()
