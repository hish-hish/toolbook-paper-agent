"""会话记忆离线单测：5 轮截断、自动压缩与失败回退、清空。"""
import toolbook.session as ss


def test_empty_context():
    # 无历史时上下文为空串（ask 走原问题路径）
    assert ss.Conversation().context() == ""


def test_module_a_trims_to_five():
    # 模块A：只保留最近 5 轮，旧轮彻底丢弃
    conv = ss.Conversation(max_turns=5)
    for i in range(7):
        conv.add(f"问{i}", f"答{i}")
    assert len(conv.turns) == 5
    assert conv.turns[0].question == "问2"
    assert "问0" not in conv.context() and "问6" in conv.context()


def test_module_b_compresses(monkeypatch):
    # 模块B：第 7 轮触发压缩，旧 4 轮进 digest，保留最近 3 轮
    monkeypatch.setattr(ss.llm, "summarize_turns", lambda text: "压缩摘要")
    conv = ss.Conversation(max_turns=6, compress_threshold=6, keep_recent=3)
    for i in range(7):
        conv.add(f"问{i}", f"答{i}")
    assert len(conv.turns) == 3 and conv.turns[0].question == "问4"
    assert conv.digest == "压缩摘要"
    assert "压缩摘要" in conv.context() and "问6" in conv.context()


def test_compress_fallback(monkeypatch):
    # LLM 压缩失败：旧轮原文机械拼进 digest，不丢历史不抛异常
    def boom(text):
        raise RuntimeError("offline")
    monkeypatch.setattr(ss.llm, "summarize_turns", boom)
    conv = ss.Conversation(max_turns=6, compress_threshold=6, keep_recent=3)
    for i in range(7):
        conv.add(f"问{i}", f"答{i}")
    assert "问0" in conv.digest and len(conv.turns) == 3


def test_clear():
    # 清空后上下文为空
    conv = ss.Conversation()
    conv.add("问", "答")
    conv.clear()
    assert conv.context() == "" and conv.turns == []