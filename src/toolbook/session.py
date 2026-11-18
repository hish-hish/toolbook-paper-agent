"""会话上下文记忆：模块A 最近 5 轮截断；模块B 每篇论文独立、超阈值自动压缩。

历史只供查询改写与理解问题（指代/追问），绝不作为答案依据。
"""
from dataclasses import dataclass

from . import llm


@dataclass
class Turn:
    """一轮问答：问题 + 答案要点（核验句拼接或拒答原因，截断 400 字）。"""
    question: str
    answer: str


class Conversation:
    """一段会话的记忆：max_turns 截断；compress_threshold>0 时超阈值把旧轮压缩进 digest。"""

    def __init__(self, max_turns: int = 5, compress_threshold: int = 0,
                 keep_recent: int = 3):
        self.max_turns = max_turns
        self.compress_threshold = compress_threshold  # 0=不压缩（模块A）
        self.keep_recent = keep_recent
        self.turns: list[Turn] = []
        self.digest: str = ""

    def add(self, question: str, answer: str):
        """记一轮；超压缩阈值先压缩旧轮，再按 max_turns 截断。"""
        self.turns.append(Turn(question, answer[:400]))
        if self.compress_threshold and len(self.turns) > self.compress_threshold:
            self._compress()
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]

    def _compress(self):
        """除最近 keep_recent 轮外压缩进 digest；LLM 失败回退旧轮原文拼接。"""
        old = self.turns[:-self.keep_recent]
        self.turns = self.turns[-self.keep_recent:]
        text = "\n".join(f"问: {t.question}\n答: {t.answer}" for t in old)
        try:
            summary = llm.summarize_turns(text)
        except Exception:
            summary = ""
        joined = "\n".join(p for p in (self.digest, summary or text) if p)
        self.digest = joined[-800:]

    def context(self) -> str:
        """供改写/生成的上下文文本：早期摘要 + 最近轮次；无历史返回空串。"""
        if not self.turns and not self.digest:
            return ""
        parts = []
        if self.digest:
            parts.append(f"早期对话要点: {self.digest}")
        parts += [f"问: {t.question}\n答: {t.answer}" for t in self.turns]
        return "\n".join(parts)[:2000]

    def clear(self):
        """清空本会话记忆。"""
        self.turns = []
        self.digest = ""