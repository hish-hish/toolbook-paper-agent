"""生成三本示例书（DOCX 中文 / EPUB 英文 / PDF 中文带书签），用于 M1 导入演示。"""
from pathlib import Path

ZH_CH1 = "第1章 信号基础"
ZH_S11 = "1.1 什么是信号"
ZH_S12 = "1.2 信号的分类"
ZH_CH2 = "第2章 傅里叶分析"
ZH_S21 = "2.1 傅里叶变换"
ZH_S22 = "2.2 采样定理"

ZH_BODY = {
    ZH_S11: [
        "信号是携带信息的物理量随时间或空间的变化。常见的例子包括语音、图像、温度和电压。",
        "在工程中，信号通常表示为时间的函数，例如 x(t)。自变量也可以是空间坐标，例如图像中的像素位置。",
        "系统对输入信号进行处理，产生输出信号。研究信号与系统的关系是通信、控制和信号处理领域的基础。",
    ],
    ZH_S12: [
        "按时间取值是否连续，信号分为连续时间信号与离散时间信号。连续时间信号在任意时刻都有定义，离散时间信号只在离散时刻有定义。",
        "按能量是否有限，信号分为能量信号与功率信号。能量有限的信号称为能量信号，平均功率有限的信号称为功率信号。",
        "此外还有周期信号与非周期信号、确定信号与随机信号等分类方式。不同分类对应不同的分析方法。",
    ],
    ZH_S21: [
        "傅里叶变换把时域信号分解为不同频率的正弦分量，是频域分析的核心工具。",
        "连续时间傅里叶变换定义为 X(jω) = ∫ x(t) e^{-jωt} dt。它揭示了信号的频谱结构。",
        "傅里叶变换具有线性、时移、频移、卷积定理等性质。其中卷积定理指出：时域卷积对应频域相乘。",
        "利用这些性质可以简化系统分析：线性时不变系统的输出等于输入与冲激响应的卷积。",
    ],
    ZH_S22: [
        "采样定理给出从离散样本无失真恢复连续信号的条件：采样频率必须大于信号最高频率的两倍。",
        "这个最低采样频率称为奈奎斯特频率。低于奈奎斯特频率采样会发生频谱混叠，信号无法恢复。",
        "实际系统中通常在采样前加入抗混叠滤波器，限制信号带宽，保证采样定理的条件成立。",
    ],
}

EN_CH1 = "Chapter 1 Signal Basics"
EN_S11 = "1.1 What is a Signal"
EN_S12 = "1.2 Signal Classification"
EN_CH2 = "Chapter 2 Fourier Analysis"
EN_S21 = "2.1 Fourier Transform"
EN_S22 = "2.2 Sampling Theorem"

EN_BODY = {
    EN_S11: [
        "A signal is a physical quantity that varies with time or space and carries information, such as speech, images, temperature or voltage.",
        "In engineering, signals are usually modeled as functions of time, for example x(t). The independent variable can also be a spatial coordinate.",
        "A system processes an input signal and produces an output signal. The study of signals and systems underlies communication, control and signal processing.",
    ],
    EN_S12: [
        "Signals are classified as continuous-time or discrete-time depending on whether the time variable is continuous.",
        "Energy signals have finite total energy, while power signals have finite average power. Periodic signals are typically power signals.",
        "Other classifications include periodic versus aperiodic, and deterministic versus random signals.",
    ],
    EN_S21: [
        "The Fourier transform decomposes a time-domain signal into sinusoidal components of different frequencies.",
        "It is defined as X(jw) = integral of x(t) e^{-jwt} dt, revealing the spectral structure of the signal.",
        "Key properties include linearity, time shifting, frequency shifting and the convolution theorem.",
        "The convolution theorem states that convolution in time corresponds to multiplication in frequency.",
    ],
    EN_S22: [
        "The sampling theorem states that a bandlimited signal can be perfectly reconstructed if the sampling rate exceeds twice the highest frequency.",
        "This minimum rate is called the Nyquist rate. Sampling below it causes aliasing and prevents recovery.",
        "Practical systems apply an anti-aliasing filter before sampling to enforce the bandlimit assumption.",
    ],
}


def make_docx(out: Path) -> Path:
    from docx import Document
    d = Document()
    d.core_properties.title = "示例教材：信号与系统基础"
    for ch, secs in [(ZH_CH1, [ZH_S11, ZH_S12]), (ZH_CH2, [ZH_S21, ZH_S22])]:
        d.add_heading(ch, level=1)
        for sec in secs:
            d.add_heading(sec, level=2)
            for para in ZH_BODY[sec]:
                d.add_paragraph(para)
    p = out / "示例教材_信号与系统基础.docx"
    d.save(str(p))
    return p


def make_epub(out: Path) -> Path:
    from ebooklib import epub
    b = epub.EpubBook()
    b.set_identifier("demo-signals-en")
    b.set_title("Sample Textbook: Signals and Systems")
    b.set_language("en")
    chapters = []
    for i, (ch, secs) in enumerate([(EN_CH1, [EN_S11, EN_S12]), (EN_CH2, [EN_S21, EN_S22])], 1):
        html = [f"<h1>{ch}</h1>"]
        for sec in secs:
            html.append(f"<h2>{sec}</h2>")
            html.extend(f"<p>{para}</p>" for para in EN_BODY[sec])
        c = epub.EpubHtml(title=ch, file_name=f"ch{i}.xhtml", lang="en")
        c.content = "".join(html)
        b.add_item(c)
        chapters.append(c)
    b.spine = ["nav"] + chapters
    b.toc = chapters
    b.add_item(epub.EpubNav())
    b.add_item(epub.EpubNcx())
    p = out / "sample_textbook_signals.epub"
    epub.write_epub(str(p), b)
    return p


def make_pdf(out: Path) -> Path:
    import pymupdf
    doc = pymupdf.open()
    doc.set_metadata({"title": "示例讲义：傅里叶分析入门"})
    pages = [
        ([(ZH_CH1, 22), (ZH_S11, 16)], ZH_BODY[ZH_S11]),
        ([(ZH_S12, 16)], ZH_BODY[ZH_S12]),
        ([(ZH_CH2, 22), (ZH_S21, 16)], ZH_BODY[ZH_S21]),
        ([(ZH_S22, 16)], ZH_BODY[ZH_S22]),
    ]
    for headings, paras in pages:
        page = doc.new_page()
        y = 72
        for text, size in headings:
            page.insert_text((72, y), text, fontname="china-s", fontsize=size)
            y += size + 18
        for para in paras:
            rect = pymupdf.Rect(72, y, 540, y + 120)
            used = page.insert_textbox(rect, para, fontname="china-s", fontsize=11)
            y += (120 - used) + 14
    doc.set_toc([
        [1, ZH_CH1, 1], [2, ZH_S11, 1], [2, ZH_S12, 2],
        [1, ZH_CH2, 3], [2, ZH_S21, 3], [2, ZH_S22, 4],
    ])
    p = out / "示例讲义_傅里叶分析入门.pdf"
    doc.save(str(p))
    doc.close()
    return p


def make_all(out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return [make_docx(out_dir), make_epub(out_dir), make_pdf(out_dir)]


if __name__ == "__main__":
    for path in make_all(Path(__file__).resolve().parents[1] / "data" / "demo_books"):
        print(path)