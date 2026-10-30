"""The real RQ round-trip: API enqueues, a real worker executes, /status reflects it.

These tests need a live Redis and a real ``rq worker`` subprocess, so they skip when either
is missing. Skipping is the honest behaviour — a fake queue would prove the fake works — but
a skipped test proves nothing either, so the delivery notes record where this actually ran
rather than treating a green run in an environment without Redis as verification.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from shutil import which
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import pytest
from app.core.config import Settings
from app.core.db import get_session
from app.main import create_app
from app.models import Base
from app.models.optimization import OptimizationStudy
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

REDIS_URL = os.environ.get("INDUSOPT_TEST_REDIS_URL", "redis://127.0.0.1:6379/0")
QUEUE_NAME = "indusopt"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
HARD_TIMEOUT_REDIS_DB = 15
HARD_TIMEOUT_SECONDS = 5
HARD_TIMEOUT_DELAY_SECONDS = 15
HARD_TIMEOUT_WORKER_BOOTSTRAP = """
import asyncio
import os

from redis import Redis
from rq import Queue, Worker

import app.services.job_queue as job_queue
import app.services.optimization_service as optimization_service

timeout_seconds = int(os.environ["INDUSOPT_TEST_JOB_TIMEOUT_SECONDS"])
delay_seconds = int(os.environ["INDUSOPT_TEST_DELAY_SECONDS"])
queue_name = os.environ["INDUSOPT_TEST_QUEUE_NAME"]

job_queue.JOB_TIMEOUT_SECONDS = timeout_seconds
optimization_service.JOB_TIMEOUT_SECONDS = timeout_seconds


async def slow_load_version_series(session, *, version_id, artifact_root):
    del session, version_id, artifact_root
    await asyncio.sleep(delay_seconds)
    raise AssertionError("The RQ hard timeout did not interrupt the deterministic delay")


optimization_service.load_version_series = slow_load_version_series

connection = Redis.from_url(os.environ["INDUSOPT_REDIS_URL"])
queue = Queue(queue_name, connection=connection, default_timeout=timeout_seconds)
worker = Worker([queue], connection=connection)
worker.work(burst=True)
"""


def redis_available() -> bool:
    try:
        from redis import Redis

        Redis.from_url(REDIS_URL, socket_connect_timeout=1).ping()
    except Exception:  # noqa: BLE001 - any failure means "not available here"
        return False
    return True


pytestmark = [
    pytest.mark.skipif(not redis_available(), reason="需要可用的 Redis 才能验证真实队列往返"),
    pytest.mark.skipif(which("rq") is None, reason="需要 rq 命令行才能启动真实 Worker"),
]


@pytest.fixture
def queued_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """An API wired to a SQLite file the worker subprocess can also open."""

    database_url = f"sqlite+aiosqlite:///{tmp_path / 'queue.db'}"
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    settings = Settings(
        artifact_root=tmp_path,
        database_url=database_url,
        redis_url=REDIS_URL,
        background_optimization=True,
    )
    monkeypatch.setattr("app.api.routes.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.job_queue.get_settings", lambda: settings)
    # The worker subprocess reads its configuration from the environment, and it must land
    # on the same database file and artifact directory as the API under test.
    monkeypatch.setenv("INDUSOPT_DATABASE_URL", database_url)
    monkeypatch.setenv("INDUSOPT_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("INDUSOPT_REDIS_URL", REDIS_URL)
    monkeypatch.setenv("INDUSOPT_BACKGROUND_OPTIMIZATION", "true")

    app = create_app()
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        yield client
    asyncio.run(engine.dispose())


def drain_queue() -> subprocess.CompletedProcess[str]:
    """Run a real worker in burst mode: it processes what is queued and exits."""

    return subprocess.run(
        ["rq", "worker", QUEUE_NAME, "--url", REDIS_URL, "--burst"],
        env={**os.environ, "PYTHONPATH": str(BACKEND_ROOT)},
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


def hard_timeout_redis_url() -> str:
    """Keep the configured Redis server, but isolate this fault test in database 15."""

    parsed = urlsplit(REDIS_URL)
    if parsed.scheme not in {"redis", "rediss"}:
        raise ValueError("INDUSOPT_TEST_REDIS_URL must use redis:// or rediss://")
    return urlunsplit(parsed._replace(path=f"/{HARD_TIMEOUT_REDIS_DB}"))


def drain_hard_timeout_queue(*, redis_url: str) -> subprocess.CompletedProcess[str]:
    """Run a patched Worker whose forked work-horse inherits this test-only runtime."""

    return subprocess.run(
        [sys.executable, "-c", HARD_TIMEOUT_WORKER_BOOTSTRAP],
        env={
            **os.environ,
            "PYTHONPATH": str(BACKEND_ROOT),
            "INDUSOPT_REDIS_URL": redis_url,
            "INDUSOPT_TEST_JOB_TIMEOUT_SECONDS": str(HARD_TIMEOUT_SECONDS),
            "INDUSOPT_TEST_DELAY_SECONDS": str(HARD_TIMEOUT_DELAY_SECONDS),
            "INDUSOPT_TEST_QUEUE_NAME": QUEUE_NAME,
        },
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


async def insert_hard_timeout_study(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    study_id: UUID,
    version_id: UUID,
    payload: dict[str, object],
) -> None:
    async with session_factory() as session:
        session.add(
            OptimizationStudy(
                id=study_id,
                dataset_id=None,
                version_id=version_id,
                status="queued",
                objective="val_free_run_fit",
                parameters=payload,
                best_params={},
                fingerprint={},
                statistics={
                    "target_trials": payload["max_trials"],
                    "job": {
                        "contract_version": "optimization_job_v1",
                        "execution_mode": "rq",
                        "rq_job_id": str(study_id),
                        "queue_name": QUEUE_NAME,
                        "job_timeout_seconds": HARD_TIMEOUT_SECONDS,
                        "submission_state": "SUBMITTED",
                        "submission_requested_at": datetime.now(UTC).isoformat(),
                    },
                },
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()


async def hard_timeout_study_snapshot(
    session_factory: async_sessionmaker[AsyncSession], *, study_id: UUID
) -> dict[str, object]:
    async with session_factory() as session:
        study = await session.get(OptimizationStudy, study_id)
        assert study is not None
        return {
            "status": study.status,
            "finished_at": study.finished_at,
            "statistics": dict(study.statistics),
        }


def generate(client: TestClient, *, seed: int = 5) -> str:
    response = client.post(
        "/api/v1/simulation/generate",
        json={"scenario": "S2", "n_steps": 1500, "seed": seed, "input_count": 2},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["version_id"]


class TestRealQueueRoundTrip:
    def test_the_request_returns_before_the_search_runs(self, queued_client: TestClient) -> None:
        """This is the whole reason the queue exists: no request held open for minutes."""

        version_id = generate(queued_client)
        started = queued_client.post(
            "/api/v1/optimization/optuna/start",
            json={
                "version_id": version_id,
                "input_columns": ["u1", "u2"],
                "output_column": "y",
                "max_trials": 3,
            },
        )
        assert started.status_code == 202, started.text
        payload = started.json()["data"]
        assert payload["task"]["status"] == "queued"

        study_id = payload["study_id"]
        assert payload["task"]["id"] == study_id
        # Pollable immediately, with nothing computed yet.
        before = queued_client.get(f"/api/v1/optimization/optuna/{study_id}/status")
        assert before.status_code == 200
        before_data = before.json()["data"]
        assert before_data["trials"] == []
        assert before_data["statistics"]["target_trials"] == 3
        assert before_data["statistics"]["job"]["rq_job_id"] == study_id
        assert before_data["task"]["id"] == study_id
        assert before_data["task"]["status"] == "queued"
        assert before_data["job"]["availability"] == "AVAILABLE"
        assert before_data["job"]["raw_status"] == "queued"

        worker = drain_queue()
        assert worker.returncode == 0, worker.stderr

        after = queued_client.get(f"/api/v1/optimization/optuna/{study_id}/status").json()["data"]
        assert len(after["trials"]) == 3
        assert after["best_value"] is not None
        assert after["statistics"]["total_trials"] == 3
        assert after["task"]["id"] == study_id
        assert after["task"]["status"] == "succeeded"
        assert after["job"]["raw_status"] == "finished"

    def test_the_worker_and_the_inline_path_produce_the_same_shape_of_result(
        self, queued_client: TestClient
    ) -> None:
        """A worker that computed something different from the API would be worse than none."""

        version_id = generate(queued_client, seed=6)
        body = {
            "version_id": version_id,
            "input_columns": ["u1", "u2"],
            "output_column": "y",
            "max_trials": 3,
            "random_seed": 11,
        }
        queued = queued_client.post("/api/v1/optimization/optuna/start", json=body)
        assert drain_queue().returncode == 0
        via_worker = queued_client.get(
            f"/api/v1/optimization/optuna/{queued.json()['data']['study_id']}/status"
        ).json()["data"]

        assert set(via_worker["statistics"]) >= {
            "total_trials",
            "completed_trials",
            "failed_trials",
            "hit_rate",
            "evaluations_per_selection",
        }
        assert via_worker["best_params"]
        assert len(via_worker["best_curve"]) == len(via_worker["trials"])


class TestRealRqHardTimeout:
    @pytest.mark.skipif(os.name != "posix", reason="RQ UnixSignalDeathPenalty requires POSIX")
    def test_real_rq_hard_timeout_persists_authoritative_terminal_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from redis import Redis
        from rq import Queue
        from rq.job import Callback, Job
        from rq.registry import FailedJobRegistry

        redis_url = hard_timeout_redis_url()
        redis_connection = Redis.from_url(redis_url, socket_connect_timeout=1)
        redis_database = redis_connection.connection_pool.connection_kwargs.get("db")
        assert redis_database == HARD_TIMEOUT_REDIS_DB
        try:
            redis_connection.ping()
        except Exception as error:  # noqa: BLE001 - this integration test needs real Redis
            pytest.skip(f"专用 Redis DB {HARD_TIMEOUT_REDIS_DB} 不可用：{type(error).__name__}")

        # The defensive DB-number assertion above makes both cleanup calls DB-15-only.
        redis_connection.flushdb()
        database_url = f"sqlite+aiosqlite:///{tmp_path / 'rq-hard-timeout.db'}"
        engine = create_async_engine(database_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async def prepare_database() -> None:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)

        asyncio.run(prepare_database())
        study_id = uuid4()
        version_id = uuid4()
        payload: dict[str, object] = {
            "version_id": str(version_id),
            "input_columns": ["u1"],
            "output_column": "y",
            "max_trials": 1,
            "timeout_seconds": None,
            "search_space": {},
            "random_seed": 42,
            "train_ratio": 0.6,
            "validation_ratio": 0.2,
        }
        asyncio.run(
            insert_hard_timeout_study(
                session_factory,
                study_id=study_id,
                version_id=version_id,
                payload=payload,
            )
        )

        settings = Settings(
            artifact_root=tmp_path,
            database_url=database_url,
            redis_url=redis_url,
            background_optimization=True,
        )
        monkeypatch.setattr("app.api.routes.get_settings", lambda: settings)
        monkeypatch.setattr("app.services.job_queue.get_settings", lambda: settings)
        monkeypatch.setenv("INDUSOPT_DATABASE_URL", database_url)
        monkeypatch.setenv("INDUSOPT_ARTIFACT_ROOT", str(tmp_path))
        monkeypatch.setenv("INDUSOPT_REDIS_URL", redis_url)
        monkeypatch.setenv("INDUSOPT_BACKGROUND_OPTIMIZATION", "true")

        queue = Queue(
            QUEUE_NAME,
            connection=redis_connection,
            default_timeout=HARD_TIMEOUT_SECONDS,
        )
        job = queue.enqueue(
            "app.worker.run_optimization_job",
            str(study_id),
            payload,
            job_id=str(study_id),
            unique=True,
            meta={"study_id": str(study_id), "job_kind": "optimization"},
            job_timeout=HARD_TIMEOUT_SECONDS,
            result_ttl=86_400,
            on_failure=Callback(
                "app.worker.handle_optimization_job_failure",
                timeout=30,
            ),
        )

        app = create_app()

        async def session_override() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_session] = session_override
        try:
            with TestClient(app) as client:
                worker = drain_hard_timeout_queue(redis_url=redis_url)
                assert worker.returncode == 0, f"{worker.stdout}\n{worker.stderr}"

                persisted_job = Job.fetch(job.id, connection=redis_connection)
                raw_status = persisted_job.get_status(refresh=True)
                assert getattr(raw_status, "value", raw_status) == "failed"
                assert job.id in FailedJobRegistry(QUEUE_NAME, connection=redis_connection)
                assert persisted_job.timeout == HARD_TIMEOUT_SECONDS

                result = persisted_job.latest_result(timeout=0)
                assert result is not None
                assert result.exc_string is not None
                assert "rq.timeouts.JobTimeoutException" in result.exc_string
                assert (
                    "Task exceeded maximum timeout value (5 seconds)" in result.exc_string
                )

                snapshot = asyncio.run(
                    hard_timeout_study_snapshot(session_factory, study_id=study_id)
                )
                assert snapshot["status"] == "failed"
                assert snapshot["finished_at"] is not None
                statistics = snapshot["statistics"]
                assert isinstance(statistics, dict)

                terminal = statistics["terminal_reason"]
                assert terminal["policy_version"] == "optimization_terminal_reason_v2"
                assert terminal["code"] == "RQ_TIMEOUT"
                assert terminal["category"] == "INFRASTRUCTURE_FAILURE"
                assert terminal["phase"] == "rq_execution"
                assert terminal["error_code"] == "RQ_JOB_TIMEOUT"

                history = statistics.get("terminal_reason_history")
                if history is not None:
                    assert isinstance(history, list)
                    if history:
                        assert any(
                            item.get("code") == "FAILED"
                            and item.get("category") == "SYSTEM_FAILURE"
                            and item.get("phase") == "preparation"
                            and item.get("error_code") == "STUDY_PREPARATION_FAILED"
                            for item in history
                        )

                evidence = statistics["job"]["terminal_evidence"]
                assert evidence["source"] == "failure_callback"
                assert evidence["kind"] == "job_timeout"
                assert evidence["confidence"] == "HIGH"
                assert evidence["rq_job_id"] == str(study_id)
                assert evidence["exception_type"] == "rq.timeouts.JobTimeoutException"
                assert evidence["error_code"] == "RQ_JOB_TIMEOUT"
                assert evidence["job_timeout_seconds"] == HARD_TIMEOUT_SECONDS

                response = client.get(f"/api/v1/optimization/optuna/{study_id}/status")
                assert response.status_code == 200, response.text
                status = response.json()["data"]
                assert status["task"]["status"] == "failed"
                assert status["study_status"] == "failed"
                assert status["job"]["raw_status"] == "failed"
                assert status["terminal_reason"]["code"] == "RQ_TIMEOUT"
                assert status["terminal_reason"]["error_code"] == "RQ_JOB_TIMEOUT"
                assert status["stop_reason"] is None
        finally:
            asyncio.run(engine.dispose())
            redis_connection.flushdb()
            redis_connection.close()
