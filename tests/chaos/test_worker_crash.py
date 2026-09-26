"""Chaos tests simulating worker crashes and auto-replacement."""

import pytest
import time
from unittest.mock import MagicMock, patch
from celerlite.config import CelerLiteConfig
from celerlite.worker.pool import WorkerPool, WorkerProcess


class TestWorkerCrashRecovery:
    def test_dead_worker_is_detected_and_replaced(self):
        cfg = CelerLiteConfig(WORKER_CONCURRENCY=2, HEARTBEAT_INTERVAL=1)
        pool = WorkerPool(cfg=cfg)

        # Mock multiprocessing.Process
        mock_proc_1 = MagicMock()
        mock_proc_1.pid = 1001
        mock_proc_1.is_alive.return_value = True

        mock_proc_2 = MagicMock()
        mock_proc_2.pid = 1002
        mock_proc_2.is_alive.return_value = True

        pool._workers = {
            "worker-1": WorkerProcess("worker-1", mock_proc_1),
            "worker-2": WorkerProcess("worker-2", mock_proc_2),
        }

        assert pool.active_workers == 2

        # Simulate sudden crash of worker-1 (e.g., SIGKILL / OOM)
        mock_proc_1.is_alive.return_value = False

        # Verify pool status reports 1 active
        status = pool.get_pool_status()
        assert status["active"] == 1

        # Trigger check and replace
        with patch.object(pool, "_spawn_worker") as mock_spawn:
            # New replacement worker
            replacement_proc = MagicMock()
            replacement_proc.pid = 1003
            replacement_proc.is_alive.return_value = True
            mock_spawn.return_value = WorkerProcess("worker-replacement", replacement_proc)

            pool._check_and_replace_dead_workers()

            # worker-1 should be removed
            assert "worker-1" not in pool._workers
            # _spawn_worker should have been called to replace it
            mock_spawn.assert_called_once()

    def test_pool_status_metrics(self):
        cfg = CelerLiteConfig(WORKER_CONCURRENCY=3)
        pool = WorkerPool(cfg=cfg)

        mock_proc = MagicMock()
        mock_proc.pid = 2001
        mock_proc.is_alive.return_value = True

        pool._workers = {
            "w-1": WorkerProcess("w-1", mock_proc),
        }

        status = pool.get_pool_status()
        assert status["total"] == 1
        assert status["active"] == 1
        assert status["workers"][0]["worker_id"] == "w-1"
        assert status["workers"][0]["alive"] is True
