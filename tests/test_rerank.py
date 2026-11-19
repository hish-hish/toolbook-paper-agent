"""重排模块离线单测：开关与加载失败降级，不下载/加载真模型。"""
import toolbook.rerank as rr


def test_rerank_off_switch(monkeypatch):
    # 环境变量关闭重排：直接返回 None
    monkeypatch.setenv("TOOLBOOK_RERANK", "off")
    assert rr.rerank_scores("问题", ["文本"]) is None


def test_rerank_load_failure_degrades(monkeypatch):
    # 模拟 sentence-transformers 不可用：必须返回 None 而不是抛异常
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "sentence_transformers":
            raise ImportError("no torch")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(rr, "_model", None)
    monkeypatch.setattr(rr, "_failed", False)
    assert rr.rerank_scores("问题", ["文本"]) is None


# ---------- 云端 API 后端分发（TOOLBOOK_RERANK_BACKEND=api，去本地 torch） ----------

def test_rerank_api_backend_dispatch(monkeypatch):
    # 后端设为 api：走 llm.rerank_api，不加载本地模型
    import toolbook.llm as llm
    monkeypatch.setenv("TOOLBOOK_RERANK_BACKEND", "api")
    monkeypatch.setattr(llm, "rerank_api", lambda q, texts: [0.7, 0.2])
    assert rr.rerank_scores("问题", ["a", "b"]) == [0.7, 0.2]


def test_rerank_api_failure_degrades(monkeypatch):
    # 云端 API 失败（断网/无密钥）：返回 None 降级，不抛异常、不永久锁死
    import toolbook.llm as llm
    monkeypatch.setenv("TOOLBOOK_RERANK_BACKEND", "api")

    def boom(q, texts):
        raise RuntimeError("offline")

    monkeypatch.setattr(llm, "rerank_api", boom)
    assert rr.rerank_scores("问题", ["a"]) is None
    # 降级非永久：恢复后下一次仍走 api
    monkeypatch.setattr(llm, "rerank_api", lambda q, texts: [0.5])
    assert rr.rerank_scores("问题", ["a"]) == [0.5]


def test_rerank_api_empty_texts(monkeypatch):
    # 候选为空：直接返回 []，不打云端 API
    import toolbook.llm as llm
    monkeypatch.setenv("TOOLBOOK_RERANK_BACKEND", "api")
    called = []
    monkeypatch.setattr(llm, "rerank_api", lambda q, texts: called.append(1) or [0.0])
    assert rr.rerank_scores("问题", []) == []
    assert called == []