#!/usr/bin/env python3
"""D2 Escalation Detector for spring perspective reports.

Usage:
    python escalation.py --report <path-to-markdown>

Detection rules (ANY match → escalation_pending):
  1. YAML frontmatter has 'status: challenged'
  2. Table row where '挑战原则前提' is '是'
  3. Checked checkbox '[x] 本视角挑战了思维框架原则体系中的前提假设'
  4. Heuristic: '前提不成立' or '前提失效' within 3 lines of '思维框架原则' or 'PD-'
"""

import argparse
import re
import sys
from pathlib import Path


def parse_frontmatter(text):
    """Extract raw YAML frontmatter between --- delimiters via regex."""
    m = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    return m.group(1) if m else ''


def strip_frontmatter(text):
    """Return the body with frontmatter removed."""
    return re.sub(r'^---\s*\n.*?\n---\n?', '', text, count=1, flags=re.DOTALL)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def rule1_challenged_status(frontmatter):
    """YAML frontmatter has 'status: challenged'."""
    return bool(re.search(r'^status\s*:\s*challenged\s*$', frontmatter, re.MULTILINE))


def rule2_table_row(body):
    """Table row where cell '挑战原则前提' has value '是'."""
    for line in body.splitlines():
        line = line.strip()
        if not (line.startswith('|') and line.endswith('|')):
            continue
        if re.match(r'^\|[\s\-:]+\|$', line):
            continue  # header separator row
        cells = [c.strip() for c in line.split('|')[1:-1]]
        has_key = any('挑战原则前提' in c for c in cells)
        has_yes = any(c == '是' for c in cells)
        if has_key and has_yes:
            return True
    return False


def rule3_checked_checkbox(body):
    """Body contains exactly '[x] 本视角挑战了思维框架原则体系中的前提假设'."""
    return '[x] 本视角挑战了思维框架原则体系中的前提假设' in body


def rule4_heuristic(body):
    """'前提不成立' or '前提失效' within 3 lines of '思维框架原则' or 'PD-'."""
    lines = body.splitlines()
    trigger_lines = set()
    target_lines = set()
    for idx, line in enumerate(lines):
        if '思维框架原则' in line or 'PD-' in line:
            trigger_lines.add(idx)
        if '前提不成立' in line or '前提失效' in line:
            target_lines.add(idx)
    return any(abs(ti - tj) <= 3 for ti in trigger_lines for tj in target_lines)


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def extract_spring_statement(body):
    """Extract Spring's statement from the report body."""
    for pat in [
        r'^##?\s*Spring\'?s?[：:]\s*\n(.*?)(?=\n##?\s|\Z)',
        r'^##?\s*[视視]角陈述[：:]\s*\n(.*?)(?=\n##?\s|\Z)',
        r'^##?\s*[视視]角[申陈]述[：:]\s*\n(.*?)(?=\n##?\s|\Z)',
    ]:
        m = re.search(pat, body, re.DOTALL | re.MULTILINE)
        if m:
            return m.group(1).strip()
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', body) if p.strip()]
    return paragraphs[0] if paragraphs else '(statement not found)'


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_report(report_path, escalation, sources, statement):
    sep = '=' * 62
    print(sep)
    print('  D2 Escalation Detector')
    print(sep)
    print()
    print(f'  Report: {report_path.name}')
    print()
    if escalation:
        print('  ⚠ Status: ESCALATION PENDING')
    else:
        print('  ✓ Status: NO ESCALATION')
    print()
    if sources:
        print('  Triggered rules:')
        for s in sources:
            print(f'    • {s}')
        print()
    print('  ─' * 30)
    print()
    print('  Spring\'s statement:')
    print(f'  {statement}')
    print()
    print('  ─' * 30)
    print()
    print('  ★ Pending decision-maker judgment')
    print()
    print('    [ ] Accept — this perspective does challenge a principle premise')
    print('    [ ] Reject — this perspective does not touch principle premises')
    if escalation:
        print('    [ ] Needs discussion — further clarification required')
    else:
        print('    ⏸  No escalation triggered, no action needed')
    print()
    print('  Decision-maker notes:')
    print('  ‾' * 20)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='D2 Escalation Detector')
    parser.add_argument('--report', required=True,
                        help='Path to spring perspective report (markdown)')
    args = parser.parse_args()

    report_path = Path(args.report)
    if not report_path.exists():
        print(f'Error: report not found: {report_path}', file=sys.stderr)
        sys.exit(2)

    text = report_path.read_text(encoding='utf-8')
    frontmatter = parse_frontmatter(text)
    body = strip_frontmatter(text)

    r1 = rule1_challenged_status(frontmatter)
    r2 = rule2_table_row(body)
    r3 = rule3_checked_checkbox(body)
    r4 = rule4_heuristic(body)

    escalation = r1 or r2 or r3 or r4

    sources = []
    if r1:
        sources.append('Rule 1: frontmatter status = challenged')
    if r2:
        sources.append('Rule 2: table row 挑战原则前提 = 是')
    if r3:
        sources.append('Rule 3: checked box "本视角挑战了思维框架原则体系中的前提假设"')
    if r4:
        sources.append('Rule 4: heuristic — 前提不成立/前提失效 near 思维框架原则/PD-')

    statement = extract_spring_statement(body)
    print_report(report_path, escalation, sources, statement)

    sys.exit(0 if not escalation else 1)


if __name__ == '__main__':
    main()
