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