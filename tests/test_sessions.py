from nestbox.core.sessions import SessionStore


async def test_roundtrip(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    key = SessionStore.key(-100123, 45)
    await store.set(key, "sid-1", "web")
    record = await store.get(key)
    assert record is not None
    assert record.session_id == "sid-1"
    assert record.agent == "web"


async def test_persists_across_instances(tmp_path):
    path = tmp_path / "sessions.json"
    key = SessionStore.key(1, None)
    await SessionStore(path).set(key, "sid-2", "main")
    record = await SessionStore(path).get(key)
    assert record is not None and record.session_id == "sid-2"


async def test_drop(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    key = SessionStore.key(1, 2)
    await store.set(key, "sid", "main")
    assert await store.drop(key) is True
    assert await store.drop(key) is False
    assert await store.get(key) is None


def test_key_shape():
    assert SessionStore.key(-100, None) == "-100:0"
    assert SessionStore.key(-100, 7) == "-100:7"
