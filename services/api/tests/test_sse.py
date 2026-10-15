import asyncio

from api.sse import EVENT_ALERT, EVENT_HEALTH, Broadcaster, format_sse


async def test_subscribe_receives_published_items():
    hub = Broadcaster()
    queue = hub.subscribe()

    await hub.publish(EVENT_ALERT, {"id": "a1"})

    item = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert item == (EVENT_ALERT, {"id": "a1"})


async def test_multiple_subscribers_all_receive_the_same_item():
    hub = Broadcaster()
    q1 = hub.subscribe()
    q2 = hub.subscribe()

    await hub.publish(EVENT_ALERT, {"id": "a1"})

    assert await asyncio.wait_for(q1.get(), timeout=1.0) == (EVENT_ALERT, {"id": "a1"})
    assert await asyncio.wait_for(q2.get(), timeout=1.0) == (EVENT_ALERT, {"id": "a1"})


async def test_unsubscribed_queue_receives_nothing_further():
    hub = Broadcaster()
    queue = hub.subscribe()
    hub.unsubscribe(queue)

    await hub.publish(EVENT_ALERT, {"id": "a1"})

    assert queue.empty()


async def test_publish_with_no_subscribers_does_not_raise():
    hub = Broadcaster()
    await hub.publish(EVENT_ALERT, {"id": "a1"})  # must not raise


async def test_event_types_are_preserved_per_message():
    hub = Broadcaster()
    queue = hub.subscribe()

    await hub.publish(EVENT_ALERT, {"id": "a1"})
    await hub.publish(EVENT_HEALTH, {"site": "home"})

    assert await asyncio.wait_for(queue.get(), timeout=1.0) == (EVENT_ALERT, {"id": "a1"})
    assert await asyncio.wait_for(queue.get(), timeout=1.0) == (EVENT_HEALTH, {"site": "home"})


async def test_a_slow_subscriber_drops_its_oldest_message_rather_than_growing():
    """A client that stops reading must not be able to grow the process's
    memory -- and when it does fall behind, it should lose the stale
    messages, not the current one."""
    hub = Broadcaster(max_queue=2)
    queue = hub.subscribe()

    for n in range(5):
        await hub.publish(EVENT_ALERT, {"id": n})

    assert queue.qsize() == 2
    assert await queue.get() == (EVENT_ALERT, {"id": 3})
    assert await queue.get() == (EVENT_ALERT, {"id": 4})


def test_format_sse_emits_a_named_event():
    formatted = format_sse(EVENT_HEALTH, {"site": "home", "dead": True})

    assert formatted.startswith("event: health\ndata: ")
    assert formatted.endswith("\n\n")
    assert '"dead": true' in formatted


async def test_messages_carry_increasing_ids_and_still_compare_as_plain_tuples():
    hub = Broadcaster()
    queue = hub.subscribe()
    await hub.publish(EVENT_ALERT, {"id": "a"})
    await hub.publish(EVENT_ALERT, {"id": "b"})
    first, second = await queue.get(), await queue.get()
    assert first == (EVENT_ALERT, {"id": "a"}) and second.id == first.id + 1


async def test_reconnect_with_last_event_id_replays_missed_alerts_but_not_health():
    hub = Broadcaster()
    await hub.publish(EVENT_ALERT, {"id": "old"})
    seen = hub.subscribe()
    await hub.publish(EVENT_ALERT, {"id": "missed1"})
    await hub.publish(EVENT_HEALTH, {"site": "home"})
    await hub.publish(EVENT_ALERT, {"id": "missed2"})
    last_seen = (await seen.get()).id                       # saw "missed1" live, then dropped off
    replay = hub.subscribe(last_event_id=last_seen)
    got = [replay.get_nowait() for _ in range(replay.qsize())]
    assert [m[1]["id"] for m in got] == ["missed2"]        # health is never replayed


async def test_history_is_bounded():
    hub = Broadcaster(history=3)
    for n in range(10):
        await hub.publish(EVENT_ALERT, {"id": n})
    replay = hub.subscribe(last_event_id=0)
    assert [replay.get_nowait()[1]["id"] for _ in range(replay.qsize())] == [7, 8, 9]


def test_format_sse_includes_the_id_when_given():
    assert format_sse(EVENT_ALERT, {"a": 1}, 42).startswith("id: 42\nevent: alert\n")
    assert not format_sse(EVENT_ALERT, {"a": 1}).startswith("id:")
