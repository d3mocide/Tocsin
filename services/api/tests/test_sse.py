import asyncio

from api.sse import Broadcaster


async def test_subscribe_receives_published_items():
    hub = Broadcaster()
    queue = hub.subscribe()

    await hub.publish({"id": "a1"})

    item = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert item == {"id": "a1"}


async def test_multiple_subscribers_all_receive_the_same_item():
    hub = Broadcaster()
    q1 = hub.subscribe()
    q2 = hub.subscribe()

    await hub.publish({"id": "a1"})

    assert await asyncio.wait_for(q1.get(), timeout=1.0) == {"id": "a1"}
    assert await asyncio.wait_for(q2.get(), timeout=1.0) == {"id": "a1"}


async def test_unsubscribed_queue_receives_nothing_further():
    hub = Broadcaster()
    queue = hub.subscribe()
    hub.unsubscribe(queue)

    await hub.publish({"id": "a1"})

    assert queue.empty()


async def test_publish_with_no_subscribers_does_not_raise():
    hub = Broadcaster()
    await hub.publish({"id": "a1"})  # must not raise
