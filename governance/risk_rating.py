#!/usr/bin/env python3
"""Decision Risk Rating — three-dimension scoring for technical decisions.

Dimensions (each scored 1–3):
  A  Reversibility  (weight 0.4): 1=fully reversible, 2=costly rollback, 3=irreversible
  B  Impact scope   (weight 0.35): 1=local, 2=system-wide, 3=architectural
  C  Novelty        (weight 0.25): 1=known path, 2=analogous, 3=uncharted

  Risk_Score = round(A*0.4 + B*0.35 + C*0.25, 1)

Tiers:
  Low    (1.0–1.6): simplified review (principle check only)
  Medium (1.7–2.3): standard (principle + perspective report)
  High   (2.4–3.0): full (principle + perspective + premise test + escalation)
"""

import argparse
import sys

WEIGHTS = {"A": 0.4, "B": 0.35, "C": 0.25}
LOW_MAX = 1.6
MEDIUM_MAX = 2.3


def heuristic_scoring(text: str) -> dict:
    """Heuristic scoring from decision text."""
    scores = {"A": 1, "B": 1, "C": 1}

    # Reversibility boost
    if any(kw in text for kw in
           ["replace", "migrate", "rewrite", "redo", "substitute", "swap"]):
        scores["A"] = 3
    elif any(kw in text for kw in
             ["modify", "update", "upgrade", "refactor", "migration"]):
        scores["A"] = 2

    # Impact boost
    if any(kw in text for kw in
           ["architecture", "core", "entire", "all", "system", "platform", "framework"]):
        scores["B"] = 3
    elif any(kw in text for kw in
             ["module", "component", "service", "interface", "feature", "flow"]):
        scores["B"] = 2

    # Novelty boost
    if any(kw in text for kw in
           ["replace", "migrate", "refactor", "architecture", "switch", "upgrade", "rewrite"]):
        scores["C"] = 3
    elif any(kw in text for kw in ["new", "explore", "trial", "introduce", "integrate"]):
        scores["C"] = 2

    for k in scores:
        scores[k] = min(scores[k], 3)
    return scores


def compute_score(a: int, b: int, c: int) -> float:
    return round(a * WEIGHTS["A"] + b * WEIGHTS["B"] + c * WEIGHTS["C"], 1)


def describe_tier(score: float) -> str:
    if score <= LOW_MAX:
        return "Low"
    if score <= MEDIUM_MAX:
        return "Medium"
    return "High"


def tier_detail(tier: str) -> str:
    details = {
        "Low": "simplified review (principle check only)",
        "Medium": "standard (principle + perspective report)",
        "High": "full (principle + perspective + premise test + escalation)",
    }
    return details[tier]


def clamp(n: int) -> int:
    return max(1, min(3, n))


def parse_override(raw: str):
    """Parse a single --override value like ``A=2``."""
    raw = raw.strip()
    if "=" not in raw:
        raise ValueError(f"Invalid override format: {raw!r} (expected DIM=score)")
    dim, _, val = raw.partition("=")
    dim = dim.upper()
    if dim not in WEIGHTS:
        raise ValueError(f"Unknown dimension {dim!r} — use A, B, or C")
    return dim, clamp(int(val))


# ── Modes ──────────────────────────────────────────────────────────────


def cmd_decision(text: str, overrides: dict[str, int]) -> None:
    """Quick rating using heuristic scoring."""
    h = heuristic_scoring(text)
    a = overrides.get("A", h["A"])
    b = overrides.get("B", h["B"])
    c = overrides.get("C", h["C"])
    score = compute_score(a, b, c)
    tier = describe_tier(score)
    print(f"Decision: {text}")
    print()
    print(f"  A (Reversibility) = {a}  (weight 0.4)")
    print(f"  B (Impact scope)  = {b}  (weight 0.35)")
    print(f"  C (Novelty)       = {c}  (weight 0.25)")
    print(f"  ─────────────────────────")
    print(f"  Risk Score = {score}")
    print(f"  Tier: {tier} — {tier_detail(tier)}")


def cmd_interactive(overrides: dict[str, int]) -> None:
    def ask(prompt: str, dim: str) -> int:
        if dim in overrides:
            val = overrides[dim]
            print(f"{prompt} [{val}] (overridden)")
            return val
        while True:
            try:
                val = int(input(f"{prompt} "))
                if 1 <= val <= 3:
                    return val
                print("  Enter 1, 2, or 3.")
            except ValueError:
                print("  Enter a number (1, 2, or 3).")

    a = ask("A: Reversibility — 1=fully reversible  2=costly rollback  3=irreversible  [1-3]:", "A")
    b = ask("B: Impact scope  — 1=local  2=system-wide  3=architectural           [1-3]:", "B")
    c = ask("C: Novelty       — 1=known path  2=analogous  3=uncharted            [1-3]:", "C")

    score = compute_score(a, b, c)
    tier = describe_tier(score)
    print()
    print(f"  A (Reversibility) = {a}  (weight 0.4)")
    print(f"  B (Impact scope)  = {b}  (weight 0.35)")
    print(f"  C (Novelty)       = {c}  (weight 0.25)")
    print(f"  ─────────────────────────")
    print(f"  Risk Score = {score}")
    print(f"  Tier: {tier} — {tier_detail(tier)}")


def cmd_examples() -> None:
    rows = [
        ("Change UI button color",           1, 1, 1),
        ("Update copy in help dialog",        2, 1, 1),
        ("Add new REST endpoint",             2, 2, 1),
        ("Refactor cache layer",              2, 2, 2),
        ("Replace ORM with raw SQL",          2, 2, 3),
        ("Migrate auth to OIDC",              2, 3, 2),
        ("Upgrade database major version",    3, 2, 2),
        ("Rewrite core routing engine",       3, 3, 3),
    ]
    header = f"{'Decision':<36} {'A':>2} {'B':>2} {'C':>2}  {'Score':>5}  {'Tier':<8}  Notes"
    print(header)
    print("─" * len(header))
    for text, a, b, c in rows:
        score = compute_score(a, b, c)
        tier = describe_tier(score)
        note = tier_detail(tier)
        print(f"{text:<36} {a:>2} {b:>2} {c:>2}  {score:>5.1f}  {tier:<8}  {note}")


# ── CLI ────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Rate technical decision risk on three dimensions.",
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument("--decision", metavar="TEXT",
                       help="Quick rating with keyword-based novelty boost")
    group.add_argument("--interactive", action="store_true",
                       help="Score via interactive prompts for A, B, C")
    group.add_argument("--examples", action="store_true",
                       help="Print example table")
    p.add_argument("--override", action="append", metavar="DIM=VAL",
                   help="Override a dimension score (e.g. A=2). Repeatable.")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    overrides: dict[str, int] = {}
    if args.override:
        for ov in args.override:
            dim, val = parse_override(ov)
            overrides[dim] = val

    if args.examples:
        cmd_examples()
    elif args.interactive:
        cmd_interactive(overrides)
    elif args.decision:
        cmd_decision(args.decision, overrides)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
