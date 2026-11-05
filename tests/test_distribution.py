"""Check reproducible builds and safe publication using local Git remotes only."""

import os
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.build import build
from scripts.publish_dist import FILES, git, publish

ROOT = Path(__file__).parents[1]


def test_build_is_repeatable_uses_fixed_names_and_excludes_development_files(tmp_path):
    for name in ("custom_components", "preview", "docs"):
        shutil.copytree(ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("README.md", "hive_zigbee_protocol_reference.md"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    component = tmp_path / "custom_components/hive_local"
    (component / "__pycache__").mkdir()
    (component / "__pycache__/ignored.pyc").write_bytes(b"ignored")
    output = build(tmp_path)
    original = output.read_bytes()
    preview = (tmp_path / "dist/preview.html").read_bytes()
    assert output.name == "hive-local-control.zip"
    assert set(p.name for p in output.parent.iterdir()) == set(FILES)
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        assert archive.namelist() == sorted(archive.namelist())
        assert "custom_components/hive_local/manifest.json" in archive.namelist()
        assert not any("__pycache__" in name or "tests/" in name for name in archive.namelist())
    for path in component.rglob("*.py"):
        path.write_bytes(path.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
        os.utime(path, (1_800_000_000, 1_800_000_000))
    assert build(tmp_path).read_bytes() == original
    assert (tmp_path / "dist/preview.html").read_bytes() == preview
    assert b'from "../custom_components/' not in preview
    assert b"Boost temperature can be found in settings." in preview


@pytest.fixture
def repository(tmp_path):
    remote, checkout, artifacts = (tmp_path / name for name in ("origin.git", "checkout", "built"))
    git(tmp_path, "init", "--bare", "--initial-branch=main", str(remote))
    git(tmp_path, "clone", str(remote), str(checkout))
    git(checkout, "config", "user.name", "Test contributor")
    git(checkout, "config", "user.email", "test@example.invalid")
    (checkout / "source.txt").write_text("source\n", encoding="utf-8")
    for name in (".gitignore", ".gitattributes"):
        shutil.copyfile(ROOT / name, checkout / name)
    git(checkout, "add", "source.txt", ".gitignore", ".gitattributes")
    git(checkout, "commit", "-m", "Initial source")
    git(checkout, "push", "origin", "main")
    artifacts.mkdir()
    for name in FILES:
        (artifacts / name).write_bytes(b"built artifact\n")
    return checkout, artifacts, git(checkout, "rev-parse", "HEAD").stdout.strip()


def test_publish_commits_only_artifacts_and_does_not_repeat_unchanged_build(repository):
    checkout, artifacts, source = repository
    assert publish(checkout, artifacts, source)
    commit = git(checkout, "rev-parse", "HEAD").stdout.strip()
    assert git(checkout, "ls-remote", "origin", "refs/heads/main").stdout.split()[0] == commit
    assert set(
        git(
            checkout, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
        ).stdout.splitlines()
    ) == {f"dist/{name}" for name in FILES}
    assert not publish(checkout, artifacts, commit)
    assert git(checkout, "rev-parse", "HEAD").stdout.strip() == commit


def test_stale_build_does_not_copy_or_push_artifacts(repository):
    checkout, artifacts, source = repository
    git(checkout, "commit", "--allow-empty", "-m", "Newer source")
    assert not publish(checkout, artifacts, source)
    assert not (checkout / "dist").exists()


def test_publisher_refuses_to_commit_unrelated_staged_changes(repository):
    checkout, artifacts, source = repository
    (checkout / "source.txt").write_text("work in progress\n", encoding="utf-8")
    git(checkout, "add", "source.txt")
    with pytest.raises(RuntimeError, match="existing changes"):
        publish(checkout, artifacts, source)
    assert not (checkout / "dist").exists()


def test_new_source_pushed_during_publication_is_never_overwritten(repository, monkeypatch):
    from scripts import publish_dist

    checkout, artifacts, source = repository
    other = checkout.parent / "other"
    git(checkout.parent, "clone", str(checkout.parent / "origin.git"), str(other))
    original = publish_dist.git

    def race_with_push(repository, *args, **kwargs):
        if args[0] == "push":
            (other / "source.txt").write_text("new source\n", encoding="utf-8")
            original(other, "add", "source.txt")
            original(
                other,
                "-c",
                "user.name=Test contributor",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-m",
                "New source",
            )
            original(other, "push", "origin", "main")
        return original(repository, *args, **kwargs)

    monkeypatch.setattr(publish_dist, "git", race_with_push)
    assert not publish(checkout, artifacts, source)
    remote = git(checkout, "ls-remote", "origin", "refs/heads/main").stdout.split()[0]
    assert remote == git(other, "rev-parse", "HEAD").stdout.strip()
    assert remote != git(checkout, "rev-parse", "HEAD").stdout.strip()


def test_rejected_push_reports_permission_failure(repository, monkeypatch):
    from scripts import publish_dist

    checkout, artifacts, source = repository
    original = publish_dist.git

    def reject_push(repository, *args, **kwargs):
        if args[0] == "push":
            return subprocess.CompletedProcess(args, 1, "", "Protected branch")
        return original(repository, *args, **kwargs)

    monkeypatch.setattr(publish_dist, "git", reject_push)
    with pytest.raises(RuntimeError, match="contents: write"):
        publish(checkout, artifacts, source)
