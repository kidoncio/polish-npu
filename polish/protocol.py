"""Messages from the Polish daemon to the pill, one per line.

Standard library only: imported by both the daemon (venv Python 3.12 with
OpenVINO) and the pill (system Python with GTK4).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Working:
    pass


@dataclass(frozen=True)
class Done:
    message: str


@dataclass(frozen=True)
class Failed:
    message: str


@dataclass(frozen=True)
class Hide:
    pass


Message = Working | Done | Failed | Hide


def encode(msg: Message) -> str:
    match msg:
        case Working():
            body = "work"
        case Done(message):
            body = "done " + " ".join(message.split())
        case Failed(message):
            body = "fail " + " ".join(message.split())
        case Hide():
            body = "hide"
    return body + "\n"


def decode(line: str) -> Message | None:
    kind, _, rest = line.strip().partition(" ")
    match kind:
        case "work":
            return Working()
        case "done":
            return Done(rest)
        case "fail":
            return Failed(rest)
        case "hide":
            return Hide()
    return None
