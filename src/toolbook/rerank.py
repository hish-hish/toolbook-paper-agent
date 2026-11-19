"""重排器：对 (问题, 候选) 逐对精打分，支持本地/云端两种后端。

- 本地（默认）：bge-reranker-v2-m3 交叉编码器，CPU（D10 方案B），与 MinerU 零显存冲突；
  懒加载，加载失败永久降级为 None。模型优先本地目录（ModelScope），否则 hf-mirror 在线下载。
- 云端（TOOLBOOK_RERANK_BACKEND=api）：走硅基流动 /v1/rerank，免本地 torch（约 1GB），
  供 1GB 内存云服务器部署；失败临时降级 None（不永久锁死，恢复后下次仍走 api）。
"""
import os

from . import config

_model = None
_failed = False


def rerank_scores(question: str, texts: list[str]) -> list[float] | None:
    """返回每个候选的相关度分；关闭/不可用时返回 None（调用方回退 RRF 序）。"""
    global _model, _failed
    # 显式关闭：直接降级
    if os.environ.get("TOOLBOOK_RERANK", "").lower() == "off":
        return None
    if not texts:
        return []
    # 云端 API 后端：免本地模型，失败临时降级（不置 _failed，恢复后仍可用）
    if os.environ.get("TOOLBOOK_RERANK_BACKEND", "local").lower() == "api":
        try:
            from .llm import rerank_api
            return rerank_api(question, texts)
        except Exception:
            return None
    # 本地后端：此前加载失败则永久降级
    if _failed:
        return None
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