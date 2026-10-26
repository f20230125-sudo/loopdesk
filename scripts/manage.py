"""Portable commands with project-local caches and temporary files on the project drive."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]


def local_environment():
    local = ROOT / ".local"
    paths = {"TEMP": local / "temp", "TMP": local / "temp", "TMPDIR": local / "temp",
             "PIP_CACHE_DIR": local / "pip-cache", "npm_config_cache": local / "npm-cache",
             "XDG_CACHE_HOME": local / "cache", "PYTHONPYCACHEPREFIX": local / "pycache"}
    env = os.environ.copy()
    for key, path in paths.items():
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    return env


def run(args, env):
    return subprocess.run(args, cwd=ROOT, env=env).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "migrate", "test", "test-postgres", "browser", "record", "package"])
    args = parser.parse_args()
    env = local_environment()
    python = str(ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    if not Path(python).is_file():
        parser.error("Create .venv and install requirements-dev.txt first. See README.md.")
    if args.command == "run":
        status = run([python, "-m", "flask", "--app", "app", "migrate"], env)
        return status or run([python, "app.py"], env)
    if args.command == "migrate":
        return run([python,"-m","flask","--app","app","migrate"], env)
    if args.command in {"test", "test-postgres"}:
        if args.command == "test-postgres" and not env.get("LOOPDESK_TEST_DATABASE_URL"):
            parser.error("Set LOOPDESK_TEST_DATABASE_URL to a dedicated PostgreSQL test database before running this command.")
        if args.command == "test":
            env.pop("LOOPDESK_TEST_DATABASE_URL", None)
        backend = "postgres" if args.command == "test-postgres" else "sqlite"
        temp = ROOT / ".local" / ("pytest-" + uuid.uuid4().hex)
        return run([python,"-m","pytest","-q",f"--basetemp={temp}",f"--junitxml=artifacts/pytest-{backend}.xml"], env)
    if args.command in {"browser", "record"}:
        return run(["node", "scripts/" + ("browser-check.mjs" if args.command == "browser" else "record-demo.mjs")], env)
    return run([python,"scripts/package-release.py"], env)


if __name__ == "__main__":
    raise SystemExit(main())
