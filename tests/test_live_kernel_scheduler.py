from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jarvis_agent.kernel_contracts import (
    KernelRequest,
    SyscallKind,
    SyscallStatus,
)
from jarvis_agent.live_kernel_scheduler import LiveKernelScheduler


class LiveKernelSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def request(request_id="req_test"):
        return KernelRequest(
            request_id=request_id,
            mission_id="mission_test",
            syscall_kind=SyscallKind.OBSERVATION,
            capability="computer.observe",
            agent_id="windows",
            payload={
                "tool_name": "inspect_active_window",
                "arguments": {},
            },
            user_id="local-user",
        )

    def test_success_transitions_are_persisted(self):
        scheduler = LiveKernelScheduler(base_dir=self.root)
        request = self.request()
        scheduler.start(request)
        running = scheduler.store.get(request.request_id)
        self.assertEqual(running["status"], SyscallStatus.RUNNING)

        response = scheduler.complete(
            request.request_id,
            success=True,
            result={"verified": True},
        )
        self.assertTrue(response.success)
        stored = scheduler.store.get(request.request_id)
        self.assertEqual(stored["status"], SyscallStatus.SUCCEEDED)

    def test_failed_tool_result_is_terminal_and_releases_capacity(self):
        scheduler = LiveKernelScheduler(base_dir=self.root)
        request = self.request()
        scheduler.start(request)
        response = scheduler.complete(
            request.request_id,
            success=False,
            error="fixture_failure",
        )
        self.assertFalse(response.success)
        self.assertEqual(
            scheduler.store.get(request.request_id)["status"],
            SyscallStatus.FAILED,
        )
        self.assertEqual(scheduler.snapshot()["active_total"], 0)

    def test_running_request_after_restart_requires_reconciliation(self):
        first = LiveKernelScheduler(base_dir=self.root)
        request = self.request("req_uncertain")
        first.start(request)

        fresh = LiveKernelScheduler(base_dir=self.root)
        summary = fresh.startup_recovery_summary()
        self.assertEqual(len(summary.running_uncertain), 1)
        self.assertEqual(
            summary.running_uncertain[0].request_id,
            "req_uncertain",
        )
        self.assertEqual(len(summary.queued_safe_to_retry), 0)

    def test_queued_request_after_restart_is_not_auto_replayed(self):
        first = LiveKernelScheduler(base_dir=self.root)
        request = self.request("req_queued")
        first.store.put(request, status=SyscallStatus.QUEUED)

        fresh = LiveKernelScheduler(base_dir=self.root)
        summary = fresh.startup_recovery_summary()
        self.assertEqual(len(summary.queued_safe_to_retry), 1)
        self.assertEqual(fresh.snapshot()["active_total"], 0)
        self.assertEqual(fresh.snapshot()["queue_depth"], 0)

    def test_duplicate_request_id_fails_before_execution(self):
        scheduler = LiveKernelScheduler(base_dir=self.root)
        request = self.request()
        scheduler.store.put(request, status=SyscallStatus.QUEUED)
        with self.assertRaises(ValueError):
            scheduler.start(request)


if __name__ == "__main__":
    unittest.main()
