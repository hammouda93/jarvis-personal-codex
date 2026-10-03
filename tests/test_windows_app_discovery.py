from __future__ import annotations

import unittest

from jarvis_agent.windows_app_discovery import (
    ApplicationCandidate,
    WindowsApplicationDiscovery,
)


class WindowsApplicationDiscoveryTests(unittest.TestCase):
    def _resolver(self, *candidates):
        def provider():
            return list(candidates)

        return WindowsApplicationDiscovery(
            providers=(("fixture", provider),),
            launcher=lambda item: (
                True,
                item.source,
                item.app_id or item.path,
            ),
        )

    def test_exact_name_resolves_without_application_specific_rule(self):
        resolver = self._resolver(
            ApplicationCandidate(
                name="WhatsApp",
                source="start_apps",
                app_id="5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App",
            ),
            ApplicationCandidate(
                name="WhatsApp Beta",
                source="start_apps",
                app_id="example.beta!App",
            ),
        )
        result = resolver.resolve("WhatsApp")
        self.assertTrue(result.resolved)
        self.assertEqual(result.candidate.name, "WhatsApp")
        self.assertEqual(result.candidate.source, "start_apps")

    def test_source_priority_breaks_same_name_registration_tie(self):
        resolver = self._resolver(
            ApplicationCandidate(
                name="Contoso Studio",
                source="executable",
                path=r"C:\Program Files\Contoso\studio.exe",
            ),
            ApplicationCandidate(
                name="Contoso Studio",
                source="app_paths",
                path=r"C:\Apps\Contoso\studio.exe",
            ),
        )
        result = resolver.resolve("Contoso Studio")
        self.assertTrue(result.resolved)
        self.assertEqual(result.candidate.source, "app_paths")

    def test_close_distinct_candidates_are_reported_as_ambiguous(self):
        resolver = self._resolver(
            ApplicationCandidate(
                name="Photo Studio",
                source="start_apps",
                app_id="photo.one!App",
            ),
            ApplicationCandidate(
                name="Photo Studio Pro",
                source="start_apps",
                app_id="photo.pro!App",
            ),
        )
        result = resolver.resolve("Photo Studio P")
        self.assertEqual(result.status, "ambiguous")
        self.assertGreaterEqual(len(result.alternatives), 2)

    def test_generic_application_word_is_rejected_before_scan(self):
        called = []

        def provider():
            called.append(True)
            return []

        resolver = WindowsApplicationDiscovery(
            providers=(("fixture", provider),),
        )
        result = resolver.resolve("application")
        self.assertEqual(result.status, "invalid")
        self.assertEqual(called, [])

    def test_start_apps_parser_accepts_single_object_and_list(self):
        parser = WindowsApplicationDiscovery._parse_start_apps
        one = parser(
            '{"Name":"Calculator","AppID":"Microsoft.Calculator!App"}'
        )
        self.assertEqual(one[0].name, "Calculator")
        self.assertEqual(one[0].app_id, "Microsoft.Calculator!App")

        many = parser(
            '[{"Name":"One","AppID":"one!App"},'
            '{"Name":"Two","AppID":"two!App"}]'
        )
        self.assertEqual([item.name for item in many], ["One", "Two"])

    def test_launch_keeps_resolution_evidence_and_method(self):
        resolver = self._resolver(
            ApplicationCandidate(
                name="Future App",
                source="app_paths",
                path=r"C:\Future\future.exe",
            )
        )
        result = resolver.launch("Future App")
        self.assertTrue(result.success)
        self.assertEqual(result.launch_method, "app_paths")
        self.assertEqual(result.resolution.candidate.name, "Future App")

    def test_provider_failure_is_traced_not_fatal(self):
        def broken():
            raise OSError("registry unavailable")

        def healthy():
            return [
                ApplicationCandidate(
                    name="Healthy App",
                    source="start_menu",
                    path=r"C:\Healthy.lnk",
                )
            ]

        resolver = WindowsApplicationDiscovery(
            providers=(("broken", broken), ("healthy", healthy)),
        )
        result = resolver.resolve("Healthy App")
        self.assertTrue(result.resolved)
        self.assertEqual(len(result.trace), 2)
        self.assertIn("OSError", result.trace[0]["error"])


if __name__ == "__main__":
    unittest.main()
