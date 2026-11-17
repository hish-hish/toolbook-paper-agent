from pathlib import Path
from typing import Protocol

from ..models import ParsedDocument


class Parser(Protocol):
    def parse(self, path: Path) -> ParsedDocument: ...