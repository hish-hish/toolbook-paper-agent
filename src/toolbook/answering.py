"""答案生成：让 LLM 基于检索父块写逐句带引用的草稿（摘录/归纳分流，供核验）。"""
import json
import re

from . import llm

_GEN_SYSTEM = ("你是严谨的资源库问答助手。只能依据给定资料回答，逐句标注引用。"
               "资料不足时宁可承认不足，绝不编造。只输出JSON。")


def generate_draft(question: str, hits: list, paper_context: str = "") -> list[dict]:
    """生成答案草稿 [{"text","type","ref"}]：excerpt 须一字不差摘抄，summary 须有依据。

    paper_context 是用户正在读的论文背景，只帮助理解问题，不作为答案依据。
    资料不足、调用失败或格式异常都返回空列表（由编排层触发重检索/拒答）。
    """
    if not hits:
        return []
    # 编号资料块：每块带完整出处，供 LLM 标引用
    sources = [f"[{i}] 《{h.doc_title}》{h.number} {h.title}（{h.locator}）\n{h.text[:1200]}"
               for i, h in enumerate(hits)]
    # 论文背景段：明确仅供理解问题，答案依据只能是编号资料
    bg = (f"提问背景（用户正在阅读的论文，仅供理解问题，不作为答案依据）：\n{paper_context[:800]}\n\n"
          if paper_context else "")
    prompt = (bg + f"问题：{question}\n\n资料：\n" + "\n\n".join(sources) +
              '\n\n请输出JSON：{"insufficient": false, "sentences": [{"text": "句子", "type": "excerpt"或"summary", "ref": 资料编号}]}\n'
              "要求：type=excerpt 的 text 必须一字不差摘抄资料原文（可截取连续片段）；"
              "type=summary 的每句必须有资料依据并标 ref；"
              '资料不足以回答问题时输出 {"insufficient": true, "sentences": []}。')
    try:
        raw = llm.chat(prompt, _GEN_SYSTEM)
        m = re.search(r"\{.*\}", raw, re.S)
        d = json.loads(m.group(0))
        if d.get("insufficient"):
            return []
        return [s for s in d.get("sentences", []) if isinstance(s, dict) and s.get("text")]
    except Exception:
        return []