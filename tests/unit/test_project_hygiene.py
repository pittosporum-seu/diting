"""Project hygiene tests: .gitignore validity, no secrets, no oversized artifacts."""

import subprocess
from pathlib import Path

import yaml


class TestGitignoreUTF8:
    """Verify .gitignore is valid UTF-8 without NUL bytes."""

    def test_no_nul_bytes(self):
        path = Path(".gitignore")
        data = path.read_bytes()
        assert b"\x00" not in data, ".gitignore contains NUL bytes"

    def test_valid_utf8(self):
        path = Path(".gitignore")
        data = path.read_bytes()
        data.decode("utf-8")

    def test_not_empty(self):
        path = Path(".gitignore")
        lines = path.read_text("utf-8").splitlines()
        assert len(lines) >= 5, ".gitignore has too few lines"

    def test_contains_experiment_ignore(self):
        content = Path(".gitignore").read_text("utf-8")
        assert "experiment/backtest_data/" in content
        assert "experiment/*.csv" in content

    def test_contains_research_artifact_allow(self):
        content = Path(".gitignore").read_text("utf-8")
        assert "research/artifacts/**" in content
        assert "!research/artifacts/**/manifest.json" in content
        assert "!research/artifacts/**/summary.json" in content
        assert "!research/artifacts/**/" in content, "missing directory re-inclusion rule"


class TestRepositoryPolicies:
    """Verify cross-platform line endings and hook scope are deterministic."""

    def test_text_files_are_lf(self):
        content = Path(".gitattributes").read_text("utf-8")
        assert "* text=auto eol=lf" in content

    def test_common_binary_types_are_binary(self):
        content = Path(".gitattributes").read_text("utf-8")
        for extension in ("*.png", "*.pdf", "*.pkl", "*.db", "*.xlsx"):
            assert f"{extension} binary" in content

    def test_ruff_hooks_match_release_scope(self):
        config = yaml.safe_load(Path(".pre-commit-config.yaml").read_text("utf-8"))
        ruff_hooks = {
            hook["id"]: hook
            for repo in config["repos"]
            for hook in repo["hooks"]
            if hook["id"] in {"ruff", "ruff-format"}
        }
        assert set(ruff_hooks) == {"ruff", "ruff-format"}
        for hook in ruff_hooks.values():
            assert hook.get("files") == "^(src/|tests/)"


class TestNoCommittedSecrets:
    """Verify no credential-bearing files are tracked."""

    def test_dotenv_not_tracked(self):
        result = subprocess.run(
            ["git", "ls-files", ".env"],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "", ".env should not be tracked"

    def test_notify_sh_not_tracked(self):
        result = subprocess.run(
            ["git", "ls-files", "scripts/notify-diting.sh"],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "", "notify-diting.sh should not be tracked"

    def test_only_env_example_tracked(self):
        result = subprocess.run(
            ["git", "ls-files", "*.env*"],
            capture_output=True,
            text=True,
        )
        tracked = [f for f in result.stdout.strip().splitlines() if f]
        for f in tracked:
            assert f.endswith(".env.example"), f"Unexpected tracked env file: {f}"


class TestNoRawArtifacts:
    """Verify raw experiment artifacts are not tracked."""

    def test_no_pkl_tracked(self):
        result = subprocess.run(
            ["git", "ls-files", "*.pkl"],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "", f"PKL files tracked: {result.stdout}"

    def test_no_log_tracked(self):
        result = subprocess.run(
            ["git", "ls-files", "*.log"],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "", f"Log files tracked: {result.stdout}"

    def test_no_experiment_csv_tracked(self):
        result = subprocess.run(
            ["git", "ls-files", "experiment/"],
            capture_output=True,
            text=True,
        )
        tracked = result.stdout.strip().splitlines()
        for f in tracked:
            assert not f.endswith(".csv") and not f.endswith(".pkl"), (
                f"Experiment raw data tracked: {f}"
            )

    def test_no_large_json_in_research(self):
        """Reject oversized JSON research artifacts (>500KB)."""
        research_dir = Path("research/artifacts")
        if not research_dir.exists():
            return
        limit = 500_000  # 500 KB
        for json_file in research_dir.rglob("*.json"):
            size = json_file.stat().st_size
            assert size <= limit, f"Research artifact {json_file} is {size} bytes (>{limit} limit)"


class TestNotifyPs1Syntax:
    """Verify the PowerShell wrapper parses correctly."""

    def test_ps1_exists(self):
        path = Path("scripts/notify-diting.ps1")
        assert path.exists(), "notify-diting.ps1 not found"

    def test_ps1_is_valid_utf8(self):
        path = Path("scripts/notify-diting.ps1")
        data = path.read_bytes()
        data.decode("utf-8")

    def test_ps1_is_secret_free(self):
        """Verify the wrapper contains no credential patterns."""
        content = Path("scripts/notify-diting.ps1").read_text("utf-8").lower()
        # Must not contain API keys, app secrets, or tokens
        suspicious = [
            "sk-",  # OpenAI-style key
            "app_secret",  # feishu secret
            "feishu_app_secret",
            "email_password",
            "api_key=",
        ]
        for pattern in suspicious:
            assert pattern not in content, f"Possible credential pattern in wrapper: {pattern}"

    def test_ps1_has_dryrun(self):
        content = Path("scripts/notify-diting.ps1").read_text("utf-8")
        assert "DryRun" in content, "Wrapper missing -DryRun support"
        assert "[DRY RUN]" in content, "Wrapper missing dry-run output marker"

    def test_ps1_has_wsl_check(self):
        content = Path("scripts/notify-diting.ps1").read_text("utf-8")
        assert "wsl --list" in content, "Wrapper missing WSL availability check"
        assert "Ubuntu-24.04" in content, "Wrapper missing target distro"
        assert "test -f" in content, "Wrapper missing script existence check"
