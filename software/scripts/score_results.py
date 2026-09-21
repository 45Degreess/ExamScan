"""
Read one or more graded results CSVs (batch_eval_cover_pages.py's
results.csv, after exporting from contact_sheet.html with the four
*_correct columns filled in) and print per-batch accuracy plus
confidence-tier / intervention-rate breakdowns.

Ungraded rows (blank *_correct cells) are skipped from accuracy math and
counted separately, not treated as incorrect.

Usage: python3 score_results.py results_graded.csv [more.csv ...]
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

GRADED_FIELDS = ["framing_correct", "student_number_correct", "course_code_correct", "mark_correct"]

REQUIRED_COLUMNS = {
    "script_id", "batch", "emplid_confidence", "course_code_confidence",
    "mark_candidates", *GRADED_FIELDS,
}

FIELD_LABELS = {
    "framing_correct": "framing_correct",
    "student_number_correct": "student_number_correct",
    "course_code_correct": "course_code_correct",
    "mark_correct": "mark_correct",
}

# graded field -> confidence-column field it's scored against (framing has none)
CONFIDENCE_SOURCE = {
    "student_number_correct": "emplid_confidence",
    "course_code_correct": "course_code_confidence",
}


def load_rows(paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        with open(path, newline="") as fh:
            reader = csv.DictReader(fh)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                sys.exit(f"{path}: missing required column(s): {sorted(missing)}")
            rows.extend(reader)
    return rows


def is_graded(value: str) -> bool:
    return value.strip() in ("TRUE", "FALSE")


def is_correct(value: str) -> bool:
    return value.strip() == "TRUE"


def parse_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first_mark_candidate_confidence(raw: str) -> float | None:
    if not raw:
        return None
    first = raw.split(";", 1)[0]
    _, _, conf = first.partition(":")
    return parse_float(conf)


def confidence_tier(c: float) -> str:
    if c >= 0.8:
        return "green"
    if c >= 0.5:
        return "yellow"
    return "red"


def group_by_batch(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["batch"], []).append(row)
    return grouped


def compute_accuracy(rows: list[dict], field: str) -> dict:
    graded = [r for r in rows if is_graded(r[field])]
    correct = sum(1 for r in graded if is_correct(r[field]))
    skipped = len(rows) - len(graded)
    pct = (correct / len(graded) * 100) if graded else 0.0
    return {"total": len(rows), "graded": len(graded), "correct": correct, "pct": pct, "skipped": skipped}


def compute_confidence_tiers(rows: list[dict], confidence_fn) -> dict:
    counts = {"red": 0, "yellow": 0, "green": 0}
    excluded = 0
    for row in rows:
        c = confidence_fn(row)
        if c is None:
            excluded += 1
            continue
        counts[confidence_tier(c)] += 1
    total = sum(counts.values())
    intervention_rate = (counts["red"] / total * 100) if total else 0.0
    return {**counts, "total_with_confidence": total, "excluded": excluded, "intervention_rate": intervention_rate}


def confidence_fn_for(field: str):
    if field in CONFIDENCE_SOURCE:
        column = CONFIDENCE_SOURCE[field]
        return lambda row: parse_float(row[column])
    if field == "mark_correct":
        return lambda row: first_mark_candidate_confidence(row["mark_candidates"])
    return None


def print_accuracy_table(rows: list[dict]) -> None:
    print("Accuracy:")
    for field in GRADED_FIELDS:
        acc = compute_accuracy(rows, field)
        print(
            f"  {FIELD_LABELS[field]:<24} graded {acc['graded']:>3}/{acc['total']:<3}"
            f"   correct {acc['correct']:>3}   accuracy {acc['pct']:5.1f}%"
            f"   ({acc['skipped']} ungraded)"
        )


def print_confidence_tables(rows: list[dict]) -> None:
    for field in GRADED_FIELDS:
        fn = confidence_fn_for(field)
        if fn is None:
            continue
        tiers = compute_confidence_tiers(rows, fn)
        note = f"   ({tiers['excluded']} rows had no confidence value — excluded)" if tiers["excluded"] else ""
        print(
            f"Confidence tiers ({FIELD_LABELS[field]}):\n"
            f"  red (<50%) {tiers['red']:>3}   yellow (50-80%) {tiers['yellow']:>3}"
            f"   green (>80%) {tiers['green']:>3}   intervention rate {tiers['intervention_rate']:5.1f}%{note}"
        )


def print_section(title: str, rows: list[dict]) -> None:
    print(f"\n=== {title} ({len(rows)} scripts) ===")
    print_accuracy_table(rows)
    print()
    print_confidence_tables(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_paths", nargs="+", type=Path)
    args = parser.parse_args()

    rows = load_rows(args.csv_paths)
    if not rows:
        sys.exit("No rows found in the given file(s).")

    batches = group_by_batch(rows)
    for batch_name, batch_rows in batches.items():
        print_section(batch_name, batch_rows)

    if len(batches) > 1:
        print_section("TOTAL", rows)


if __name__ == "__main__":
    main()
