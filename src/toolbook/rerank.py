"""本地重排器：bge-reranker-v2-m3 交叉编码器对 (问题, 候选) 逐对精打分。

默认 CPU（D10 方案B），与 MinerU 零显存冲突；懒加载，加载失败永久降级为 None。
模型优先从本地目录加载（ModelScope 下载），否则走 hf-mirror 在线下载（首次约 2GB）。
"""
import os

from . import config

_model = None
_failed = False


def rerank_scores(question: str, texts: list[str]) -> list[float] | None:
    """返回每个候选的相关度分；关闭/不可用时返回 None（调用方回退 RRF 序）。"""
    global _model, _failed
    # 显式关闭或此前加载失败：直接降级
    if os.environ.get("TOOLBOOK_RERANK", "").lower() == "off" or _failed:
        return None
    if not texts:
        return []
    if _model is None:
        try:
            # 国内网络优先走 HF 镜像下载模型
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            from sentence_transformers import CrossEncoder
            # 本地目录存在则离线加载，避免现场断网时无法下载
            name = str(config.RERANK_MODEL_DIR) if config.RERANK_MODEL_DIR.exists() else config.RERANK_MODEL
            _model = CrossEncoder(name, device=config.RERANK_DEVICE, max_length=512)
        except Exception:
            _failed = True
            return None
    # 逐对打分：(问题, 候选文本) → 相关度
    return [float(s) for s in _model.predict([(question, t) for t in texts])]