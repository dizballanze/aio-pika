import asyncio

import aiormq
import pytest
from contextlib import suppress

from aio_pika import connect_robust
from aio_pika.robust_channel import RobustChannel
from aio_pika.robust_connection import RobustConnection
from aio_pika.robust_queue import RobustQueue
from tests import AMQP_URL
from tests.test_amqp import TestCase as AMQPTestCase


pytestmark = pytest.mark.asyncio


class TestCase(AMQPTestCase):
    async def create_connection(self, cleanup=True):
        client = await connect_robust(str(AMQP_URL), loop=self.loop)

        if cleanup:
            self.addCleanup(client.close)

        return client

    async def test_set_qos(self):
        channel = await self.create_channel()
        await channel.set_qos(prefetch_count=1)

    async def test_revive_passive_queue_on_reconnect(self):
        client1 = await self.create_connection()
        self.assertIsInstance(client1, RobustConnection)

        client2 = await self.create_connection()
        self.assertIsInstance(client2, RobustConnection)

        reconnect_event = asyncio.Event()
        reconnect_count = 0

        def reconnect_callback(conn):
            nonlocal reconnect_count
            reconnect_count += 1
            reconnect_event.set()
            reconnect_event.clear()

        client2.add_reconnect_callback(reconnect_callback)

        queue_name = self.get_random_name()
        channel1 = await client1.channel()
        self.assertIsInstance(channel1, RobustChannel)

        channel2 = await client2.channel()
        self.assertIsInstance(channel2, RobustChannel)

        queue1 = await self.declare_queue(
            queue_name,
            auto_delete=False,
            passive=False,
            channel=channel1
        )
        self.assertIsInstance(queue1, RobustQueue)

        queue2 = await self.declare_queue(
            queue_name,
            passive=True,
            channel=channel2
        )
        self.assertIsInstance(queue2, RobustQueue)

        await client2.connection.close(aiormq.AMQPError(320, 'Closed'))

        await reconnect_event.wait()

        self.assertEqual(reconnect_count, 1)

        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(
                reconnect_event.wait(),
                client2.reconnect_interval * 2
            )

        self.assertEqual(reconnect_count, 1)
