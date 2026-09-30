#!/usr/bin/env python3
"""Run one dated, approved packet under the native service supervisor."""
import argparse
import datetime as dt
import json
from pathlib import Path

import engineering as e


def run(schedule, now=None):
    start = dt.datetime.fromisoformat(schedule['startAt'])
    latest = dt.datetime.fromisoformat(schedule['latestStartAt'])
    if start.tzinfo is None or latest.tzinfo is None or not 0 < (latest - start).total_seconds() <= 3600:
        raise ValueError('Schedule requires an explicit timezone and at most one hour of admission')
    now = now or dt.datetime.now(dt.timezone.utc)
    if now < start:
        return {'status': 'not-started', 'reason': 'Scheduled start has not arrived'}
    if now >= latest:
        return {'status': 'expired', 'reason': 'This one-time admission window has closed'}
    packet = json.loads(Path(schedule['packet']).read_text())
    return e.execute(packet)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schedule', type=Path, required=True)
    args = parser.parse_args()
    result = run(json.loads(args.schedule.read_text()))
    summary = {key: result[key] for key in ('runId', 'status', 'reason', 'prUrl', 'headSha') if key in result}
    e.c.save(args.schedule.with_suffix('.result.json'), summary)
    print(json.dumps(summary), flush=True)
    # The service allows only one restart. Completed/blocked work never replays.
    return 75 if result['status'] in {'retryable', 'interrupted', 'busy'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
