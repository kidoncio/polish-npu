"""Daemon → pill messages."""
from polish.protocol import Done, Failed, Hide, Working, decode, encode


def test_every_message_round_trips():
    for msg in (Working(), Done("Copiado — Ctrl+V"), Done("Pronto"), Failed("Erro: boom"), Hide()):
        assert decode(encode(msg)) == msg


def test_failed_message_is_flattened_to_one_line():
    assert decode(encode(Failed("Error:\n  line two"))) == Failed("Error: line two")


def test_garbage_decodes_to_none():
    assert decode("garbage") is None
