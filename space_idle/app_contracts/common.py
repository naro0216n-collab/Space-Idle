from __future__ import annotations
from dataclasses import dataclass

class ApplicationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

@dataclass(frozen=True)
class CommandResult:
    created_id: str | None = None
