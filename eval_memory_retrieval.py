#!/usr/bin/env python3
"""Run Local Memory retrieval eval cases."""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import MEMORY_DIR, MEMORY_INDEX_PATH
from memory_store import MemoryStore, memory_to_response


PRIVATE_CASES = Path("eval_cases/local/scheduled_retrieval_eval_cases.json")
EXAMPLE_CASES = Path("eval_cases/scheduled_retrieval_eval_cases.example.json")


@dataclass
class EvalResult:
    case_id: str
    passed: bool
    failures: list[str]
    hits: list[dict[str, Any]]


def text_contains_all(text: str, terms: list[str]) -> bool:
    lower = text.lower()
    return all(term.lower() in lower for term in terms)


def text_contains_any(text: str, terms: list[str]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def run_retrieval_case(store: MemoryStore, case: dict[str, Any], default_top_k: int) -> EvalResult:
    top_k = int(case.get("top_k") or default_top_k)
    results = store.search(
        case["query"],
        project=case.get("project"),
        category=case.get("category"),
        source=case.get("source"),
        since=case.get("since"),
        limit=top_k,
    )
    hits = [memory_to_response(memory, score) for memory, score in results]
    hit_ids = {hit["id"] for hit in hits}
    hit_projects = [hit.get("metadata", {}).get("project") for hit in hits]
    hit_categories = {hit.get("metadata", {}).get("category") for hit in hits}
    combined_text = "\n".join(hit.get("memory", "") for hit in hits)

    failures: list[str] = []
    expected_ids = set(case.get("expected_ids_any", []))
    if expected_ids and not (expected_ids & hit_ids):
        failures.append(f"missing expected id; expected any of {sorted(expected_ids)}, got {sorted(hit_ids)}")

    required_project = case.get("required_project") or case.get("project")
    if required_project and any(project != required_project for project in hit_projects):
        failures.append(f"project scope violation; expected only {required_project}, got {hit_projects}")

    forbidden_projects = set(case.get("forbidden_projects", []))
    forbidden_seen = forbidden_projects & set(project for project in hit_projects if project)
    if forbidden_seen:
        failures.append(f"forbidden projects returned: {sorted(forbidden_seen)}")

    required_categories = set(case.get("required_category_any", []))
    if required_categories and not (required_categories & hit_categories):
        failures.append(
            f"missing required category; expected any of {sorted(required_categories)}, got {sorted(hit_categories)}"
        )

    terms_all = case.get("required_terms_all", [])
    if terms_all and not text_contains_all(combined_text, terms_all):
        failures.append(f"missing required terms: {terms_all}")

    terms_any = case.get("required_terms_any", [])
    if terms_any and not text_contains_any(combined_text, terms_any):
        failures.append(f"missing any required term from: {terms_any}")

    if not hits:
        failures.append("no hits returned")

    return EvalResult(
        case_id=case["id"],
        passed=not failures,
        failures=failures,
        hits=hits,
    )


def run_static_check(check: dict[str, Any]) -> EvalResult:
    path = Path(check["file"])
    text = path.read_text(encoding="utf-8")
    failures: list[str] = []
    terms_all = check.get("required_terms_all", [])
    if terms_all and not text_contains_all(text, terms_all):
        missing = [term for term in terms_all if term.lower() not in text.lower()]
        failures.append(f"missing required terms in {path}: {missing}")
    terms_any = check.get("required_terms_any", [])
    if terms_any and not text_contains_any(text, terms_any):
        failures.append(f"missing any required term in {path}: {terms_any}")
    return EvalResult(case_id=check["id"], passed=not failures, failures=failures, hits=[])


def run_suite(cases_path: Path) -> dict[str, Any]:
    suite = json.loads(cases_path.read_text(encoding="utf-8"))
    store = MemoryStore(MEMORY_DIR, MEMORY_INDEX_PATH)
    default_top_k = int(suite.get("default_top_k") or 5)
    retrieval_results = [
        run_retrieval_case(store, case, default_top_k)
        for case in suite.get("cases", [])
    ]
    static_results = [
        run_static_check(check)
        for check in suite.get("static_checks", [])
    ]
    all_results = retrieval_results + static_results
    passed = sum(1 for result in all_results if result.passed)
    failed = len(all_results) - passed
    return {
        "suite": suite.get("suite", str(cases_path)),
        "passed": passed,
        "failed": failed,
        "results": [
            {
                "case_id": result.case_id,
                "passed": result.passed,
                "failures": result.failures,
                "hits": [
                    {
                        "id": hit["id"],
                        "project": hit.get("metadata", {}).get("project"),
                        "category": hit.get("metadata", {}).get("category"),
                        "created_at": hit.get("metadata", {}).get("created_at"),
                        "score": hit.get("score"),
                        "memory": hit.get("memory", "")[:220],
                    }
                    for hit in result.hits
                ],
            }
            for result in all_results
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Local Memory retrieval eval cases")
    parser.add_argument(
        "--cases",
        type=Path,
        default=PRIVATE_CASES if PRIVATE_CASES.exists() else EXAMPLE_CASES,
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    args = parser.parse_args()

    if args.cases == EXAMPLE_CASES:
        print(
            "Using structure-only example cases. Copy to "
            "eval_cases/local/scheduled_retrieval_eval_cases.json and fill private ids/queries for real recall evals."
        )
    report = run_suite(args.cases)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"{report['suite']}: {report['passed']} passed, {report['failed']} failed")
        for result in report["results"]:
            status = "PASS" if result["passed"] else "FAIL"
            print(f"{status} {result['case_id']}")
            for failure in result["failures"]:
                print(f"  - {failure}")

    if report["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
