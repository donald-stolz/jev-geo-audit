import unittest
from pathlib import Path

# Verify the repository boundary and command-center contract before a credential exists.
ROOT = Path(__file__).parent
REQUIRED_FILES = {
    "README.md", "CLAUDE.md", ".gitignore", ".env.example",
    "index.html", "styles.css", "app.js", "server.py", "smoke_test.py"
}
BROWSER_FILES = ("index.html", "styles.css", "app.js")


class ProjectRepositoryTests(unittest.TestCase):
    def test_required_files_exist(self):
        missing = sorted(name for name in REQUIRED_FILES if not (ROOT / name).is_file())
        self.assertEqual(missing, [], f"Missing project files: {missing}")

    def test_browser_assets_are_linked(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="styles.css"', html)
        self.assertIn('src="app.js"', html)

    def test_command_center_elements_exist(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        required_ids = (
            "appShell", "websiteUrl", "discoverSite", "runPilot", "runFull", "stopRun",
            "fullscreenBtn", "activityPanel", "workerRail", "runStatus", "activeWorkers",
            "progressBar", "liveSpeed", "throughput", "successGauge", "successRate",
            "feed", "reviewQueue", "pageContent", "fullRunDialog", "completionDialog",
            "completionSummary"
        )
        for element_id in required_ids:
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn("Run Full Discovery", html)
        self.assertNotIn("Continue Full Discovery", html)
        self.assertNotIn('id="skipWarningDialog"', html)

    def test_live_worker_fullscreen_and_automatic_stop_logic_exist(self):
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        for required_text in (
            "activePages", "AbortController", "requestFullscreen", "exitFullscreen",
            "fullscreenchange", "aria-busy", "await Promise.all(batch.map",
            "function shouldAutoStop()", "stats.attempted >= 20",
            "successfulAuditRate() < 0.5",
            "Stopped automatically: successful audit rate below 50%"
        ):
            self.assertIn(required_text, source)
        self.assertNotIn("Continue Full Discovery", source)

    def test_discovery_processing_contract_exists(self):
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "styles.css").read_text(encoding="utf-8")
        for required_text in (
            "is-discovering", "Discovering...", "requestAnimationFrame", "cancelAnimationFrame",
            "aria-valuetext", "Reading crawl rules and sitemap files"
        ):
            self.assertIn(required_text, source)
        for required_text in (
            ".activity-panel.is-discovering", "discovery-border-sweep", "discovery-progress"
        ):
            self.assertIn(required_text, styles)

    def test_viewport_motion_gauge_and_scroll_contract_exist(self):
        styles = (ROOT / "styles.css").read_text(encoding="utf-8")
        for required_text in (
            "100dvh", ".activity-panel.is-running", ".activity-panel.is-discovering",
            ".scroll-region", "overflow: hidden", "max-width: 1100px", "prefers-reduced-motion",
            "progress-light", "worker-orbit", ".gauge-value"
        ):
            self.assertIn(required_text, styles)

    def test_browser_files_contain_no_real_key_reference(self):
        source = "\n".join((ROOT / name).read_text(encoding="utf-8") for name in BROWSER_FILES)
        self.assertNotIn("OPENROUTER_API_KEY", source)
        self.assertNotIn("sk-or-v1-", source)

    def test_local_secret_is_ignored(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".env", ignored)

    def test_example_uses_only_the_placeholder(self):
        example = (ROOT / ".env.example").read_text(encoding="utf-8").strip()
        self.assertEqual(example, "OPENROUTER_API_KEY=your-api-key-here")


if __name__ == "__main__":
    unittest.main()
