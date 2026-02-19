"""fixit CLI — the crow's command interface.

Usage:
    fixit scan [PATH] [--frame NAME] [--plugin NAME] [--output json|md]
    fixit label [SAMPLE_ID] [--batch N] [--review]
    fixit status
    fixit watch [--interval SECS] [--threshold FLOAT]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from fixit.engine import Crow
from fixit.signals import FileSystemSignal, EnvVarsSignal, GitSignal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fixit",
        description="Lateral-thinking diagnostics. Trained like a crow.",
    )
    sub = parser.add_subparsers(dest="command")

    # ── scan ──────────────────────────────────────────────────────────
    scan_p = sub.add_parser("scan", help="Run a diagnostic scan")
    scan_p.add_argument("path", nargs="?", default=".", help="Target path")
    scan_p.add_argument("--frame", help="Run only this frame")
    scan_p.add_argument("--plugin", help="Load a stack plugin")
    scan_p.add_argument("--output", choices=["md", "json"], default="md")
    scan_p.add_argument("--no-save", action="store_true", help="Don't save training data")

    # ── label ─────────────────────────────────────────────────────────
    label_p = sub.add_parser("label", help="Label training samples")
    label_p.add_argument("sample_id", nargs="?", help="Specific sample ID")
    label_p.add_argument("--batch", type=int, default=1, help="Label N samples")
    label_p.add_argument("--review", action="store_true", help="Review due samples")

    # ── status ────────────────────────────────────────────────────────
    sub.add_parser("status", help="Show crow development status")

    # ── watch ─────────────────────────────────────────────────────────
    watch_p = sub.add_parser("watch", help="Continuous scan (the active ball)")
    watch_p.add_argument("path", nargs="?", default=".", help="Target path")
    watch_p.add_argument("--interval", type=int, default=300, help="Seconds between scans")
    watch_p.add_argument("--threshold", type=float, default=0.7, help="Min confidence to report")
    watch_p.add_argument("--plugin", help="Load a stack plugin")

    args = parser.parse_args(argv)

    if args.command == "scan":
        return cmd_scan(args)
    elif args.command == "label":
        return cmd_label(args)
    elif args.command == "status":
        return cmd_status(args)
    elif args.command == "watch":
        return cmd_watch(args)
    else:
        parser.print_help()
        return 0


def cmd_scan(args) -> int:
    """Run a diagnostic scan."""
    crow = _build_crow(args.path)

    if args.plugin:
        crow.load_plugin(args.plugin)
    else:
        # Default signals for the target path
        crow.add_signal(FileSystemSignal(args.path, watch=["*.json", "*.yaml", "*.yml", "*.conf", "*.env"]))
        crow.add_signal(EnvVarsSignal())
        if (Path(args.path) / ".git").exists():
            crow.add_signal(GitSignal(args.path))

    frames = [args.frame] if args.frame else None
    prescriptions = crow.scan(frames=frames, save=not args.no_save)

    if args.output == "json":
        print(json.dumps([rx.to_dict() for rx in prescriptions], indent=2))
    else:
        _print_report(prescriptions, args.path)

    # Exit code: non-zero if any critical findings
    critical = [rx for rx in prescriptions if rx.severity() == "critical"]
    return 1 if critical else 0


def cmd_label(args) -> int:
    """Label training samples for the crow."""
    crow = Crow()

    if args.sample_id:
        return _label_one(crow, args.sample_id)

    # Get samples to label
    if args.review:
        samples = crow.cache.due_for_review(limit=args.batch)
        if not samples:
            print("No samples due for review.")
            return 0
    else:
        samples = crow.cache.unlabeled(limit=args.batch)
        if not samples:
            print("No unlabeled samples. Run a scan first.")
            return 0

    for sample in samples:
        _label_one(crow, sample.id)

    return 0


def _label_one(crow: Crow, sample_id: str) -> int:
    """Interactively label a single sample."""
    try:
        sample = crow.cache.load(sample_id)
    except FileNotFoundError:
        print(f"Sample {sample_id} not found.")
        return 1

    print(f"\n{'=' * 60}")
    print(f"Sample: {sample.id}")
    print(f"Time:   {time.strftime('%Y-%m-%d %H:%M', time.localtime(sample.timestamp))}")
    if sample.label:
        print(f"Current label: {sample.label} (review #{sample.review_count})")
    print(f"{'=' * 60}")

    for rx in sample.prescriptions:
        from fixit.prescription import Prescription
        p = Prescription.from_dict(rx)
        print(f"\n{p}")

    print(f"\n{'─' * 60}")
    print("  [1] Good find    (correct diagnosis)")
    print("  [2] Noise        (false positive)")
    print("  [3] Critical     (underrated severity)")
    print("  [4] Wrong frame  (right problem, wrong reasoning)")
    print("  [s] Skip")

    choice = input("\nVerdict: ").strip().lower()
    verdicts = {"1": "good_find", "2": "noise", "3": "critical", "4": "wrong_frame"}

    if choice in verdicts:
        crow.label(sample_id, verdicts[choice])
        print(f"Labeled as: {verdicts[choice]}")
        return 0
    else:
        print("Skipped.")
        return 0


def cmd_status(args) -> int:
    """Show the crow's development status."""
    crow = Crow()
    stats = crow.status()

    box_names = {1: "new", 2: "seen", 3: "familiar", 4: "known", 5: "mastered"}

    print(f"""
{'=' * 44}
  fixit.bot — Crow Status
{'=' * 44}
  Stage:          {stats['stage']} ({stats['stage_name']})
  Training pairs: {stats['labeled']} labeled / {stats['total_scans']} total
  Next stage at:  {stats.get('next_stage_at', 'N/A')} pairs

  Accuracy:       {stats['accuracy']:.0%}
  FP rate:        {stats['false_positive_rate']:.0%}

  Leitner Boxes:""")
    for box in range(1, 6):
        count = stats['leitner_boxes'].get(box, 0)
        print(f"    Box {box} ({box_names[box]:>8}):  {count} patterns")

    print(f"""
  Brain:          {stats.get('model', 'not set')}
  Signals:        {stats.get('signal_count', 0)}
  Target:         {stats.get('target', 'not set')}
{'=' * 44}
""")
    return 0


def cmd_watch(args) -> int:
    """Continuous scan mode — the active ball."""
    print(f"fixit watch: scanning every {args.interval}s (threshold: {args.threshold})")
    print("Press Ctrl+C to stop.\n")

    crow = _build_crow(args.path)
    if args.plugin:
        crow.load_plugin(args.plugin)
    else:
        crow.add_signal(FileSystemSignal(args.path, watch=["*.json", "*.yaml", "*.conf"]))
        crow.add_signal(EnvVarsSignal())

    scan_num = 0
    try:
        while True:
            scan_num += 1
            ts = time.strftime("%H:%M:%S")
            prescriptions = crow.scan()
            hot = [rx for rx in prescriptions if rx.confidence >= args.threshold]

            if hot:
                print(f"[{ts}] Scan #{scan_num}: {len(hot)} findings above threshold")
                for rx in hot:
                    print(f"  [{rx.confidence:.0%}] {rx.frame}: {rx.title}")
            else:
                print(f"[{ts}] Scan #{scan_num}: clean")

            time.sleep(args.interval)
    except KeyboardInterrupt:
        print(f"\nStopped after {scan_num} scans.")
        return 0


def _build_crow(path: str) -> Crow:
    """Build a Crow instance for the given path."""
    return Crow(target=path)


def _print_report(prescriptions: list, target: str) -> None:
    """Pretty-print a scan report."""
    from fixit.prescription import Prescription

    print(f"""
{'=' * 56}
  fixit.bot — Lateral Diagnostics Report
  Target: {target}
  Frames: 6    Time: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
{'=' * 56}
""")

    if not prescriptions:
        print("  No findings. The crow sees nothing unusual.")
    else:
        for rx in prescriptions:
            print(f"{rx}\n")

    high_blast = [rx for rx in prescriptions if rx.blast_radius == "high"]
    avg_conf = sum(rx.confidence for rx in prescriptions) / len(prescriptions) if prescriptions else 0

    print(f"{'─' * 56}")
    print(f"  {len(prescriptions)} prescriptions | {len(high_blast)} high blast | avg confidence: {avg_conf:.0%}")
    print(f"{'─' * 56}")


if __name__ == "__main__":
    sys.exit(main())
