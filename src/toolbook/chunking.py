import re

_SENT_SPLIT = re.compile(r"(?<=[。！？；.!?;])\s*")


def _sentences(text: str) -> list[str]:
    return [s for s in _SENT_SPLIT.split(text) if s.strip()]


def child_chunks(text: str, target: int = 300) -> list[str]:
    chunks: list[str] = []
    cur = ""
    for sent in _sentences(text.replace("\n", "")):
        if len(sent) > target * 2:
            if cur:
                chunks.append(cur)
                cur = ""
            for i in range(0, len(sent), target):
                chunks.append(sent[i:i + target])
            continue
        if cur and len(cur) + len(sent) > target:
            chunks.append(cur)
            cur = ""
        cur += sent
    if cur:
        chunks.append(cur)
    return chunks


def parent_parts(text: str, max_chars: int = 2000) -> list[str]:
    parts: list[str] = []
    cur = ""
    for para in text.split("\n"):
        if len(para) > max_chars:
            if cur:
                parts.append(cur)
                cur = ""
            for sent in _sentences(para):
                if cur and len(cur) + len(sent) > max_chars:
                    parts.append(cur)
                    cur = ""
                cur += sent
                while len(cur) > max_chars:
                    parts.append(cur[:max_chars])
                    cur = cur[max_chars:]
        elif cur and len(cur) + len(para) + 1 > max_chars:
            parts.append(cur)
            cur = para
        else:
            cur = cur + "\n" + para if cur else para
    if cur:
        parts.append(cur)
    return parts or [""]