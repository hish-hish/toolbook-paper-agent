"""两级原文核验（D11）：摘录走机械子串匹配，归纳走 LLM 逐句裁判 + 依据机械复核。

本项目的招牌防线：只返回核验通过的内容，宁缺勿错。
"""
import re
import unicodedata

# 中英标点统一映射：比对前归一化，避免"内容全对却因标点判失败"
_PUNCT_MAP = str.maketrans({
    "，": ",", "。": ".", "！": "!", "？": "?", "；": ";", "：": ":",
    "（": "(", "）": ")", "【": "[", "】": "]", "“": '"', "”": '"',
    "‘": "'", "’": "'", "、": ",", "－": "-", "—": "-", "～": "~",
})


def normalize(text: str) -> str:
    """核验归一化：NFKC 全半角统一、中英标点统一、转小写、去掉全部空白。"""
    t = unicodedata.normalize("NFKC", text)
    t = t.translate(_PUNCT_MAP).lower()
    return re.sub(r"\s+", "", t)


def mechanical_ok(excerpt: str, source: str) -> bool:
    """机械核验：归一化后摘录必须是原文的子串（零误差、零成本）。"""
    e = normalize(excerpt)
    return bool(e) and e in normalize(source)


# 中英文句末标点拆句（与分块模块同一套切分哲学）
_SENT_SPLIT = re.compile(r"(?<=[。！？；.!?;])\s*")


def split_sentences(text: str) -> list[str]:
    """把答案拆成句子（按中英文句末标点），供逐句核验。"""
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]