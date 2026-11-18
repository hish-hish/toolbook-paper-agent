"""硅基流动云端客户端：bge-m3 批量向量化、DeepSeek/Qwen 对话、双语查询改写。

全项目唯一的云端出口；密钥经 config.load_api_key() 从 .env/环境变量读取。
"""
import json
import os
import re

import httpx
from openai import OpenAI

from . import config

_client = None


def _make_http_client() -> httpx.Client:
    """构造 httpx 客户端；临时剔除 NO_PROXY 中的 IPv6 条目（httpx 解析 [::1] 会崩）。"""
    saved = {}
    for name in ("NO_PROXY", "no_proxy"):
        val = os.environ.get(name)
        if val and ":" in val:
            saved[name] = val
            os.environ[name] = ",".join(e for e in val.split(",") if ":" not in e)
    try:
        return httpx.Client()
    finally:
        # 恢复原环境变量，不影响其他库（requests 等能正常处理 IPv6）
        for name, val in saved.items():
            os.environ[name] = val


def get_client() -> OpenAI:
    """懒加载 OpenAI 兼容客户端（指向硅基流动）；无密钥时抛出带指引的异常。"""
    global _client
    if _client is None:
        key = config.load_api_key()
        if not key:
            raise RuntimeError("未配置 SILICONFLOW_API_KEY：请在项目根 .env 填入硅基流动密钥")
        _client = OpenAI(api_key=key, base_url=config.SILICONFLOW_BASE_URL,
                         http_client=_make_http_client())
    return _client


def embed_texts(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """批量向量化（bge-m3，1024 维），按 batch_size 分批，结果与输入同序。"""
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        resp = get_client().embeddings.create(
            model=config.EMBED_MODEL, input=texts[i:i + batch_size])
        out.extend(d.embedding for d in resp.data)
    return out


def chat(prompt: str, system: str = "", model: str | None = None) -> str:
    """单轮对话调用（查询改写/后续核验共用），temperature=0 保证可复现。"""
    msgs = ([{"role": "system", "content": system}] if system else [])
    msgs.append({"role": "user", "content": prompt})
    resp = get_client().chat.completions.create(
        model=model or config.CHAT_MODEL, messages=msgs, temperature=0)
    return resp.choices[0].message.content or ""


def rewrite_query(question: str) -> dict:
    """LLM 把问题改写为中英双语关键词（BM25 跨语言用）；任何失败回退原问题。"""
    system = "你是检索查询改写器。把用户问题改写为适合关键词检索的中英双语关键词，只输出JSON，不要解释。"
    prompt = (f"问题：{question}\n"
              '输出格式：{"zh": "中文关键词 空格分隔", "en": "english keywords space separated"}')
    try:
        raw = chat(prompt, system)
        m = re.search(r"\{.*\}", raw, re.S)
        d = json.loads(m.group(0))
        return {"zh": str(d.get("zh", "")), "en": str(d.get("en", ""))}
    except Exception:
        # 断网/无密钥/格式异常都不阻断检索：回退原问题
        return {"zh": question, "en": ""}


def alternative_query(question: str, tried: list[str]) -> str:
    """重检索替代查询：让 LLM 换一组不同的关键词；失败回退原问题。"""
    prompt = (f"原问题：{question}\n已尝试过的查询：{tried}\n"
              "请给出一组与上述都不同的检索关键词（中英混合、空格分隔），直接输出关键词串，不要解释。")
    try:
        out = chat(prompt).strip()
        return out or question
    except Exception:
        return question


def propose_titles(text: str) -> list[str]:
    """LLM 兜底章节识别（D5）：为无结构文本提议章节标题。

    防编造：只保留原文中一字不差出现且 ≤60 字的标题；任何失败返回空列表。
    """
    prompt = (f"以下是一本书的正文片段：\n{text[:3000]}\n\n"
              "请提议 3–10 个章节标题，每个标题必须是原文中一字不差出现的连续片段（不超过60字）。"
              '只输出JSON数组，如 ["标题一", "标题二"]。')
    try:
        raw = chat(prompt, "你是章节结构识别器。只输出JSON数组，不要解释。")
        m = re.search(r"\[.*\]", raw, re.S)
        titles = json.loads(m.group(0))
        return [t for t in titles if isinstance(t, str) and 0 < len(t) <= 60 and t in text]
    except Exception:
        return []


def contextualize_query(question: str, paper_context: str) -> str:
    """查询上下文化：结合论文摘要与对话历史把问题展开为资源库检索关键词；失败回退原问题。"""
    prompt = (f"提问背景（论文摘要与对话历史，仅供理解问题）：\n{paper_context[:1500]}\n\n用户问题：{question}\n"
              "请把问题改写为适合在教材资源库中检索的关键词（中英混合、空格分隔），"
              "结合背景补全指代与省略，突出基础知识点术语，直接输出关键词串，不要解释。")
    try:
        out = chat(prompt).strip()
        return out or question
    except Exception:
        return question


def summarize_turns(turns_text: str) -> str:
    """把旧问答轮次压缩成要点（保留知识点与结论）；失败抛异常由调用方回退。"""
    prompt = (f"以下是用户与资源库的历史问答：\n{turns_text[:3000]}\n\n"
              "请压缩成不超过200字的要点，保留讨论过的知识点与结论，直接输出要点。")
    return chat(prompt).strip()