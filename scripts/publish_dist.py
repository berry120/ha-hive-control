"""Commit tested artifacts on main without overwriting a newer source commit."""

import argparse
import shutil
import subprocess
from pathlib import Path

FILES = ("hive-local-control.zip", "preview.html")


def git(repository, *args, check=True):
    return subprocess.run(
        ["git", *args], cwd=repository, text=True, capture_output=True, check=check
    )


def publish(repository, artifacts, source_sha):
    repository, artifacts = Path(repository).resolve(), Path(artifacts).resolve()
    if git(repository, "rev-parse", "HEAD").stdout.strip() != source_sha:
        print("Main has changed since this build; leaving it to the newer workflow.")
        return False
    if git(repository, "branch", "--show-current").stdout.strip() != "main":
        raise RuntimeError("Distribution updates must run on main")
    if git(repository, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        raise RuntimeError("Refusing to publish from a checkout with existing changes")
    for name in FILES:
        if not (artifacts / name).is_file() or (artifacts / name).is_symlink():
            raise RuntimeError(f"Missing regular artifact file: {name}")
    (repository / "dist").mkdir(exist_ok=True)
    for name in FILES:
        shutil.copyfile(artifacts / name, repository / "dist" / name)
    git(repository, "add", "--", *(f"dist/{name}" for name in FILES))
    if git(repository, "diff", "--cached", "--quiet", check=False).returncode == 0:
        print("Distribution is unchanged; no commit needed.")
        return False
    git(
        repository,
        "-c",
        "user.name=github-actions[bot]",
        "-c",
        "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "commit",
        "-m",
        "chore: update generated distribution",
    )
    pushed = git(repository, "push", "origin", "HEAD:refs/heads/main", check=False)
    if pushed.returncode:
        remote = git(
            repository, "ls-remote", "--exit-code", "origin", "refs/heads/main"
        ).stdout.split()[0]
        if remote != source_sha:
            print("Main changed during publishing; the newer workflow will update dist.")
            return False
        raise RuntimeError(
            "Could not push dist to main. Allow contents: write and bot pushes in branch rules.\n"
            + pushed.stderr
        )
    print("Updated dist/hive-local-control.zip and dist/preview.html on main.")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    publish(Path.cwd(), args.artifacts, args.source_sha)
