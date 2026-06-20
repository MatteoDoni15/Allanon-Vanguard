"""
CLI entry point.

Usage:
    python main.py "high-yield savings accounts" "how to build an emergency fund"
    python main.py --file keywords.txt
    python main.py                      # runs the 3 demo keywords below

At 700 posts/month (~23/day) this same `run_for_keyword` call is what a
scheduler (cron, Airflow, or a queue worker -- see README "Scaling to
700 posts/month") would invoke once per keyword, in parallel workers.
"""

from __future__ import annotations

import argparse
import sys

from config import settings
from src.logging_config import configure_logging, get_logger
from src.pipeline_graph import run_for_keyword

logger = get_logger("main")

DEMO_KEYWORDS = [
    "how to start investing",
    "best budgeting apps for beginners",
    "how to improve your credit score",
]


def main():
    configure_logging()
    logger.info(f"Starting blog automation pipeline (LLM_PROVIDER={settings.llm_provider})")

    parser = argparse.ArgumentParser(description="Run the automated blog pipeline.")
    parser.add_argument("keywords", nargs="*", help="One or more target keywords.")
    parser.add_argument("--file", help="Path to a text file with one keyword per line.")
    args = parser.parse_args()

    keywords = list(args.keywords)
    if args.file:
        logger.info(f"Reading keywords from file: {args.file}")
        with open(args.file, "r", encoding="utf-8") as f:
            keywords += [line.strip() for line in f if line.strip()]
    if not keywords:
        keywords = DEMO_KEYWORDS
        logger.info(f"No keywords supplied -- running {len(keywords)} demo keywords")

    logger.info(f"Processing {len(keywords)} keyword(s)")
    results = []
    for i, kw in enumerate(keywords, 1):
        logger.info(f"[{i}/{len(keywords)}] Running pipeline for: '{kw}'")
        state = run_for_keyword(kw)
        results.append(state)
        _print_summary(state)
        print()

    published = sum(1 for r in results if r.get("status") == "published")
    needs_review = sum(1 for r in results if r.get("status") == "needs_review")
    logger.info(f"Pipeline complete: {published} published, {needs_review} needs review, {len(results)} total")


def _print_summary(state: dict) -> None:
    seo = state.get("seo_report", {})
    quality = state.get("quality", {})
    compliance = state.get("compliance", {})
    print(f"  Title:        {state.get('title')}")
    print(f"  Voice profile: {state.get('voice_profile')}   "
          f"Importance tier: {state.get('importance_tier')}")
    print(f"  SEO score:    {seo.get('score')}/100  "
          f"(words={seo.get('word_count')}, flesch={seo.get('flesch_reading_ease')}, "
          f"kw_density={seo.get('keyword_density_pct')}%)")
    print(f"  Internal links suggested: {len(state.get('internal_links', []))}")
    for link in state.get("internal_links", []):
        print(f"    - '{link['anchor_text']}' -> {link['target_url']} "
              f"(similarity={link['similarity']})")
    print(f"  Compliance judge: {'PASSED' if compliance.get('passed', True) else 'FAILED'}")
    for reason in compliance.get("reasons", []):
        print(f"    - {reason}")
    fact_check = state.get("fact_check", {})
    print(f"  Policy fact-check: {'PASSED' if fact_check.get('passed', True) else 'FAILED'}")
    for reason in fact_check.get("reasons", []):
        print(f"    - {reason}")
    duplicate_check = state.get("duplicate_check", {})
    print(f"  Duplicate check: {'PASSED' if duplicate_check.get('passed', True) else 'FAILED'}")
    for reason in duplicate_check.get("reasons", []):
        print(f"    - {reason}")
    print(f"  Quality gate: {'PASSED' if quality.get('passed') else 'FAILED'}"
          + (f" after {state.get('retries', 0)} retr{'y' if state.get('retries')==1 else 'ies'}" if state.get('retries') else ""))
    if not quality.get("passed"):
        for reason in quality.get("reasons", []):
            print(f"    - {reason}")
    print(f"  Status:       {state.get('status')}")
    print(f"  AI disclosure: {state.get('ai_disclosure')}")
    if state.get("publish_result", {}).get("url"):
        print(f"  Output file:  {state['publish_result']['url']}")
        print(f"  Scheduled for: {state.get('scheduled_publish_at')}")
        print(f"  Canonical URL: {state.get('canonical_url')}")


if __name__ == "__main__":
    sys.exit(main() or 0)
