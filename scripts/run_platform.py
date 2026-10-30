"""Run the integrated local platform with persistent PostgreSQL and the backend .env.

Requires the existing backend virtual environment, npm dependencies, PostgreSQL
and Redis binaries. Local database files and logs stay in ignored .runtime/platform. No
credentials are copied to the frontend or printed. Ctrl-C stops services started here.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).absolute().parents[1]


def binary(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for prefix in (
        "/opt/homebrew/opt/postgresql@16/bin",
        "/usr/local/opt/postgresql@16/bin",
    ):
        path = Path(prefix) / name
        if path.is_file():
            return str(path)
    raise SystemExit(
        f"Missing {name}: add the required program's bin directory to PATH."
    )


def wait_http(url: str, process: subprocess.Popen, timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Service exited; inspect .runtime/platform logs.")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, TimeoutError):
            time.sleep(0.5)
    raise TimeoutError(f"Service readiness timed out: {url}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-port", type=int, default=18000)
    parser.add_argument("--web-port", type=int, default=5173)
    parser.add_argument("--db-port", type=int, default=55432)
    parser.add_argument("--redis-port", type=int, default=56379)
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    state = ROOT / ".runtime/platform"
    state.mkdir(parents=True, exist_ok=True)
    data = state / "postgres"
    python = ROOT / "backend/.venv/bin/python"
    if not python.is_file():
        raise SystemExit("Set up backend/.venv first; see backend/README.md.")
    pg_ctl = binary("pg_ctl")
    if not (data / "PG_VERSION").exists():
        subprocess.run(
            [binary("initdb"), "-D", str(data), "--auth=trust", "--encoding=UTF8"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    owns_pg = (
        subprocess.run(
            [pg_ctl, "-D", str(data), "status"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        != 0
    )
    children: list[subprocess.Popen] = []
    logs = []
    env = os.environ.copy()
    env.update(
        INDUSOPT_DATABASE_URL=f"postgresql+asyncpg://{getpass.getuser()}@127.0.0.1:{args.db_port}/indusopt_demo",
        INDUSOPT_ARTIFACT_ROOT=str(state / "artifacts"),
        INDUSOPT_REDIS_URL=f"redis://127.0.0.1:{args.redis_port}/0",
        INDUSOPT_BACKGROUND_OPTIMIZATION="false",
        VITE_API_TARGET=f"http://127.0.0.1:{args.api_port}",
    )

    def terminate(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    try:
        redis_log = (state / "redis.log").open("a")
        logs.append(redis_log)
        children.append(
            subprocess.Popen(
                [
                    binary("redis-server"),
                    "--bind",
                    "127.0.0.1",
                    "--port",
                    str(args.redis_port),
                    "--dir",
                    str(state),
                    "--appendonly",
                    "yes",
                ],
                stdout=redis_log,
                stderr=redis_log,
                start_new_session=True,
            )
        )
        if owns_pg:
            subprocess.run(
                [
                    pg_ctl,
                    "-D",
                    str(data),
                    "-l",
                    str(state / "postgres.log"),
                    "-o",
                    f"-p {args.db_port} -h 127.0.0.1",
                    "-w",
                    "start",
                ],
                check=True,
            )
        connection = ["-h", "127.0.0.1", "-p", str(args.db_port)]
        exists = subprocess.check_output(
            [
                binary("psql"),
                *connection,
                "-d",
                "postgres",
                "-tAc",
                "SELECT 1 FROM pg_database WHERE datname='indusopt_demo'",
            ],
            text=True,
        ).strip()
        if not exists:
            subprocess.run(
                [binary("createdb"), *connection, "indusopt_demo"], check=True
            )
        subprocess.run(
            [str(python), "-m", "alembic", "upgrade", "head"],
            cwd=ROOT / "backend",
            env=env,
            check=True,
        )
        if not args.skip_build:
            subprocess.run(
                [binary("npm"), "run", "build"],
                cwd=ROOT / "frontend",
                env=env,
                check=True,
            )
        for name, command, cwd in [
            (
                "api",
                [
                    str(python),
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.api_port),
                ],
                ROOT / "backend",
            ),
            (
                "web",
                [
                    binary("npm"),
                    "run",
                    "preview",
                    "--",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.web_port),
                    "--strictPort",
                ],
                ROOT / "frontend",
            ),
        ]:
            log = (state / f"{name}.log").open("a")
            logs.append(log)
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            children.append(process)
            wait_http(
                f"http://127.0.0.1:{args.api_port}/api/v1/health/ready"
                if name == "api"
                else f"http://127.0.0.1:{args.web_port}",
                process,
            )
        if children[0].poll() is not None:
            raise RuntimeError(
                "Dedicated Redis did not start; inspect redis.log and the configured port."
            )
        print(
            f"Platform ready: http://127.0.0.1:{args.web_port} (PostgreSQL migrated; .env loaded by backend)",
            flush=True,
        )
        while all(child.poll() is None for child in children):
            time.sleep(1)
        raise RuntimeError(
            "A platform service stopped; inspect .runtime/platform logs."
        )
    except KeyboardInterrupt:
        print("Stopping platform; persistent data retained.", flush=True)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
        for log in logs:
            log.close()
        if owns_pg:
            subprocess.run(
                [pg_ctl, "-D", str(data), "-m", "fast", "-w", "stop"], check=False
            )


if __name__ == "__main__":
    main()
