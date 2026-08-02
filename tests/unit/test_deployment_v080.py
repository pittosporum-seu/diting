"""Release packaging, candidate and rollback safety gates."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAKE_COMMIT = "a" * 40


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_all_release_shell_scripts_are_syntactically_valid() -> None:
    for relative in (
        "scripts/deploy.sh",
        "scripts/smoke_test.sh",
        "scripts/vps-deploy-v080.sh",
    ):
        process = subprocess.run(
            ["bash", "-n", relative],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert process.returncode == 0, process.stderr


def test_release_controller_dry_run_redacts_token_and_keeps_ssh_verification() -> None:
    process = subprocess.run(
        [
            "bash",
            "scripts/deploy.sh",
            "verify",
            "--host",
            "deploy.example",
            "--commit",
            FAKE_COMMIT,
            "--dry-run",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    source = _read("scripts/deploy.sh")

    assert process.returncode == 0, process.stderr
    assert "REDACTED" in process.stdout
    assert "StrictHostKeyChecking=no" not in source
    assert "UserKnownHostsFile=/dev/null" not in source
    assert "git reset --hard" not in source
    assert "--skip-tests" not in source
    assert "origin/verify" in source


def test_all_remote_state_transitions_support_read_only_dry_run() -> None:
    for command in ("rehearse", "promote", "rollback"):
        process = subprocess.run(
            [
                "bash",
                "scripts/deploy.sh",
                command,
                "--host",
                "deploy.example",
                "--commit",
                FAKE_COMMIT,
                "--dry-run",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert process.returncode == 0, process.stderr
        assert f"vps-deploy-v080.sh {command}" in process.stdout


def test_stage_dry_run_uses_checksummed_bundle_and_explicit_caddyfile() -> None:
    relative = Path("dist") / f"diting-{FAKE_COMMIT}.tar.gz"
    bundle = ROOT / relative
    checksum = Path(f"{bundle}.sha256")
    bundle.parent.mkdir(exist_ok=True)
    bundle.write_bytes(b"dry-run")
    checksum.write_text("dry-run\n", encoding="utf-8")
    try:
        process = subprocess.run(
            [
                "bash",
                "scripts/deploy.sh",
                "stage",
                "--host",
                "deploy.example",
                "--bundle",
                relative.as_posix(),
                "--caddy-config",
                "config/Caddyfile.v080.example",
                "--dry-run",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        bundle.unlink(missing_ok=True)
        checksum.unlink(missing_ok=True)

    assert process.returncode == 0, process.stderr
    assert "scp" in process.stdout
    assert " prepare " in process.stdout
    assert "Caddyfile.v080.example" in process.stdout


def test_remote_driver_requires_candidate_verification_and_preserves_rollback() -> None:
    source = _read("scripts/vps-deploy-v080.sh")

    assert "UV_VERSION=0.11.32" in source
    assert "useradd --system" in source
    assert "candidate-data" in source
    assert 'install -d -m 0710 -o root -g diting "$DEPLOYMENT_ROOT"' in source
    assert 'install -d -m 0710 -o root -g diting "$deployment"' in source
    assert 'install -d -m 0700 -o diting -g diting "$candidate_data"' in source
    assert "wait_ready 8101" in source
    assert 'require_file "$deployment/verified"' in source
    assert 'require_file "$deployment/rollback-rehearsed"' in source
    assert "database restore rehearsal mismatch" in source
    assert "promote-diting.db" in source
    assert "caddy validate" in source
    assert 'rollback "$commit"' in source
    assert "observe_seconds" in source
    assert "sha256sum --check" in source
    assert "incoming.backup(outgoing)" in source
    assert "PRAGMA integrity_check" in source


def test_service_and_caddy_reference_match_v080_topology() -> None:
    service = _read("config/diting-v080.service")
    caddy = _read("config/Caddyfile.v080.example")

    assert "User=diting" in service
    assert "--port 8100 --workers 1" in service
    assert "NoNewPrivileges=true" in service
    assert "ProtectSystem=strict" in service
    assert "ReadWritePaths=/var/lib/diting" in service
    assert "/api/diting/*" in caddy
    assert "rewrite * /api{uri}" in caddy
    assert "/opt/diting/current/frontend" in caddy


def test_production_report_path_is_a_strict_environment_override() -> None:
    config = _read("src/diting/config.py")

    assert '"DITING_REPORT_OUTPUT_DIR": ("report", "output_dir")' in config
