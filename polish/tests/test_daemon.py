"""Daemon request handling that needs neither the NPU nor a desktop."""
import asyncio
import gc

from polish import daemon


def test_request_task_survives_garbage_collection(monkeypatch):
    app = daemon.Polish()
    finished = []

    async def fake_run(gen):
        await asyncio.sleep(0.05)
        gc.collect()
        await asyncio.sleep(0.05)
        finished.append(gen)
        app.busy.finish()

    monkeypatch.setattr(app, "_run", fake_run)

    async def go():
        assert app.request() == "start"
        gc.collect()
        await asyncio.sleep(0.3)

    asyncio.run(go())
    assert finished == [1]
    assert app._tasks == set()
