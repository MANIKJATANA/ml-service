# 0018 — Redis socket_timeout must exceed the XREADGROUP BLOCK window

Date: 2026-07-06

## Context

The inference worker crashed on startup in Docker with:

```
redis.exceptions.TimeoutError: Timeout reading from redis:6379
  ... adapters/queue/redis_streams.py:66 in consume  -> await self._redis.xreadgroup(..., block=5000)
ml-worker-1 exited with code 1
```

Root cause: **redis-py 8.x changed the default `socket_timeout` from `None` to
`5` seconds** (`redis/_defaults.py: DEFAULT_SOCKET_TIMEOUT = 5`). Our
`RedisStreamsJobQueue.consume()` does a blocking read `XREADGROUP ... BLOCK 5000`
(`block_ms=5000`, i.e. 5 s). redis-py does **not** extend the socket read timeout
to cover a command's server-side BLOCK window — `parse_response()` calls
`connection.read_response()` with no timeout, so it falls back to `socket_timeout`.
With both values at 5 s, every poll of an idle/empty stream races the 5 s socket
read timeout against the 5 s server BLOCK, and the socket timeout wins → a raised
`TimeoutError` (not the graceful `None` you get for a user-supplied timeout).

Secondary fragility (not fixed here): `WorkerRunner.run()` only wraps
`handle(lease)` in try/except, not the `async for ... in self._queue.consume()`,
so an error escaping `consume()` kills the worker (exit 1) despite the docstring
promising infra hiccups never stop the consumer.

## Decision

Build the Redis client with an explicit `socket_timeout` that comfortably exceeds
the queue's BLOCK window, plus TCP keepalive:

- New setting `redis_socket_timeout_s: float = 30.0` (`ML_REDIS_SOCKET_TIMEOUT_S`).
- `Container.redis()` now calls
  `Redis.from_url(url, socket_timeout=redis_socket_timeout_s, socket_keepalive=True)`.

30 s > the 5 s `block_ms`, so an empty stream now returns `None` from
`xreadgroup` and the consume loop idles as designed, while normal commands still
fail fast on a genuinely dead connection.

## Alternatives rejected

- `socket_timeout=None` (block forever): loses dead-connection detection on
  non-blocking commands; relies solely on TCP keepalive.
- Lowering `block_ms` below 5 s: fragile — couples the fix to redis-py's default
  and reintroduces the bug if the default changes again.

## Follow-up (not done)

Harden `WorkerRunner.run()` so a transient error from `consume()` is logged and
retried rather than crashing the worker, matching its docstring contract.
