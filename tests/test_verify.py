"""核验模块离线单测：归一化、机械子串匹配、拆句与两级分流。"""
from toolbook.verify import mechanical_ok, normalize, split_sentences


def test_normalize_fullwidth_and_space():
    # 全角字母/空格/中英标点统一后应相等
    assert normalize("Ｆｏｕｒｉｅｒ 变换，性质。") == normalize("fourier变换,性质.")


def test_mechanical_ok_exact():
    # 原文摘录一字不差（允许空白差异）应通过
    src = "采样定理指出：采样频率必须大于信号最高频率的两倍。"
    assert mechanical_ok("采样频率必须大于信号最高频率的两倍", src)
    assert mechanical_ok("采样频率 必须大于信号最高频率的两倍", src)


def test_mechanical_rejects_altered():
    # 内容被篡改（两倍→三倍）或空摘录必须拒绝
    src = "采样频率必须大于信号最高频率的两倍。"
    assert not mechanical_ok("采样频率必须大于信号最高频率的三倍", src)
    assert not mechanical_ok("", src)


def test_split_sentences():
    # 按中英文句末标点拆句
    assert split_sentences("第一句。第二句！第三句？") == ["第一句。", "第二句！", "第三句？"]