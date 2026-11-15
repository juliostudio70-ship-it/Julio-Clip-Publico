from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from public_quota import PublicQuota, WINDOW, trusted_time


class PublicQuotaTests(unittest.TestCase):
    def test_rolling_window_uses_online_clock_and_one_watermark(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [1700000000]
            clock = lambda: now[0]
            quota = PublicQuota(Path(directory), clock)
            self.assertTrue(quota.reserve('first', True))
            now[0] += 60
            self.assertFalse(quota.reserve('second', True))
            with patch('time.time', return_value=now[0]+7*WINDOW):
                reopened = PublicQuota(Path(directory), clock)
                with self.assertRaisesRegex(ValueError, 'dos clips'):
                    reopened.reserve('third', False)
            now[0] += WINDOW - 60
            self.assertEqual(quota.status(), {'clips': 1, 'watermark': True})
            self.assertTrue(quota.reserve('third', True))
            self.assertEqual(quota.status()['clips'], 0)

    def test_failed_export_can_release_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            quota = PublicQuota(Path(directory), lambda: 1700000000)
            quota.reserve('failed', True)
            quota.release('failed')
            self.assertEqual(quota.status(), {'clips': 2, 'watermark': True})

    def test_clock_failure_does_not_fall_back_to_windows_time(self):
        with patch('public_quota.http.client.HTTPSConnection') as https:
            https.return_value.request.side_effect = OSError('offline')
            with self.assertRaisesRegex(ValueError, 'verificar la hora'):
                trusted_time()
