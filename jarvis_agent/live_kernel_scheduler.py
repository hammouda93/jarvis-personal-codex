from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .capability_registry import (
    CapabilityRegistry,
    DEFAULT_CAPABILITY_REGISTRY,
)
from .kernel_contracts import (
    KernelRequest,
    KernelResponse,
    SyscallStatus,
)
from .kernel_request_store import KernelRequestStore
from .mission_scheduler import MissionScheduler


def _default_state_dir() -> Path:
    root = Path(
        os.getenv("LOCALAPPDATA")
        or os.getenv("XDG_STATE_HOME")
        or Path.home()
    )
    return root / "JarvisPersonal" / "live_kernel"


@dataclass(frozen=True)
class StartupRecoverySummary:
    running_uncertain: tuple[KernelRequest, ...]
    queued_safe_to_retry: tuple[KernelRequest, ...]

    def as_dict(self) -> dict[str, Any]:
        def compact(request: KernelRequest) -> dict[str, Any]:
            return {
                "request_id": request.request_id,
                "mission_id": request.mission_id,
                "agent_id": request.agent_id,
                "capability": request.capability,
                "tool_name": str(
                    dict(request.payload or {}).get("tool_name") or ""
                ),
                "created_at": request.created_at,
            }

        return {
            "running_uncertain_count": len(self.running_uncertain),
            "queued_safe_to_retry_count": len(self.queued_safe_to_retry),
            "running_uncertain": [
                compact(request) for request in self.running_uncertain
            ],
            "queued_safe_to_retry": [
                compact(request) for request in self.queued_safe_to_retry
            ],
        }


class LiveKernelScheduler:
    """Durable synchronous scheduler for the authoritative live tool path.

    A request is durably QUEUED before it can become RUNNING. The scheduler does
    not auto-replay requests found RUNNING after a restart because the external
    side effect may already have happened. Such requests are exposed as
    recovery candidates and require fresh observation/reconciliation.

    QUEUED requests from an interrupted process are also surfaced rather than
    silently replayed. They are safe to retry because they never entered
    RUNNING, but the current synchronous runtime leaves that retry decision to a
    future long-mission coordinator instead of executing old user intent in a
    new session.
    """

    def __init__(
        self,
        *,
        base_dir: str | Path | None = None,
        registry: CapabilityRegistry | None = None,
    ):
        self.registry = registry or DEFAULT_CAPABILITY_REGISTRY
        root = Path(base_dir) if base_dir else _default_state_dir()
        root.mkdir(parents=True, exist_ok=True)
        self.store = KernelRequestStore(root / "kernel_requests.sqlite3")
        self.scheduler = MissionScheduler(
            concurrency_limits={
                manifest.agent_id: manifest.max_concurrency
                for manifest in self.registry.agents()
            }
        )
        self._startup = StartupRecoverySummary(
            running_uncertain=tuple(
                self.store.by_status(SyscallStatus.RUNNING)
            ),
            queued_safe_to_retry=tuple(
                self.store.by_status(SyscallStatus.QUEUED)
            ),
        )

    def startup_recovery_summary(self) -> StartupRecoverySummary:
        return self._startup

    def start(self, request: KernelRequest):
        if self.store.get(request.request_id) is not None:
            raise ValueError("duplicate_live_kernel_request")

        self.store.put(request, status=SyscallStatus.QUEUED)
        try:
            self.scheduler.submit(request)
        except Exception as exc:
            self.store.mark(
                request.request_id,
                SyscallStatus.FAILED,
                error=f"scheduler_submit_failed:{exc}",
            )
            raise

        scheduled = self.scheduler.next_request(
            timeout_s=0.0,
            allowed_agents={request.agent_id},
        )
        if (
            scheduled is None
            or scheduled.request.request_id != request.request_id
        ):
            try:
                self.scheduler.cancel(request.request_id)
            except Exception:
                pass
            self.store.mark(
                request.request_id,
                SyscallStatus.FAILED,
                error="scheduler_did_not_start_request",
            )
            raise RuntimeError("scheduler_did_not_start_request")

        self.store.mark(request.request_id, SyscallStatus.RUNNING)
        return scheduled

    def complete(
        self,
        request_id: str,
        *,
        success: bool,
        result: dict[str, Any] | None = None,
        error: str = "",
    ) -> KernelResponse:
        response = self.scheduler.complete(
            request_id,
            success=bool(success),
            result=dict(result or {}),
            error=str(error or ""),
        )
        self.store.mark(
            request_id,
            response.status,
            error=str(error or ""),
        )
        return response

    def fail_exception(
        self,
        request_id: str,
        exc: Exception,
    ) -> KernelResponse | None:
        scheduled = self.scheduler.get(request_id)
        error = f"{type(exc).__name__}: {exc}"[:1200]
        if scheduled is None:
            self.store.mark(
                request_id,
                SyscallStatus.FAILED,
                error=error,
            )
            return None
        try:
            return self.complete(
                request_id,
                success=False,
                result={},
                error=error,
            )
        except Exception:
            self.store.mark(
                request_id,
                SyscallStatus.FAILED,
                error=error,
            )
            return None

    def snapshot(self) -> dict[str, int]:
        return self.scheduler.snapshot()
