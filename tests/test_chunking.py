from toolbook.chunking import child_chunks, parent_parts


def test_child_chunks_size_and_sentences():
    text = "".join(f"这是第{i}个句子，用来测试分块边界。" for i in range(60))
    chunks = child_chunks(text, target=300)
    assert all(len(c) <= 330 for c in chunks)
    assert all(c.endswith("。") for c in chunks)
    assert "".join(chunks) == text


def test_child_chunks_short_text_single():
    assert child_chunks("一句话。") == ["一句话。"]


def test_parent_parts_split_long_section():
    text = "\n".join("段落" * 200 for _ in range(10))
    parts = parent_parts(text, max_chars=2000)
    assert len(parts) >= 2
    assert all(len(p) <= 2000 for p in parts)


def test_parent_parts_empty():
    assert parent_parts("") == [""]


def test_parent_parts_hard_split_giant_paragraph():
    text = "字" * 5000
    parts = parent_parts(text, max_chars=2000)
    assert all(len(p) <= 2000 for p in parts)
    assert sum(len(p) for p in parts) == 5000