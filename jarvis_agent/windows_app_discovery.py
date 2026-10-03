from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import time
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


_GENERIC_APP_NAMES = {
    "app",
    "application",
    "browser",
    "logiciel",
    "navigateur",
    "program",
    "programme",
}


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower().strip())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s.+#-]", " ", text, flags=re.UNICODE)
    text = text.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text).strip()


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9.+#]*", _normalize(value))
        if len(token) >= 2
    }


@dataclass(frozen=True)
class ApplicationCandidate:
    name: str
    source: str
    app_id: str = ""
    path: str = ""
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def identity(self) -> str:
        if self.app_id:
            return "aumid:" + self.app_id.casefold()
        if self.path:
            return "path:" + os.path.normcase(self.path)
        return f"{self.source}:{_normalize(self.name)}"

    def as_dict(self) -> dict[str, Any]:
        data = {
            "name": self.name,
            "source": self.source,
            "score": round(float(self.score), 4),
        }
        if self.app_id:
            data["app_id"] = self.app_id
        if self.path:
            data["path"] = self.path
        if self.metadata:
            data["metadata"] = dict(self.metadata)
        return data


@dataclass(frozen=True)
class ApplicationResolution:
    query: str
    status: str
    candidate: ApplicationCandidate | None = None
    alternatives: tuple[ApplicationCandidate, ...] = ()
    trace: tuple[dict[str, Any], ...] = ()
    elapsed_ms: float = 0.0
    reason: str = ""

    @property
    def resolved(self) -> bool:
        return self.status == "resolved" and self.candidate is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "status": self.status,
            "candidate": self.candidate.as_dict() if self.candidate else None,
            "alternatives": [item.as_dict() for item in self.alternatives],
            "trace": [dict(item) for item in self.trace],
            "elapsed_ms": round(float(self.elapsed_ms), 3),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ApplicationLaunchResult:
    success: bool
    resolution: ApplicationResolution
    launch_method: str = ""
    launch_target: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "launch_method": self.launch_method,
            "launch_target": self.launch_target,
            "error": self.error,
            "resolution": self.resolution.as_dict(),
        }


Provider = Callable[[], Iterable[ApplicationCandidate]]
Launcher = Callable[[ApplicationCandidate], tuple[bool, str, str]]


class WindowsApplicationDiscovery:
    """Resolve installed apps through generic Windows registration data.

    Discovery is intentionally separate from UI verification. A successful
    activation only means Windows accepted the request; callers must observe a
    real window before claiming that the requested application is visible.
    """

    SOURCE_PRIOR = {
        "start_apps": 0.035,
        "app_paths": 0.030,
        "start_menu": 0.020,
        "desktop": 0.015,
        "executable": 0.0,
    }

    def __init__(
        self,
        *,
        providers: Sequence[tuple[str, Provider]] | None = None,
        launcher: Launcher | None = None,
        powershell_timeout_s: float = 4.0,
    ):
        self.powershell_timeout_s = max(0.5, float(powershell_timeout_s))
        self._launcher = launcher or self._launch_candidate
        self._providers = tuple(providers) if providers is not None else (
            ("start_apps", self._start_apps_candidates),
            ("app_paths", self._app_paths_candidates),
            ("start_menu", self._start_menu_candidates),
            ("executable", self._executable_candidates),
        )

    @staticmethod
    def _score(query: str, candidate: ApplicationCandidate) -> float:
        wanted = _normalize(query)
        name = _normalize(candidate.name)
        if not wanted or not name:
            return 0.0
        if wanted == name:
            semantic = 1.0
        elif wanted.replace(" ", "") == name.replace(" ", ""):
            semantic = 0.995
        else:
            wanted_tokens = _tokens(wanted)
            actual_tokens = _tokens(name)
            if wanted_tokens and wanted_tokens <= actual_tokens:
                semantic = 0.965
            elif (
                min(len(wanted), len(name)) >= 4
                and (wanted in name or name in wanted)
            ):
                semantic = 0.935
            else:
                semantic = difflib.SequenceMatcher(None, wanted, name).ratio()
        return min(
            1.0,
            semantic + WindowsApplicationDiscovery.SOURCE_PRIOR.get(
                candidate.source, 0.0
            ),
        )

    @staticmethod
    def _dedupe(
        candidates: Iterable[ApplicationCandidate],
    ) -> list[ApplicationCandidate]:
        best: dict[str, ApplicationCandidate] = {}
        for item in candidates:
            if not str(item.name or "").strip():
                continue
            key = item.identity()
            existing = best.get(key)
            if existing is None:
                best[key] = item
                continue
            old_prior = WindowsApplicationDiscovery.SOURCE_PRIOR.get(
                existing.source, 0.0
            )
            new_prior = WindowsApplicationDiscovery.SOURCE_PRIOR.get(
                item.source, 0.0
            )
            if new_prior > old_prior:
                best[key] = item
        return list(best.values())

    def resolve(self, query: str) -> ApplicationResolution:
        started = time.perf_counter()
        raw_query = str(query or "").strip()
        normalized = _normalize(raw_query)
        if (
            not normalized
            or normalized in _GENERIC_APP_NAMES
            or len(normalized.replace(" ", "")) < 2
        ):
            return ApplicationResolution(
                query=raw_query,
                status="invalid",
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                reason="application_name_too_generic",
            )

        all_candidates: list[ApplicationCandidate] = []
        trace: list[dict[str, Any]] = []
        for source_id, provider in self._providers:
            source_started = time.perf_counter()
            error = ""
            candidates: list[ApplicationCandidate] = []
            try:
                for item in provider():
                    if not item.source:
                        item = replace(item, source=source_id)
                    candidates.append(item)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"[:300]
            all_candidates.extend(candidates)
            trace.append(
                {
                    "source": source_id,
                    "candidate_count": len(candidates),
                    "elapsed_ms": round(
                        (time.perf_counter() - source_started) * 1000.0,
                        3,
                    ),
                    "error": error,
                }
            )

        ranked = [
            replace(item, score=self._score(raw_query, item))
            for item in self._dedupe(all_candidates)
        ]
        ranked = [item for item in ranked if item.score >= 0.72]
        ranked.sort(
            key=lambda item: (
                -item.score,
                -self.SOURCE_PRIOR.get(item.source, 0.0),
                len(item.name),
                item.name.casefold(),
            )
        )

        elapsed = (time.perf_counter() - started) * 1000.0
        if not ranked:
            return ApplicationResolution(
                query=raw_query,
                status="not_found",
                trace=tuple(trace),
                elapsed_ms=elapsed,
                reason="no_candidate_above_discovery_threshold",
            )

        top = ranked[0]
        strong = [item for item in ranked[:6] if item.score >= 0.86]
        if len(strong) >= 2:
            first_name = _normalize(strong[0].name)
            second_name = _normalize(strong[1].name)
            if (
                first_name != second_name
                and abs(strong[0].score - strong[1].score) <= 0.025
            ):
                return ApplicationResolution(
                    query=raw_query,
                    status="ambiguous",
                    alternatives=tuple(strong[:5]),
                    trace=tuple(trace),
                    elapsed_ms=elapsed,
                    reason="multiple_close_candidates",
                )

        if top.score < 0.86:
            return ApplicationResolution(
                query=raw_query,
                status="ambiguous",
                alternatives=tuple(ranked[:5]),
                trace=tuple(trace),
                elapsed_ms=elapsed,
                reason="best_candidate_below_resolution_threshold",
            )

        return ApplicationResolution(
            query=raw_query,
            status="resolved",
            candidate=top,
            alternatives=tuple(ranked[1:5]),
            trace=tuple(trace),
            elapsed_ms=elapsed,
        )

    def launch(self, query: str) -> ApplicationLaunchResult:
        resolution = self.resolve(query)
        if not resolution.resolved:
            return ApplicationLaunchResult(
                False,
                resolution,
                error=resolution.reason or resolution.status,
            )
        assert resolution.candidate is not None
        try:
            success, method, target = self._launcher(resolution.candidate)
            return ApplicationLaunchResult(
                bool(success),
                resolution,
                launch_method=str(method or ""),
                launch_target=str(target or ""),
                error="" if success else "windows_launch_rejected",
            )
        except Exception as exc:
            return ApplicationLaunchResult(
                False,
                resolution,
                error=f"{type(exc).__name__}: {exc}"[:500],
            )

    @staticmethod
    def _parse_start_apps(payload: str) -> list[ApplicationCandidate]:
        try:
            raw = json.loads(payload or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            return []
        result: list[ApplicationCandidate] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("Name") or item.get("name") or "").strip()
            app_id = str(
                item.get("AppID")
                or item.get("AppId")
                or item.get("appid")
                or ""
            ).strip()
            if name and app_id:
                result.append(
                    ApplicationCandidate(
                        name=name,
                        source="start_apps",
                        app_id=app_id,
                    )
                )
        return result

    def _start_apps_candidates(self) -> list[ApplicationCandidate]:
        if os.name != "nt":
            return []
        command = (
            "$ErrorActionPreference='Stop';"
            "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"
        )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.powershell_timeout_s,
            creationflags=flags,
        )
        if completed.returncode != 0:
            return []
        return self._parse_start_apps(completed.stdout)

    @staticmethod
    def _app_paths_candidates() -> list[ApplicationCandidate]:
        if os.name != "nt":
            return []
        try:
            import winreg
        except ImportError:
            return []

        base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
        result: list[ApplicationCandidate] = []
        seen: set[tuple[str, str]] = set()
        roots = (
            ("HKCU", winreg.HKEY_CURRENT_USER),
            ("HKLM", winreg.HKEY_LOCAL_MACHINE),
        )
        views = [0]
        for flag_name in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
            flag = int(getattr(winreg, flag_name, 0) or 0)
            if flag and flag not in views:
                views.append(flag)

        for hive_name, hive in roots:
            for view in views:
                access = int(getattr(winreg, "KEY_READ", 0x20019)) | int(view)
                try:
                    parent = winreg.OpenKey(hive, base, 0, access)
                except OSError:
                    continue
                try:
                    index = 0
                    while index < 5000:
                        try:
                            child_name = winreg.EnumKey(parent, index)
                        except OSError:
                            break
                        index += 1
                        try:
                            child = winreg.OpenKey(parent, child_name, 0, access)
                            try:
                                value, _kind = winreg.QueryValueEx(child, None)
                            finally:
                                winreg.CloseKey(child)
                        except OSError:
                            continue
                        path = os.path.expandvars(
                            str(value or "").strip().strip('"')
                        )
                        if not path:
                            continue
                        key = (
                            child_name.casefold(),
                            os.path.normcase(path),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        display = Path(child_name).stem.strip() or child_name
                        result.append(
                            ApplicationCandidate(
                                name=display,
                                source="app_paths",
                                path=path,
                                metadata={"hive": hive_name},
                            )
                        )
                finally:
                    winreg.CloseKey(parent)
        return result

    @staticmethod
    def _walk_candidates(
        roots: Iterable[tuple[str, Path]],
        *,
        suffixes: set[str],
        max_depth: int,
        max_files: int,
        source_default: str,
    ) -> list[ApplicationCandidate]:
        result: list[ApplicationCandidate] = []
        seen: set[str] = set()
        ignored = (
            "uninstall",
            "update",
            "updater",
            "service",
            "server",
            "helper",
            "crashpad",
        )
        for source_id, root in roots:
            if not root.exists() or not root.is_dir():
                continue
            base_depth = len(root.parts)
            visited = 0
            try:
                for current, dirs, files in os.walk(root):
                    current_path = Path(current)
                    depth = len(current_path.parts) - base_depth
                    if depth >= max_depth:
                        dirs[:] = []
                    for filename in files:
                        path = current_path / filename
                        if path.suffix.lower() not in suffixes:
                            continue
                        if any(word in filename.lower() for word in ignored):
                            continue
                        key = os.path.normcase(str(path))
                        if key in seen:
                            continue
                        seen.add(key)
                        name = path.stem.strip()
                        if name:
                            result.append(
                                ApplicationCandidate(
                                    name=name,
                                    source=source_id or source_default,
                                    path=str(path),
                                )
                            )
                        visited += 1
                        if visited >= max_files:
                            dirs[:] = []
                            break
                    if visited >= max_files:
                        break
            except OSError:
                continue
        return result

    def _start_menu_candidates(self) -> list[ApplicationCandidate]:
        appdata = os.getenv("APPDATA", "")
        programdata = os.getenv("PROGRAMDATA", r"C:\ProgramData")
        roots: list[tuple[str, Path]] = []
        if appdata:
            roots.append(
                (
                    "start_menu",
                    Path(appdata)
                    / "Microsoft"
                    / "Windows"
                    / "Start Menu"
                    / "Programs",
                )
            )
        roots.append(
            (
                "start_menu",
                Path(programdata)
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs",
            )
        )
        roots.append(("desktop", Path.home() / "Desktop"))
        return self._walk_candidates(
            roots,
            suffixes={".lnk", ".appref-ms", ".exe"},
            max_depth=3,
            max_files=1600,
            source_default="start_menu",
        )

    def _executable_candidates(self) -> list[ApplicationCandidate]:
        local = os.getenv("LOCALAPPDATA", "")
        program_files = os.getenv("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.getenv(
            "ProgramFiles(x86)",
            r"C:\Program Files (x86)",
        )
        roots: list[tuple[str, Path]] = []
        if local:
            roots.append(("executable", Path(local) / "Programs"))
        roots.extend(
            [
                ("executable", Path(program_files)),
                ("executable", Path(program_files_x86)),
            ]
        )
        return self._walk_candidates(
            roots,
            suffixes={".exe"},
            max_depth=4,
            max_files=3200,
            source_default="executable",
        )

    @staticmethod
    def _launch_candidate(
        candidate: ApplicationCandidate,
    ) -> tuple[bool, str, str]:
        if os.name != "nt":
            return False, "", ""

        if candidate.app_id:
            target = rf"shell:AppsFolder\{candidate.app_id}"
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                ["explorer.exe", target],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
            return True, "aumid", target

        path = str(candidate.path or "").strip()
        if path:
            startfile = getattr(os, "startfile", None)
            if callable(startfile):
                startfile(path)
                return True, candidate.source, path
            subprocess.Popen(
                [path],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True, candidate.source, path
        return False, "", ""


DEFAULT_WINDOWS_APP_DISCOVERY = WindowsApplicationDiscovery()
