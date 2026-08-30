"""B04 — enveloppe d'événement et bus Redis Streams."""

from __future__ import annotations

import uuid

from shared.eventbus import EventConsumer, publish_event
from shared.events import EventEnvelope, Streams


def test_envelope_has_required_fields():
    env = EventEnvelope(
        event_type="strategy.proposal.created",
        correlation_id=uuid.uuid4(),
        execution_context_id=uuid.uuid4(),
        payload={"symbol": "AAPL"},
    )
    assert env.event_id is not None
    assert env.schema_version == 1
    assert env.occurred_at is not None
    assert env.payload == {"symbol": "AAPL"}


def test_dead_letter_naming_convention():
    assert Streams.dead_letter("order.commands") == "order.commands.dead-letter"


def test_publish_and_consume_roundtrip(redis_client):
    redis_client.flushdb()
    stream = "test.events"
    ctx_id = uuid.uuid4()
    corr_id = uuid.uuid4()
    env = EventEnvelope(
        event_type="test.event", correlation_id=corr_id, execution_context_id=ctx_id, payload={"k": "v"}
    )
    publish_event(redis_client, stream, env)

    consumer = EventConsumer(redis_client, stream=stream, group="test-group", consumer_name="c1")
    consumer.ensure_group()
    messages = list(consumer.read(count=10, block_ms=1000))

    assert len(messages) == 1
    assert messages[0].envelope.correlation_id == corr_id
    assert messages[0].envelope.payload == {"k": "v"}
    consumer.ack(messages[0].message_id)


def test_dead_letter_after_max_retries(redis_client):
    redis_client.flushdb()
    stream = "test.events.retry"
    env = EventEnvelope(
        event_type="test.event",
        correlation_id=uuid.uuid4(),
        execution_context_id=uuid.uuid4(),
        payload={},
    )
    publish_event(redis_client, stream, env)

    consumer = EventConsumer(redis_client, stream=stream, group="g", consumer_name="c1", max_retries=1)
    consumer.ensure_group()
    msg = next(iter(consumer.read(count=1, block_ms=1000)))

    consumer.fail(msg.message_id, delivery_count=1)  # atteint max_retries -> dead-letter

    assert redis_client.xlen(consumer.dead_letter_stream) == 1
