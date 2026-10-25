"""Buffered exact encoder for the private History audit typed-hash protocol."""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Iterable
from typing import Any


class _BroadcastBuffer:
    def __init__(self, targets, limit: int) -> None:
        self.targets, self.limit = targets, limit
        self.parts: list[bytes] = []
        self.size = 0

    def write(self, payload: bytes) -> None:
        if self.size + len(payload) > self.limit:
            self.flush()
        if len(payload) >= self.limit:
            for target in self.targets:
                target.update(payload)
        else:
            self.parts.append(payload)
            self.size += len(payload)

    def put(self, payload: bytes) -> None:
        self.write(struct.pack(">Q", len(payload)))
        self.write(payload)

    def flush(self) -> None:
        if self.parts:
            chunk = b"".join(self.parts)
            for target in self.targets:
                target.update(chunk)
            self.parts.clear()
            self.size = 0


class TypedHash:
    """Incrementally hash typed values without materializing a canonical tree."""

    def __init__(self, *, buffer_bytes: int = 64 * 1024) -> None:
        if buffer_bytes < 1:
            raise ValueError("buffer_bytes must be positive")
        self._hash = hashlib.sha256()
        self._buffer_bytes = buffer_bytes

    def _encoder(self, mirrors: Iterable[TypedHash]) -> _BroadcastBuffer:
        targets = (self, *tuple(mirrors))
        return _BroadcastBuffer(tuple(target._hash for target in targets), self._buffer_bytes)

    @classmethod
    def _logical(cls, encoder: _BroadcastBuffer, value: Any) -> None:
        if type(value) is dict:
            encoder.write(b"D")
            encoder.put(str(len(value)).encode())
            for key in sorted(value):
                encoder.put(key.encode())
                cls._logical(encoder, value[key])
        elif type(value) in (list, tuple):
            encoder.write(b"L" if type(value) is list else b"T")
            encoder.put(str(len(value)).encode())
            for item in value:
                cls._logical(encoder, item)
        else:
            cls._raw(encoder, value, framed=True)

    @classmethod
    def _raw(cls, encoder: _BroadcastBuffer, value: Any, *, framed: bool) -> None:
        if value is None:
            parts = (b"N",)
        elif type(value) is bool:
            parts = (b"B1" if value else b"B0",)
        elif type(value) is int:
            parts = (b"I", str(value).encode("ascii"))
        elif type(value) is float:
            parts = (b"F", struct.pack(">d", value))
        elif type(value) is str:
            parts = (b"S", value.encode())
        elif type(value) is bytes:
            parts = (b"Y", value)
        elif type(value) in (dict, list, tuple):
            nested = TypedHash(buffer_bytes=encoder.limit)
            nested.update(value)
            parts = (b"C", nested.digest())
        else:
            raise TypeError(type(value))
        if framed:
            encoder.write(struct.pack(">Q", sum(map(len, parts))))
        for part in parts:
            encoder.write(part)

    def put(self, payload: bytes, *, mirrors: Iterable[TypedHash] = ()) -> None:
        encoder = self._encoder(mirrors)
        encoder.put(payload)
        encoder.flush()

    def write(self, payload: bytes, *, mirrors: Iterable[TypedHash] = ()) -> None:
        encoder = self._encoder(mirrors)
        encoder.write(payload)
        encoder.flush()

    def update(self, value: Any, *, mirrors: Iterable[TypedHash] = ()) -> None:
        encoder = self._encoder(mirrors)
        self._logical(encoder, value)
        encoder.flush()

    def update_raw(self, value: Any, *, mirrors: Iterable[TypedHash] = ()) -> None:
        encoder = self._encoder(mirrors)
        self._raw(encoder, value, framed=True)
        encoder.flush()

    def update_many(self, values: Iterable[Any]) -> None:
        encoder = self._encoder(())
        for value in values:
            self._logical(encoder, value)
        encoder.flush()

    def digest(self) -> bytes:
        return self._hash.digest()

    def hexdigest(self) -> str:
        return self._hash.hexdigest()


def typed_digest(value: Any) -> bytes:
    result = TypedHash()
    result.update(value)
    return result.digest()
