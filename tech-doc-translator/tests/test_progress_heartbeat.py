"""R15：交付校验的长阶段按固定间隔输出 running 进度，阶段结束后不再输出。"""
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
import verify_delivery as delivery_verifier


class ProgressHeartbeatTest(unittest.TestCase):
    def run_stage(self, seconds):
        events = []
        context = delivery_verifier.new_run_context(events.append)
        with delivery_verifier.progress_stage(context, 'verify_pdf', 'book.pdf', 7):
            time.sleep(seconds)
        settled = len(events)
        time.sleep(0.15)
        self.assertEqual(len(events), settled, events)   # 阶段结束后不再输出
        return events

    def test_long_stage_reports_running_until_it_ends(self):
        with patch.object(delivery_verifier, 'PROGRESS_HEARTBEAT_SECONDS', 0.05):
            events = self.run_stage(0.32)
        kinds = [event['event'] for event in events]
        self.assertEqual((kinds[0], kinds[-1]), ('start', 'end'), kinds)
        running = events[1:-1]
        self.assertGreaterEqual(len(running), 3, kinds)
        self.assertEqual({event['event'] for event in running}, {'running'}, kinds)
        self.assertTrue(all(event['stage'] == 'verify_pdf' and event['order'] == 7
                            for event in running), running)
        elapsed = [event['elapsed_seconds'] for event in running]
        self.assertEqual(elapsed, sorted(elapsed))

    def test_short_stage_reports_only_start_and_end(self):
        self.assertEqual([event['event'] for event in self.run_stage(0)], ['start', 'end'])


if __name__ == '__main__':
    unittest.main()
