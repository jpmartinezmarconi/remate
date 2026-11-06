import unittest
from unittest.mock import Mock, patch

from app import create_app
from app.outbid_worker import run_outbid_retry_loop


class WorkerConfig:
    TESTING = True
    SECRET_KEY = "test-key"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class OutbidWorkerTest(unittest.TestCase):
    def test_worker_retries_after_error_and_stops_cleanly(self):
        app = create_app(WorkerConfig)
        stop = Mock()
        stop.is_set.side_effect = [False, False]
        stop.wait.side_effect = [False, True]
        with patch("app.outbid_worker.send_due_auction_outbid_notifications", side_effect=[RuntimeError("offline"), 1]) as send:
            run_outbid_retry_loop(app, stop, interval=60)
        self.assertEqual(send.call_count, 2)
        self.assertEqual(stop.wait.call_count, 2)
        stop.wait.assert_called_with(60)


if __name__ == "__main__":
    unittest.main()