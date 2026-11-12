"""Daemon → pill messages."""
from polish.protocol import Done, Failed, Hide, Working, decode, encode


def test_every_message_round_trips():
    for msg in (Working(), Done("Copiado — Ctrl+V"), Done("Pronto"), Failed("Erro: boom"), Hide()):
        assert decode(encode(msg)) == msg


def test_failed_message_is_flattened_to_one_line():
    assert decode(encode(Failed("Error:\n  line two"))) == Failed("Error: line two")


def test_garbage_decodes_to_none():
    assert decode("garbage") is None


def test_line_buffer_returns_every_complete_line():
    from polish.protocol import LineBuffer
    buf = LineBuffer()
    assert buf.feed(b"work\nfail Nada sele") == ["work"]
    assert buf.feed("cionado\nhide\n".encode()) == ["fail Nada selecionado", "hide"]
    assert buf.feed(b"") == []
