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


def test_contextualize_query_success(monkeypatch):
    # 论文上下文改写：提示词含论文背景与问题，输出关键词串
    captured = {}

    def fake_chat(prompt, system="", model=None):
        captured["prompt"] = prompt
        return " 双极化 polarization 协方差 covariance "

    monkeypatch.setattr(llm, "chat", fake_chat)
    out = llm.contextualize_query("这个接收机为什么用双极化？", "论文《CORE》\n摘要：dual-polarized")
    assert out == "双极化 polarization 协方差 covariance"
    assert "CORE" in captured["prompt"] and "双极化" in captured["prompt"]


def test_contextualize_query_fallback(monkeypatch):
    # 调用失败回退原问题，不阻断检索
    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(llm, "chat", boom)
    assert llm.contextualize_query("原问题", "背景") == "原问题"


def test_summarize_turns(monkeypatch):
    # 压缩摘要：去首尾空白直接返回
    monkeypatch.setattr(llm, "chat", lambda *a, **k: " 摘要 ")
    assert llm.summarize_turns("问: x\n答: y") == "摘要"


def _fake_chat_client(content, usage):
    # 构造带 usage 的假对话客户端，供用量统计测试复用
    class FakeResp:
        choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]

    FakeResp.usage = usage

    class FakeClient:
        chat = type("Chat", (), {"completions": type("Comp", (), {"create": lambda self, **k: FakeResp()})()})()

    return FakeClient()


def test_chat_records_usage(monkeypatch):
    # 对话调用累加 token 与次数：输入10/输出5/共15，chat_calls=1
    llm.reset_usage()
    usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})()
    monkeypatch.setattr(llm, "get_client", lambda: _fake_chat_client("ok", usage))
    assert llm.chat("hi") == "ok"
    u = llm.snapshot_usage()
    assert u["chat_calls"] == 1 and u["prompt_tokens"] == 10
    assert u["completion_tokens"] == 5 and u["total_tokens"] == 15


def test_embed_records_usage(monkeypatch):
    # 向量化调用累加 embed_calls 与 prompt/total token（无 completion）
    llm.reset_usage()
    usage = type("U", (), {"prompt_tokens": 8, "total_tokens": 8})()

    class FakeEmbeddings:
        def create(self, model, input):
            return type("R", (), {"data": [type("D", (), {"embedding": [0.0]})() for _ in input],
                                  "usage": usage})()

    monkeypatch.setattr(llm, "get_client", lambda: type("C", (), {"embeddings": FakeEmbeddings()})())
    llm.embed_texts(["a", "b"], batch_size=2)
    u = llm.snapshot_usage()
    assert u["embed_calls"] == 1 and u["prompt_tokens"] == 8 and u["total_tokens"] == 8


def test_usage_accumulates_then_resets(monkeypatch):
    # 多次调用累加；reset_usage 清零，快照互不污染
    llm.reset_usage()
    usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3})()
    monkeypatch.setattr(llm, "get_client", lambda: _fake_chat_client("x", usage))
    llm.chat("a")
    llm.chat("b")
    u = llm.snapshot_usage()
    assert u["chat_calls"] == 2 and u["total_tokens"] == 6
    llm.reset_usage()
    assert llm.snapshot_usage() == {"chat_calls": 0, "embed_calls": 0, "rerank_calls": 0,
                                    "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def test_rewrite_prompt_handles_formula(monkeypatch):
    # 公式问题：改写提示词须含公式→概念术语引导（去掉该引导则此测试失败）
    captured = {}

    def fake_chat(prompt, system="", model=None):
        captured["prompt"] = prompt
        return '{"zh": "采样", "en": "sampling"}'

    monkeypatch.setattr(llm, "chat", fake_chat)
    llm.rewrite_query("式(14)的LMMSE估计是什么")
    assert "公式" in captured["prompt"]


def test_contextualize_prompt_handles_formula(monkeypatch):
    # 论文公式问题：上下文化提示词同样须含公式引导
    captured = {}

    def fake_chat(prompt, system="", model=None):
        captured["prompt"] = prompt
        return "LMMSE 估计"

    monkeypatch.setattr(llm, "chat", fake_chat)
    llm.contextualize_query("式(14)怎么理解", "论文《CORE》")
    assert "公式" in captured["prompt"]


# ---------- 云端重排 API（硅基流动 /v1/rerank，去本地 torch） ----------

def _fake_rerank_client(results, usage, captured):
    # 构造假 httpx 客户端：记录请求 url/payload，返回指定 results/usage
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": results, "usage": usage}

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["payload"] = json
            captured["headers"] = headers
            return FakeResp()

    return FakeClient()


def test_rerank_api_maps_scores_to_input_order(monkeypatch):
    # results 按分降序且 index 乱序 → 必须还原成与输入 documents 同序的分数
    captured = {}
    results = [{"index": 2, "relevance_score": 0.9},
               {"index": 0, "relevance_score": 0.5},
               {"index": 1, "relevance_score": 0.1}]
    monkeypatch.setattr(llm, "_make_http_client",
                        lambda: _fake_rerank_client(results, {"total_tokens": 10, "prompt_tokens": 10}, captured))
    monkeypatch.setattr(llm.config, "load_api_key", lambda: "sk-test")
    llm.reset_usage()
    scores = llm.rerank_api("问题", ["a", "b", "c"])
    assert scores == [0.5, 0.1, 0.9]
    # 请求打到 /rerank，模型与候选文本正确，带 Bearer 鉴权
    assert captured["url"].endswith("/rerank")
    assert captured["payload"]["model"] == llm.config.RERANK_MODEL
    assert captured["payload"]["query"] == "问题"
    assert captured["payload"]["documents"] == ["a", "b", "c"]
    assert "Bearer sk-test" in captured["headers"]["Authorization"]


def test_rerank_api_records_usage(monkeypatch):
    # 云端重排计入 rerank_calls 与 token（不再「本地不计费」）
    captured = {}
    results = [{"index": 0, "relevance_score": 0.8}]
    monkeypatch.setattr(llm, "_make_http_client",
                        lambda: _fake_rerank_client(results, {"total_tokens": 7, "prompt_tokens": 7}, captured))
    monkeypatch.setattr(llm.config, "load_api_key", lambda: "sk-test")
    llm.reset_usage()
    llm.rerank_api("问题", ["a"])
    u = llm.snapshot_usage()
    assert u["rerank_calls"] == 1 and u["prompt_tokens"] == 7 and u["total_tokens"] == 7


def test_rerank_api_no_key_raises(monkeypatch):
    # 无密钥时抛出带指引的异常（由 rerank 分发层捕获降级）
    monkeypatch.setattr(llm.config, "load_api_key", lambda: "")
    try:
        llm.rerank_api("问题", ["a"])
        assert False, "应抛异常"
    except RuntimeError as e:
        assert "SILICONFLOW_API_KEY" in str(e)