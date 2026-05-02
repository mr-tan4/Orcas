#!/usr/bin/env python3
"""Schema compliance audit — governance knowledge graph health check.

Checks:
  1. Personal settlement zero co_occurrence
  2. judgment entity author field distribution
  3. Personal settlement entity settlement marker consistency
  4. Shadow entity connection integrity
  5. Challenges relation target compliance

Usage:
    python3 audit.py                     # Print audit report
    python3 audit.py --fix               # Auto-fix remediable items
    python3 audit.py --db /path/to.db    # Use custom DB path
"""
import sqlite3
import sys
import os
from collections import Counter
from datetime import datetime

DEFAULT_DB = os.path.expanduser("~/.orcas/knowledge_graph.db")


def check_zero_co_occurrence(conn):
    """Check 1: personal settlement has zero co_occurrence."""
    count = conn.execute(
        "SELECT COUNT(*) FROM relations WHERE settlement='personal' AND relation_type='co_occurrence'"
    ).fetchone()[0]
    return {"check": "zero co_occurrence", "status": "✅" if count == 0 else "⚠️",
            "detail": f"{count} rows"}


def check_judgment_authors(conn):
    """Check 2: distribution of judgment entity authors."""
    rows = conn.execute(
        "SELECT author, COUNT(*) FROM entities WHERE type='judgment' GROUP BY author"
    ).fetchall()
    total = sum(c for _, c in rows)
    detail = dict(rows) if rows else {"(no judgment entities)": 0}
    status = "✅" if total > 0 else "⚠️"
    return {"check": "judgment.author distribution", "status": status,
            "detail": f"{total} total: {dict(rows)}"}


def check_settlement_consistency(conn):
    """Check 3: settlement markers consistent — no NULLs or illegal values."""
    nulls = conn.execute(
        "SELECT COUNT(*) FROM entities WHERE settlement IS NULL OR settlement = ''"
    ).fetchone()[0]
    unknown = conn.execute(
        "SELECT COUNT(*) FROM entities WHERE settlement NOT IN ('personal', 'public', 'personal_shadow')"
    ).fetchone()[0]

    status = "✅"
    issues = []
    if nulls > 0:
        issues.append(f"{nulls} NULL values")
        status = "⚠️"
    if unknown > 0:
        issues.append(f"{unknown} illegal values")
        status = "⚠️"
    return {"check": "settlement marker consistency", "status": status,
            "detail": "; ".join(issues) if issues else "all correct"}


def check_shadow_entities(conn):
    """Check 4: shadow entity connection integrity."""
    shadows = conn.execute(
        "SELECT COUNT(*) FROM entities WHERE settlement='personal_shadow'"
    ).fetchone()[0]
    if shadows == 0:
        return {"check": "shadow entity connections", "status": "ℹ️",
                "detail": "no shadow entities (none triggered)"}

    missing = conn.execute("""
        SELECT e.id, e.name FROM entities e
        WHERE e.settlement='personal_shadow'
        AND e.id NOT IN (
            SELECT source_id FROM relations WHERE relation_type='corresponds_to'
            UNION
            SELECT target_id FROM relations WHERE relation_type='corresponds_to'
        )
    """).fetchall()

    status = "✅" if not missing else "⚠️"
    missing_msg = f", {len(missing)} missing corresponds_to edges" if missing else ", all connected"
    return {"check": "shadow entity connections", "status": status,
            "detail": f"{shadows} shadow entities{missing_msg}"}


def check_challenges_target(conn):
    """Check 5: challenges must not target judgments authored by Spring."""
    violations = conn.execute("""
        SELECT r.id, r.source_id, e.author FROM relations r
        JOIN entities e ON r.target_id = e.id
        WHERE r.relation_type='challenges' AND r.settlement='personal'
        AND e.author = 'spring'
    """).fetchall()

    status = "✅" if not violations else "⚠️"
    detail = f"{len(violations)} violations" if violations else "all compliant"
    return {"check": "challenges target compliance", "status": status, "detail": detail}


def fix_challenges_target(conn):
    """Remove challenges relations targeting Spring's judgments."""
    violations = conn.execute("""
        SELECT r.id FROM relations r
        JOIN entities e ON r.target_id = e.id
        WHERE r.relation_type='challenges' AND r.settlement='personal'
        AND e.author = 'spring'
    """).fetchall()
    for (rid,) in violations:
        conn.execute("DELETE FROM relations WHERE id=?", (rid,))
    return len(violations)


def main():
    db_path = DEFAULT_DB
    auto_fix = False
    dry_run = False

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--db" and i + 1 < len(sys.argv):
            db_path = os.path.expanduser(sys.argv[i + 1])
            i += 2
        elif arg in ("--fix", "--auto-fix"):
            auto_fix = True
            i += 1
        elif arg == "--dry-run":
            dry_run = True
            i += 1
        else:
            i += 1

    print("=" * 60)
    print(f"Governance Schema Compliance Audit")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"DB: {db_path}")
    print("=" * 60)

    conn = sqlite3.connect(db_path)

    checks = [
        check_zero_co_occurrence,
        check_judgment_authors,
        check_settlement_consistency,
        check_shadow_entities,
        check_challenges_target,
    ]

    print(f"\n{'Check':<30} {'Status':<8} {'Detail'}")
    print("-" * 60)

    all_pass = True
    for fn in checks:
        result = fn(conn)
        print(f"{result['check']:<30} {result['status']:<8} {result['detail']}")
        if '⚠️' in result['status']:
            all_pass = False

    if auto_fix and not dry_run:
        print(f"\n--- Auto-fix ---")
        fixed = fix_challenges_target(conn)
        if fixed > 0:
            conn.commit()
            print(f"  Removed {fixed} challenges targeting Spring judgments")
        else:
            print("  Nothing to fix")

    print(f"\nConclusion: {'All checks passed' if all_pass else 'Issues found requiring attention'}")

    if not all_pass and auto_fix:
        print("  Auto-fix applied. Re-run audit to confirm.")

    conn.close()


if __name__ == "__main__":
    main()
