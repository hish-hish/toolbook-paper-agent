"""供研究生学习指引（建议性面板，独立于答案核验链）：命中节 LLM 复核 + 跨章相关推荐。

推荐只从资源库真实目录树里选、校验编号存在，绝不编造章节号；LLM 失败时降级为
仅展示命中节、不给推荐（宁缺勿错）。推荐节附一句话内容简介，UI 上标 [相关推荐]。
"""
import json
import re

from . import config, llm
from .models import StudyGuide, StudySection
from .store import LibraryStore

_PICK_SYSTEM = "你是研究生学习指引助手。基于资源库真实目录复核命中章节并推荐相关章节，只输出JSON，不要解释。"
_SUMMARY_SYSTEM = "你是教材章节简介生成器。为给定章节写一句话内容简介，只输出JSON，不要解释。"


def _norm_number(s) -> str:
    """从 LLM 回显里提取节号本身：取首个空白分隔 token（标题已含节号，LLM 常整行回显）。"""
    parts = str(s).strip().split()
    return parts[0] if parts else ""


def _pick_sections(question: str, hits: list, catalog: list) -> dict | None:
    """LLM 复核命中节并跨章推荐：返回 {"keep": [节号], "recommend": [节号]}；任何失败返回 None。

    catalog 为资源库真实目录 [{"number","title"}]，推荐只能从中选，防编造章节号。
    """
    matched_desc = "\n".join(
        f"{h.number} {h.title.removeprefix(h.number).strip() or h.title}：{h.text[:200]}" for h in hits)
    catalog_desc = "\n".join(
        f"{r['number']} {r['title'].removeprefix(r['number']).strip() or r['title']}" for r in catalog)
    prompt = (f"问题：{question}\n\n本次检索命中的章节（含内容片段）：\n{matched_desc}\n\n"
              f"资源库真实目录（推荐只能从中选节号，不得编造）：\n{catalog_desc}\n\n"
              '请输出JSON：{"keep": ["节号"], "recommend": ["节号"]}\n'
              "要求：keep 从命中节里挑出与问题真正相关、研究生应当系统学习的内容，剔除不相关节号；"
              "recommend 从真实目录里挑出值得延伸学习的其他章节（可跨章），不与命中节重复，最多5个；"
              "数组里只放节号本身（如 3.1、3），不要带标题文字，节号须一字不差来自上面给出的编号。")
    try:
        raw = llm.chat(prompt, _PICK_SYSTEM)
        m = re.search(r"\{.*\}", raw, re.S)
        d = json.loads(m.group(0))
        return {"keep": [_norm_number(x) for x in d.get("keep", []) if _norm_number(x)],
                "recommend": [_norm_number(x) for x in d.get("recommend", []) if _norm_number(x)]}
    except Exception:
        return None


def _summarize_sections(question: str, sections: list) -> dict:
    """LLM 为推荐节生成内容简介：返回 {节号: 简介}；任何失败返回空字典。"""
    desc = "\n".join(f"{s['number']} {s['title']}：{s['text'][:300]}" for s in sections)
    prompt = (f"问题：{question}\n\n待简介的章节（含内容片段）：\n{desc}\n\n"
              "请为每个章节写一句不超过40字的内容简介，说明它与问题相关的学习要点。"
              '只输出JSON：{"节号": "简介"}。')
    try:
        raw = llm.chat(prompt, _SUMMARY_SYSTEM)
        m = re.search(r"\{.*\}", raw, re.S)
        d = json.loads(m.group(0))
        return {str(k): str(v) for k, v in d.items()}
    except Exception:
        return {}


def _hit_section(h) -> StudySection:
    """把检索命中转为学习指引节（命中节不带内容简介）。"""
    return StudySection(h.doc_title, h.number, h.title, h.locator, h.source, "")


def build_study_guide(question: str, hits: list, db_path=config.DEFAULT_DB) -> StudyGuide:
    """组装学习指引：命中节经 LLM 复核保留 + 跨章推荐（校验编号真实、附简介）。

    无命中返回空指引；LLM 复核失败降级为命中节全保留、推荐为空。
    """
    if not hits:
        return StudyGuide()
    store = LibraryStore(db_path)
    try:
        # 命中节涉及文档的真实目录树（同编号多 part 取首条）+ 书名映射
        by_number: dict = {}
        for did in {h.doc_id for h in hits}:
            for r in store.get_tree(did):
                by_number.setdefault(r["number"], r)
        doc_titles = {h.doc_id: h.doc_title for h in hits}
        catalog = [{"number": n, "title": r["title"]} for n, r in by_number.items()]

        picks = _pick_sections(question, hits, catalog)
        if picks is None:
            # 降级：命中节全保留、不给推荐
            return StudyGuide([_hit_section(h) for h in hits], [])

        # 命中节：仅保留 LLM 复核通过者
        keep = set(picks["keep"])
        matched = [_hit_section(h) for h in hits if h.number in keep]

        # 推荐节：校验编号真实存在、排除已命中节、去重保序、最多5个
        hit_numbers = {h.number for h in hits}
        rec_numbers: list[str] = []
        for n in picks["recommend"]:
            if n in by_number and n not in hit_numbers and n not in rec_numbers:
                rec_numbers.append(n)
        rec_numbers = rec_numbers[:5]
        rec_rows = [by_number[n] for n in rec_numbers]
        summaries = _summarize_sections(question, rec_rows) if rec_rows else {}
        recommended = [
            StudySection(doc_titles.get(r["doc_id"], ""), r["number"], r["title"],
                         r["locator"], r["source"], summaries.get(r["number"], ""))
            for r in rec_rows
        ]
        return StudyGuide(matched, recommended)
    finally:
        store.close()