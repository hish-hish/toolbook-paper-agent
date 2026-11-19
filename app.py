"""ToolBook-Paper Agent Streamlit 界面（D12）：资源库管理 + 资源库问答 + 论文问答。

内核与 UI 分离：本文件只做装配与展示，全部逻辑在 toolbook 包内。
启动：uv run streamlit run app.py
"""
import sys
from datetime import datetime
from pathlib import Path

# 允许 streamlit 直接以脚本方式加载（把 src 加入模块搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st

from toolbook import config
from toolbook.agent import ask
from toolbook.importer import import_file
from toolbook.models import AnswerResult
from toolbook.paper import list_papers, parse_paper
from toolbook.session import Conversation
from toolbook.store import LibraryStore
from toolbook.vector_index import build_vector_index

st.set_page_config(page_title="ToolBook-Paper Agent", layout="wide")


def render_stats(stats: dict):
    """渲染本次回答的用量统计：token 消耗 + 模型调用次数（本地重排不计费）。"""
    if not stats:
        return
    total = stats.get("total_tokens", 0)
    pt = stats.get("prompt_tokens", 0)
    ct = stats.get("completion_tokens", 0)
    chat = stats.get("chat_calls", 0)
    emb = stats.get("embed_calls", 0)
    st.caption(f"本次消耗 {total} tokens（输入 {pt} / 输出 {ct}）· "
               f"模型调用 {chat + emb} 次（对话 {chat} / 向量化 {emb}）· 重排本地不计费")


def render_study(g):
    """渲染「供研究生学习」面板：命中节在前，[相关推荐] 跨章节在后（附内容简介）。"""
    if not g or (not g.matched and not g.recommended):
        return
    with st.expander("📚 供研究生学习", expanded=True):
        if g.matched:
            st.markdown("**命中章节**（建议系统学习）")
            for s in g.matched:
                mark = "" if s.source == "original" else " [系统编号]"
                title = s.title.removeprefix(s.number).strip() or s.title
                st.markdown(f"- {s.number} {title}（{s.locator}）《{s.doc_title}》{mark}")
        if g.recommended:
            st.markdown("**相关推荐**")
            for s in g.recommended:
                mark = "" if s.source == "original" else " [系统编号]"
                title = s.title.removeprefix(s.number).strip() or s.title
                summary = f"：{s.summary}" if s.summary else ""
                st.markdown(f"- [相关推荐] {s.number} {title}（{s.locator}）{summary}{mark}")


def render_answer(r: AnswerResult):
    """渲染一条答案：节号→页码置顶 + 无徽章核验句 + 学习指引 + 出处目录 + 用量统计。"""
    if r.refused:
        st.warning(r.message)
        st.caption(f"已尝试查询：{r.searched}（重试 {r.retries} 次）")
        render_stats(r.stats)
        return
    # 出处节号 → 页码（置顶，节号在前页码在后；只列被句子引用的出处）
    cited = sorted({s.ref for s in r.sentences if 0 <= s.ref < len(r.sources)})
    head = "、".join(f"{r.sources[i].number} 节（{r.sources[i].locator}）" for i in cited)
    if head:
        st.markdown(f"**出处节号 → 页码**：{head}")
    # 核验句：去掉机械/LLM 徽章前缀（核验仍在内部完成），保留引用角标
    for s in r.sentences:
        st.markdown(f"{s.text} `[{s.ref}]`")
    # 供研究生学习指引（命中节 + 相关推荐）
    render_study(r.study)
    # 完整出处目录（保留系统编号标记）
    with st.expander(f"出处目录（{len(r.sources)} 条，重试 {r.retries} 次）"):
        for i, src in enumerate(r.sources):
            mark = "" if src.source == "original" else " **[系统编号]**"
            title = src.title.removeprefix(src.number).strip() or src.title
            st.markdown(f"[{i}] 《{src.doc_title}》 {src.number} {title}{mark}（{src.locator}）")
    render_stats(r.stats)


def answer_gist(r: AnswerResult) -> str:
    """把一条答案压成记忆要点：核验句拼接；拒答记拒答原因。"""
    if r.refused:
        return r.message
    return "\n".join(s.text for s in r.sentences)[:400]


def chat_block(key: str, paper=None, conv=None):
    """通用问答区：历史消息 + 输入框 + spinner 跑 ask()；key 区分会话，conv 为上下文记忆。"""
    hist_key = f"messages_{key}"
    if hist_key not in st.session_state:
        st.session_state[hist_key] = []
    for role, payload in st.session_state[hist_key]:
        with st.chat_message(role):
            if role == "user":
                st.markdown(payload)
            else:
                render_answer(payload)
    prompt = st.chat_input("输入问题…", key=f"input_{key}")
    if not prompt:
        return
    st.session_state[hist_key].append(("user", prompt))
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("检索 → 生成 → 核验中（约 30–60 秒）…"):
            r = ask(prompt, use_rerank=st.session_state.get("use_rerank", True),
                    paper=paper, history_context=conv.context() if conv else "")
        render_answer(r)
    st.session_state[hist_key].append(("assistant", r))
    # 答完记一轮记忆（下一问的指代/追问靠它补全）
    if conv is not None:
        conv.add(prompt, answer_gist(r))


# ---------- 侧边栏：重排开关 + 资源库管理 ----------
st.sidebar.title("ToolBook-Paper Agent")
st.session_state["use_rerank"] = st.sidebar.checkbox("本地重排（更准，CPU 约 +2 秒/轮）", value=True)
st.sidebar.subheader("资源库")
store = LibraryStore(config.DEFAULT_DB)
docs = store.list_documents()
if docs:
    for d in docs:
        st.sidebar.markdown(f"《{d['title']}》（{d['format']}）")
else:
    st.sidebar.info("资源库为空，请先导入书籍")

# 导入新书：上传 → 存 data/books → 导入 → 重建向量索引（会话内按文件名防重复触发）
up = st.sidebar.file_uploader("导入新书（PDF/DOCX/EPUB）", type=["pdf", "docx", "epub"])
if up is not None:
    done = st.session_state.setdefault("imported_files", set())
    if up.name not in done:
        books_dir = config.DATA_DIR / "books"
        books_dir.mkdir(parents=True, exist_ok=True)
        dest = books_dir / up.name
        dest.write_bytes(up.getvalue())
        with st.sidebar.status("导入并建索引中…"):
            res = import_file(dest)
            build_vector_index(config.DEFAULT_DB, force=True)
        done.add(up.name)
        if res.skipped:
            st.sidebar.info(f"《{res.title}》已在库中（哈希去重）")
        else:
            st.sidebar.success(f"《{res.title}》导入成功：{res.sections} 章节行 / {res.chunks} 子块")

# 目录浏览：选书 → 章节树表格
if docs:
    pick = st.sidebar.selectbox("浏览目录", [d["title"] for d in docs])
    doc_id = next(d["doc_id"] for d in docs if d["title"] == pick)
    rows = store.get_tree(doc_id)
    st.sidebar.dataframe(
        [{"编号": r["number"], "标题": r["title"],
          "来源": "原书" if r["source"] == "original" else "系统",
          "定位": r["locator"]} for r in rows],
        height=300, hide_index=True)
store.close()

# ---------- 主区：两个问答页签 ----------
tab_a, tab_b = st.tabs(["知识点检索", "论文检索"])
with tab_a:
    st.caption("答案只返回核验通过的内容（摘录机械子串匹配 / 归纳逐句裁判+原文双锚定，核验在内部完成）。上下文记忆：自动保留最近 5 轮。")
    conv_a = st.session_state.setdefault("conv_a", Conversation(max_turns=5))
    if st.button("清空对话", key="clear_a"):
        conv_a.clear()
        st.session_state["messages_a"] = []
        st.rerun()
    chat_block("a", conv=conv_a)
with tab_b:
    st.caption("上传论文 PDF → 论文按行列表 → 点进某篇开始对话，答案附本地资源库出处（论文本身不作答案依据）。")
    papers_dir = config.DATA_DIR / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    # 视图切换：b_active_paper 为空=列表视图，否则=该篇详情/对话视图
    active = st.session_state.get("b_active_paper")

    if active is None:
        # ---------- 列表视图：多选上传 + 论文按行排列 ----------
        ups = st.file_uploader("上传论文 PDF（可多选）", type=["pdf"],
                               accept_multiple_files=True, key="paper_upload")
        # 上传即存盘（同名不覆盖），随后扫目录列出；不在此解析，保证列表秒开
        for up in ups:
            dest = papers_dir / up.name
            if not dest.exists():
                dest.write_bytes(up.getvalue())
        rows = list_papers(papers_dir)
        if not rows:
            st.info("还没有论文，请先上传 PDF")
        else:
            st.markdown(f"**论文列表（{len(rows)} 篇，最新上传在前）**")
            for r in rows:
                col_info, col_btn = st.columns([5, 1])
                with col_info:
                    mtime = datetime.fromtimestamp(r["mtime"]).strftime("%Y-%m-%d %H:%M")
                    st.markdown(f"📄 **{r['name']}**  \n{r['size'] / 1024:.0f} KB · 上传于 {mtime}")
                with col_btn:
                    if st.button("进入对话 →", key=f"enter_{r['name']}"):
                        st.session_state["b_active_paper"] = r["name"]
                        st.rerun()
    else:
        # ---------- 详情/对话视图：点进某篇后才懒解析 ----------
        if st.button("← 返回论文列表", key="back_to_list"):
            st.session_state["b_active_paper"] = None
            st.rerun()
        dest = papers_dir / active
        if not dest.exists():
            st.error("该论文文件已不存在，请返回列表")
            st.session_state["b_active_paper"] = None
        else:
            # 按文件名缓存解析结果，来回切换不重复解析
            cache = st.session_state.setdefault("paper_cache", {})
            if active not in cache:
                cache[active] = parse_paper(dest)
            paper = cache[active]
            st.success(f"已解析《{paper.title}》（{paper.n_pages} 页）")
            if paper.outline:
                with st.expander("论文目录", expanded=True):
                    st.dataframe(
                        [{"层级": e["level"], "标题": e["title"], "页码": e["page"]}
                         for e in paper.outline], hide_index=True)
            else:
                st.info("该论文无目录书签，已按全文处理")
            if paper.abstract:
                with st.expander("摘要"):
                    st.write(paper.abstract)
            # 每篇论文独立记忆与聊天记录：换论文不串上下文，新论文从空开始
            convs = st.session_state.setdefault("convs_b", {})
            conv = convs.setdefault(active,
                                    Conversation(max_turns=6, compress_threshold=6, keep_recent=3))
            st.caption("每篇论文的对话记忆独立；超过 6 轮自动压缩旧轮；换论文不串上下文。")
            if st.button("清空本论文对话", key=f"clear_b_{active}"):
                conv.clear()
                st.session_state[f"messages_b_{active}"] = []
                st.rerun()
            chat_block(f"b_{active}", paper=paper, conv=conv)