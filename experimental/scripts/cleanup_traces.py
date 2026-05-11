"""Delete Langfuse traces by experiment name, tag, or all.

Usage:
    # Delete all traces
    uv run python experimental/scripts/cleanup_traces.py --all

    # Delete by experiment name (matches trace name prefix)
    uv run python experimental/scripts/cleanup_traces.py --experiment langchain_exp

    # Delete by tag
    uv run python experimental/scripts/cleanup_traces.py --tag exp_baseline

    # Dry run (show what would be deleted)
    uv run python experimental/scripts/cleanup_traces.py --experiment langchain_exp --dry_run

    # Delete specific battle
    uv run python experimental/scripts/cleanup_traces.py --tag battle_001
"""
import argparse
import os
import sys
from dotenv import load_dotenv

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, project_root)

load_dotenv(os.path.join(os.path.dirname(__file__), "../config/.env"))

parser = argparse.ArgumentParser(description="Delete Langfuse traces")
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument("--all", action="store_true", help="Delete all traces")
group.add_argument("--experiment", type=str, help="Delete traces with name matching prefix")
group.add_argument("--tag", type=str, help="Delete traces containing this tag")
parser.add_argument("--dry_run", action="store_true", help="Show traces without deleting")
args = parser.parse_args()


def main():
    from langfuse import Langfuse

    client = Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
    )

    all_ids = []
    page = 1

    if args.all:
        print("Fetching all traces...")
        while True:
            resp = client.api.trace.list(page=page, limit=100)
            traces = resp.data if hasattr(resp, "data") else resp
            if not traces:
                break
            all_ids.extend([t.id for t in traces])
            print(f"  Page {page}: {len(traces)} traces (total: {len(all_ids)})")
            page += 1
    elif args.experiment:
        print(f"Fetching traces matching '{args.experiment}'...")
        while True:
            resp = client.api.trace.list(page=page, limit=100, name=args.experiment)
            traces = resp.data if hasattr(resp, "data") else resp
            if not traces:
                break
            for t in traces:
                if hasattr(t, "name") and t.name and t.name.startswith(args.experiment):
                    all_ids.append(t.id)
            print(f"  Page {page}: {len(traces)} fetched, {len(all_ids)} matched")
            page += 1
    elif args.tag:
        print(f"Fetching traces with tag '{args.tag}'...")
        while True:
            resp = client.api.trace.list(page=page, limit=100, tags=[args.tag])
            traces = resp.data if hasattr(resp, "data") else resp
            if not traces:
                break
            all_ids.extend([t.id for t in traces])
            print(f"  Page {page}: {len(traces)} traces")
            page += 1

    if not all_ids:
        print("No traces found.")
        return

    print(f"\nTotal: {len(all_ids)} traces")

    if args.dry_run:
        print("[DRY RUN] No traces deleted.")
        return

    # Delete in batches of 100
    deleted = 0
    for i in range(0, len(all_ids), 100):
        batch = all_ids[i : i + 100]
        client.api.trace.delete_multiple(trace_ids=batch)
        deleted += len(batch)
        print(f"  Deleted {deleted}/{len(all_ids)}")

    print(f"\nDone. {deleted} traces deleted.")


if __name__ == "__main__":
    main()
