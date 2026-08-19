from __future__ import annotations

import json
import threading

import pytest

from app.domain.models import ServerSpec
from app.repository.server_repository import ServerRepository


class _RecordingLock:
    """Wraps a real RLock and tracks whether it's currently held, so instrumented
    calls to _load_unlocked/_save_unlocked can assert they only ever run while a
    public writer method is holding this exact lock instance. Deterministic and
    single-threaded — no timing dependency."""

    def __init__(self) -> None:
        self._real = threading.RLock()
        self.held = False

    def acquire(self, *args, **kwargs):
        result = self._real.acquire(*args, **kwargs)
        if result:
            self.held = True
        return result

    def release(self) -> None:
        self.held = False
        self._real.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False


def make_servers():
    return [
        ServerSpec(id="s1", cpu_units_per_tick=10, mem_mb=1024, rate_limit_per_sec=2),
        ServerSpec(id="s2", cpu_units_per_tick=5, mem_mb=512, rate_limit_per_sec=1),
    ]


def test_save_then_load_round_trips(tmp_path):
    repo = ServerRepository(tmp_path / "servers.json")
    servers = make_servers()
    repo.save(servers)
    loaded = repo.load()
    assert loaded == servers


def test_save_is_atomic_no_temp_file_left_on_success(tmp_path):
    repo = ServerRepository(tmp_path / "servers.json")
    repo.save(make_servers())
    leftovers = list(tmp_path.glob(".servers-*"))
    assert leftovers == []


def test_save_failure_leaves_original_file_untouched(tmp_path, monkeypatch):
    path = tmp_path / "servers.json"
    repo = ServerRepository(path)
    repo.save(make_servers())
    original_bytes = path.read_bytes()

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(json, "dump", boom)
    with pytest.raises(RuntimeError):
        repo.save([ServerSpec(id="s3", cpu_units_per_tick=1, mem_mb=1, rate_limit_per_sec=1)])

    assert path.read_bytes() == original_bytes
    assert list(tmp_path.glob(".servers-*")) == []


def test_all_public_writers_hold_the_lock_around_load_and_save(tmp_path):
    """The deterministic proof (no threading, no timing): swap in a recording lock
    and assert _load_unlocked/_save_unlocked are only ever called while it's held,
    across save(), create(), update(), and delete() — i.e. every public writer
    enters the same lock for its whole read-modify-write cycle. load() is
    intentionally excluded: by design (D-015) it calls _load_unlocked without the
    lock, since os.replace() atomicity already makes plain reads safe."""
    repo = ServerRepository(tmp_path / "servers.json")
    repo.save([])  # baseline write via the real lock, before swapping it out

    recording_lock = _RecordingLock()
    repo._lock = recording_lock

    real_load_unlocked = repo._load_unlocked
    real_save_unlocked = repo._save_unlocked
    unlocked_load_calls: list[str] = []
    unlocked_save_calls: list[str] = []

    def checked_load_unlocked():
        if not recording_lock.held:
            unlocked_load_calls.append("load")
        return real_load_unlocked()

    def checked_save_unlocked(servers):
        if not recording_lock.held:
            unlocked_save_calls.append("save")
        real_save_unlocked(servers)

    repo._load_unlocked = checked_load_unlocked
    repo._save_unlocked = checked_save_unlocked

    repo.save([ServerSpec(id="s1", cpu_units_per_tick=1, mem_mb=1, rate_limit_per_sec=1)])
    repo.create(ServerSpec(id="s2", cpu_units_per_tick=1, mem_mb=1, rate_limit_per_sec=1))
    repo.update("s1", cpu_units_per_tick=9, mem_mb=9, rate_limit_per_sec=9)
    repo.delete("s2")

    assert unlocked_load_calls == [], "a public writer read without holding the shared lock"
    assert unlocked_save_calls == [], "a public writer wrote without holding the shared lock"

    repo._load_unlocked = real_load_unlocked
    repo._save_unlocked = real_save_unlocked
    remaining = repo.load()
    assert [s.id for s in remaining] == ["s1"]
    assert remaining[0].cpu_units_per_tick == 9


def test_concurrent_create_final_state_has_no_lost_update(tmp_path):
    """Best-effort stress check with real OS threads — not a standalone proof of
    exclusion (no artificial delay is used to widen a race window, and none is
    claimed here). The deterministic proof that every writer holds the lock is
    test_all_public_writers_hold_the_lock_around_load_and_save above. This test
    additionally builds confidence that two concurrent create() calls never lose
    an update under real threading."""
    repo = ServerRepository(tmp_path / "servers.json")
    repo.save([])

    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def worker(server_id: str) -> None:
        try:
            barrier.wait(timeout=5)
            repo.create(ServerSpec(id=server_id, cpu_units_per_tick=1, mem_mb=1, rate_limit_per_sec=1))
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=("s1",))
    t2 = threading.Thread(target=worker, args=("s2",))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not t1.is_alive() and not t2.is_alive(), "threads did not complete in time — possible deadlock"
    assert not errors, f"unexpected errors: {errors}"

    final_ids = {s.id for s in repo.load()}
    assert final_ids == {"s1", "s2"}, f"lost update: expected both servers persisted, got {final_ids}"
