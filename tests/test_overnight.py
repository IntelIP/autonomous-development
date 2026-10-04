import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'controller'))
import overnight


class OvernightTests(unittest.TestCase):
    def test_dated_admission_never_bypasses_engineering_window(self):
        with tempfile.TemporaryDirectory() as directory:
            packet = Path(directory) / 'packet.json'
            packet.write_text(json.dumps({'approved': 'fixture'}))
            schedule = {'packet': str(packet), 'startAt': '2026-09-29T22:00:00-04:00',
                        'latestStartAt': '2026-09-29T23:00:00-04:00'}
            with patch.object(overnight.e, 'execute', return_value={'status': 'blocked'}) as execute:
                for stamp, status in [('2026-09-29T21:59:59-04:00', 'not-started'),
                                      ('2026-09-29T23:00:00-04:00', 'expired'),
                                      ('2026-09-30T22:00:00-04:00', 'expired')]:
                    self.assertEqual(overnight.run(schedule, dt.datetime.fromisoformat(stamp))['status'], status)
                execute.assert_not_called()
                self.assertEqual(overnight.run(schedule, dt.datetime.fromisoformat(schedule['startAt']))['status'], 'blocked')
                execute.assert_called_once_with({'approved': 'fixture'})
            for invalid in ('2026-09-29T23:00:00', '2026-09-30T23:00:00-04:00'):
                with self.assertRaises(ValueError):
                    overnight.run(dict(schedule, latestStartAt=invalid))
