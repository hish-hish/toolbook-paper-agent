"""两级原文核验（D11）：摘录走机械子串匹配，归纳走 LLM 逐句裁判 + 依据机械复核。

本项目的招牌防线：只返回核验通过的内容，宁缺勿错。
"""
import json
import re
import unicodedata

from . import llm
from .models import VerifiedSentence

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


# --- 第二级：LLM 逐句裁判（管归纳句） ---

_JUDGE_SYSTEM = "你是原文核验裁判。判断给定句子是否有原文依据，只输出JSON，不要解释。"


def judge_sentence(sentence: str, source: str) -> dict | None:
    """LLM 裁判单句：返回 {"supported": bool, "quote": 原文依据}；任何失败返回 None。"""
    prompt = (f"原文：\n{source[:3000]}\n\n待核验句子：{sentence}\n"
              '若句子有原文依据，输出 {"supported": true, "quote": "支撑该句的原文连续片段（一字不差摘抄）"}；'
              '否则输出 {"supported": false, "quote": ""}。只输出JSON。')
    try:
        raw = llm.chat(prompt, _JUDGE_SYSTEM)
        m = re.search(r"\{.*\}", raw, re.S)
        d = json.loads(m.group(0))
        return {"supported": bool(d.get("supported")), "quote": str(d.get("quote", ""))}
    except Exception:
        return None


def verify_draft(sentences: list[dict], hits: list) -> list[VerifiedSentence]:
    """分流核验草稿：摘录→机械匹配；归纳→LLM裁判+依据quote机械复核（双重锚定）。

    只返回核验通过的句子；ref 越界、空句、裁判失败一律剔除（宁缺勿错）。
    """
    out: list[VerifiedSentence] = []
    for s in sentences:
        ref = s.get("ref", 0)
        text = str(s.get("text", "")).strip()
        if not isinstance(ref, int) or not (0 <= ref < len(hits)) or not text:
            continue
        h = hits[ref]
        if s.get("type") == "excerpt":
            # 第一级：摘录必须一字不差（归一化后）存在于原文
            if mechanical_ok(text, h.text):
                out.append(VerifiedSentence(text, "excerpt", ref, "mechanical", text))
        else:
            # 第二级：LLM 说支持，且其给出的依据 quote 还能机械锚回原文，才放行
            verdict = judge_sentence(text, h.text)
            if verdict and verdict["supported"] and mechanical_ok(verdict["quote"], h.text):
                out.append(VerifiedSentence(text, "summary", ref, "llm", verdict["quote"]))
    return out