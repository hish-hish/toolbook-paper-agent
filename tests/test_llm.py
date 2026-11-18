"""llm 模块离线单测：查询改写的 JSON 解析与失败降级，不触网。"""
import toolbook.llm as llm


def test_rewrite_parses_json_in_markdown(monkeypatch):
    # 模拟 LLM 返回包裹在 markdown 代码块里的 JSON
    monkeypatch.setattr(llm, "chat", lambda *a, **k: '```json\n{"zh": "采样 定理", "en": "sampling theorem"}\n```')
    kw = llm.rewrite_query("什么是采样定理")
    assert kw == {"zh": "采样 定理", "en": "sampling theorem"}


def test_rewrite_fallback_on_error(monkeypatch):
    # 模拟网络/密钥故障：改写必须回退为原问题，绝不抛异常中断检索
    def boom(*a, **k):
        raise RuntimeError("no network")
    monkeypatch.setattr(llm, "chat", boom)
    kw = llm.rewrite_query("什么是采样定理")
    assert kw == {"zh": "什么是采样定理", "en": ""}


def test_embed_texts_batches(monkeypatch):
    # 模拟 embedding 接口：验证分批调用且结果按输入顺序拼接
    calls = []

    class FakeEmbeddings:
        def create(self, model, input):
            calls.append(len(input))
            return type("R", (), {"data": [type("D", (), {"embedding": [float(len(t))]})() for t in input]})()

    class FakeClient:
        embeddings = FakeEmbeddings()

    monkeypatch.setattr(llm, "get_client", lambda: FakeClient())
    vecs = llm.embed_texts(["a", "bb", "ccc", "dddd", "eeeee"], batch_size=2)
    assert calls == [2, 2, 1]
    assert [v[0] for v in vecs] == [1.0, 2.0, 3.0, 4.0, 5.0]