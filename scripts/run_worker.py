from __future__ import annotations

import argparse

from mfethuls.worker import run_worker


def main() -> None:
    parser = argparse.ArgumentParser(description="Run mfethuls ingest worker")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--max-jobs", type=int, default=None)
    args = parser.parse_args()

    run_worker(poll_interval=args.poll_interval, max_jobs=args.max_jobs)


if __name__ == "__main__":
    main()
