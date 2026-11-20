"""ToolBook-Paper Agent Streamlit 界面（D12）：资源库管理 + 资源库问答 + 论文问答。

内核与 UI 分离：本文件只做装配与展示，全部逻辑在 toolbook 包内。
启动：uv run streamlit run app.py

性能设计（登录提速）：顶层只 import 轻量模块（config/auth/models/sources/store），
chromadb/openai/langgraph 等重依赖改为「后台线程预热 + 用时懒加载」，
登录门不再被重 import 阻塞；书目/目录树用 st.cache_data 缓存，减少每次 rerun 的 SQLite 读取。
"""
import sys
import os
import html
import threading
from datetime import datetime
from pathlib import Path

# 允许 streamlit 直接以脚本方式加载（把 src 加入模块搜索路径）
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st
import streamlit.components.v1 as components
from streamlit import runtime

from toolbook import config
from toolbook import auth
from toolbook.models import AnswerResult
from toolbook.sources import group_sources_by_book, section_label
from toolbook.store import LibraryStore

st.set_page_config(page_title="ToolBook-Paper Agent", page_icon="📚", layout="wide")

# ---------- 主题样式（墨与纸：深墨蓝 × 宣纸米 × 朱砂红 × 鎏金 × 青玉） ----------
_CSS = """
:root{
  --tb-ink:#1B2A4A; --tb-ink-deep:#131F38; --tb-ink-soft:#2A3A5C;
  --tb-paper:#FAF6EC; --tb-surface:#FFFDF6; --tb-surface-dim:#F2ECDD;
  --tb-line:#E4DCC8; --tb-cinnabar:#C2402A; --tb-cinnabar-deep:#A3301F;
  --tb-gold:#D9A441; --tb-jade:#2E7D5B; --tb-azure:#3B6FB5;
  --tb-text:#26324B; --tb-muted:#7A7466;
  --tb-serif:Georgia,"Times New Roman","STZhongsong","华文中宋","SimSun",serif;
  --tb-sans:"Segoe UI","Microsoft YaHei","PingFang SC","Helvetica Neue",sans-serif;
}
html,body,[data-testid="stApp"]{font-family:var(--tb-sans);}
h1,h2,h3,.tb-serif{font-family:var(--tb-serif);}
::selection{background:rgba(217,164,65,.35);}
/* 滚动条：墨色轨道 + 鎏金拇指，与主题同语言 */
::-webkit-scrollbar{width:10px;height:10px;}
::-webkit-scrollbar-track{background:rgba(27,42,74,.06);}
::-webkit-scrollbar-thumb{background:linear-gradient(180deg,#C9B072,#B98A2E);border-radius:8px;border:2px solid transparent;background-clip:padding-box;}
::-webkit-scrollbar-thumb:hover{background:linear-gradient(180deg,#D9A441,#C2402A);background-clip:padding-box;}
[data-testid="stSidebar"] ::-webkit-scrollbar-track{background:rgba(255,255,255,.05);}

/* 主区背景：宣纸底 + 两端淡彩晕染 + 细颗粒 */
[data-testid="stApp"]{
  background:
    radial-gradient(900px 420px at 8% -6%, rgba(217,164,65,.14), transparent 60%),
    radial-gradient(800px 460px at 100% 108%, rgba(46,125,91,.10), transparent 60%),
    radial-gradient(600px 300px at 92% -4%, rgba(194,64,42,.07), transparent 55%),
    var(--tb-paper);
}
[data-testid="stApp"]::before{
  content:"";position:fixed;inset:0;pointer-events:none;z-index:0;opacity:.05;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='140' height='140' filter='url(%23n)' opacity='0.55'/%3E%3C/svg%3E");
}
[data-testid="stMain"]{position:relative;z-index:1;}
[data-testid="stDecoration"]{background:linear-gradient(90deg,var(--tb-ink),var(--tb-cinnabar) 45%,var(--tb-gold));height:3px;}
[data-testid="stHeader"]{background:transparent;}
#MainMenu,footer,[data-testid="stToolbar"]{display:none;}
[data-testid="stMainBlockContainer"]{padding-top:2.2rem;}
[data-testid="stStatusWidget"]{color:var(--tb-cinnabar);}
hr{border-color:var(--tb-line);}
a{color:var(--tb-azure);}

/* 侧边栏：深墨蓝书斋 */
[data-testid="stSidebar"]{
  background:linear-gradient(178deg,var(--tb-ink-deep) 0%,var(--tb-ink) 55%,#22304F 100%);
  border-right:1px solid rgba(217,164,65,.28);
}
[data-testid="stSidebar"] [data-testid="stMarkdown"],
[data-testid="stSidebar"] p,[data-testid="stSidebar"] label,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"]{color:#E9E4D6;}
[data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3{color:#F5EFDF;font-family:var(--tb-serif);}
[data-testid="stSidebar"] hr{border-color:rgba(217,164,65,.3);}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"]{color:#9FA9BF;}
[data-testid="stSidebar"] .stCheckbox label p{color:#E9E4D6;}
[data-testid="stSidebar"] button[kind="secondary"],
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]{
  background:rgba(255,255,255,.06);color:#F0EAD9;border:1px solid rgba(217,164,65,.45);
}
[data-testid="stSidebar"] button[kind="secondary"]:hover,
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover{
  background:rgba(217,164,65,.18);border-color:var(--tb-gold);color:#FFF6E3;
}
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"]{
  background:rgba(255,255,255,.05);border:1.5px dashed rgba(217,164,65,.55);border-radius:12px;
}
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] *{color:#D8D2C2;}
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button{
  background:rgba(217,164,65,.16);color:#F5EFDF;border:1px solid rgba(217,164,65,.5);
}
/* 下拉框底色是浅色纸面，文字必须用深墨色，否则米字米底看不清 */
[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-rac],
[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-rac] *{color:#26324B !important;}
[data-testid="stSidebar"] [data-testid="stSelectbox"] svg{fill:#D9A441 !important;}
[data-testid="stSidebar"] [data-testid="stDataFrame"]{
  border:1px solid rgba(217,164,65,.35);border-radius:10px;overflow:hidden;
}
[data-testid="stSidebar"] [data-testid="stAlert"]{background:rgba(255,255,255,.08);color:#E9E4D6;border:1px solid rgba(217,164,65,.35);}
[data-testid="stSidebar"] [data-testid="stAlert"] *{color:#E9E4D6;}
[data-testid="stSidebarCollapsedControl"]{color:var(--tb-cinnabar);}

/* 品牌与页首 */
.tb-brand{display:flex;align-items:center;gap:.7rem;margin:.2rem 0 .4rem;}
.tb-brand-name{font-family:var(--tb-serif);font-size:1.35rem;font-weight:700;color:#F5EFDF;line-height:1.15;}
.tb-brand-sub{font-size:.72rem;letter-spacing:.22em;color:#D9A441;text-transform:uppercase;}
.tb-hero{display:flex;align-items:flex-end;justify-content:space-between;gap:1rem;flex-wrap:wrap;
  padding:.4rem 0 1rem;border-bottom:2px solid var(--tb-line);margin-bottom:1rem;}
.tb-hero-title{font-family:var(--tb-serif);font-size:1.9rem;font-weight:700;color:var(--tb-ink);line-height:1.2;}
.tb-hero-title em{font-style:normal;color:var(--tb-cinnabar);}
.tb-hero-tag{color:var(--tb-muted);font-size:.92rem;margin-top:.25rem;}
.tb-hero-chips{display:flex;gap:.45rem;flex-wrap:wrap;}
.tb-chip{display:inline-flex;align-items:center;gap:.3rem;padding:.22rem .7rem;border-radius:999px;
  font-size:.78rem;font-weight:600;border:1px solid var(--tb-line);background:var(--tb-surface);color:var(--tb-ink);
  box-shadow:0 1px 2px rgba(27,42,74,.06);}
.tb-chip-gold{border-color:rgba(217,164,65,.6);background:rgba(217,164,65,.14);color:#8A6516;}
.tb-chip-jade{border-color:rgba(46,125,91,.45);background:rgba(46,125,91,.10);color:var(--tb-jade);}
.tb-chip-red{border-color:rgba(194,64,42,.4);background:rgba(194,64,42,.08);color:var(--tb-cinnabar);}
.tb-strip{font-size:.8rem;color:var(--tb-muted);margin:.1rem 0 .6rem;}

/* 页签：墨色胶囊（Streamlit 1.67 react-aria + @layer，需 !important 压过 emotion 默认配色） */
[data-testid="stTabs"] [role="tablist"]{gap:.4rem !important;background:transparent !important;border-bottom:2px solid var(--tb-line) !important;}
[data-testid="stTabs"] [data-testid="stTab"]{
  font-family:var(--tb-serif) !important;font-weight:700 !important;font-size:1rem !important;
  color:var(--tb-ink-soft) !important;background:transparent !important;
  border-radius:10px 10px 0 0 !important;padding:.55rem 1.3rem !important;cursor:pointer;
  transition:background .12s ease,color .12s ease;
}
[data-testid="stTabs"] [data-testid="stTab"] *{color:inherit !important;}
[data-testid="stTabs"] [data-testid="stTab"]:hover{background:rgba(217,164,65,.14) !important;color:var(--tb-ink) !important;}
[data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"]{
  background:linear-gradient(180deg,var(--tb-ink-soft),var(--tb-ink)) !important;color:#F5EFDF !important;
  box-shadow:0 -2px 8px rgba(27,42,74,.18) !important;
}
[data-testid="stTabs"] [role="tabpanel"]{padding-top:1rem;}

/* 按钮：朱砂主按钮 / 宣纸次按钮 */
button[kind="primary"],[data-testid="stBaseButton-primary"],
[data-testid="stFormSubmitButton"] button,[data-testid="stChatInputSubmitButton"]{
  background:linear-gradient(135deg,var(--tb-cinnabar),var(--tb-cinnabar-deep));
  color:#FFF6E9;border:none;border-radius:10px;font-weight:600;
  box-shadow:0 2px 8px rgba(163,48,31,.3);transition:transform .12s ease,box-shadow .12s ease;
}
button[kind="primary"]:hover,[data-testid="stBaseButton-primary"]:hover,
[data-testid="stFormSubmitButton"] button:hover,[data-testid="stChatInputSubmitButton"]:hover{
  background:linear-gradient(135deg,#D24B33,var(--tb-cinnabar));color:#FFF6E9;
  transform:translateY(-1px);box-shadow:0 4px 14px rgba(163,48,31,.38);
}
button[kind="secondary"],[data-testid="stBaseButton-secondary"]{
  background:var(--tb-surface);color:var(--tb-ink);border:1px solid var(--tb-line);
  border-radius:999px;font-weight:600;transition:all .12s ease;
}
button[kind="secondary"]:hover,[data-testid="stBaseButton-secondary"]:hover{
  border-color:var(--tb-gold);background:rgba(217,164,65,.14);color:var(--tb-ink);
}
[data-testid="stChatInputSubmitButton"]{border-radius:10px;}
[data-testid="stChatInputSubmitButton"] svg{fill:#FFF6E9;}

/* 输入控件（1.67 react-aria：无 baseweb；输入框/下拉底色由 config.toml 主题接管） */
[data-testid="stTextInput"] input,[data-testid="stChatInput"] textarea{color:var(--tb-text);}
[data-testid="stTextInput"] [data-rac]:focus-within{box-shadow:0 0 0 3px rgba(194,64,42,.14);border-radius:10px;}
[data-testid="stMultiSelect"] [data-tag]{
  background:rgba(194,64,42,.12) !important;border-radius:999px !important;
}
[data-testid="stMultiSelect"] [data-tag] span{color:var(--tb-cinnabar-deep) !important;}
[data-testid="stMultiSelect"] [data-tag] svg{fill:var(--tb-cinnabar-deep) !important;}
[data-testid="stFileUploaderDropzone"]{
  background:var(--tb-surface);border:1.5px dashed rgba(217,164,65,.7);border-radius:12px;
}
[data-testid="stFileUploaderDropzone"]:hover{border-color:var(--tb-cinnabar);background:rgba(217,164,65,.08);}

/* 对话区：助手=鎏金边纸卡，用户=墨青便签（1.67 靠 aria-label 区分角色） */
[data-testid="stChatMessage"]{
  background:var(--tb-surface);border:1px solid var(--tb-line);border-left:4px solid var(--tb-gold);
  border-radius:12px;padding:1rem 1.15rem;box-shadow:0 2px 10px rgba(27,42,74,.06);
  margin-bottom:.7rem;
}
[data-testid="stChatMessage"]:has([aria-label="Chat message from user"]){
  background:linear-gradient(180deg,#EFF2F8,#E9EDF5);border-left-color:var(--tb-ink);
}
[data-testid="stChatMessage"]>div[aria-hidden="true"]{
  border-radius:10px;background:rgba(217,164,65,.2);border:1px solid var(--tb-line);
  width:2.1rem;height:2.1rem;display:flex;align-items:center;justify-content:center;font-size:1.1rem;
}
[data-testid="stChatMessage"]:has([aria-label="Chat message from user"])>div[aria-hidden="true"]{
  background:rgba(27,42,74,.12);
}
[data-testid="stBottom"]{background:linear-gradient(180deg,transparent,var(--tb-paper) 30%);}
[data-testid="stBottom"]>[data-testid="stVerticalBlock"]{
  background:var(--tb-paper);border-top:1px solid var(--tb-line);
}
[data-testid="stChatInput"]{
  background:var(--tb-surface);border:1.5px solid var(--tb-line);border-radius:14px;
  box-shadow:0 3px 14px rgba(27,42,74,.08);
}
[data-testid="stChatInput"]:focus-within{border-color:var(--tb-cinnabar);box-shadow:0 3px 16px rgba(194,64,42,.16);}
[data-testid="stChatInput"] textarea{color:var(--tb-text);}
[data-testid="stSpinner"]{color:var(--tb-cinnabar);}
[data-testid="stSpinner"] svg{stroke:var(--tb-cinnabar);}

/* 答案内部：出处置顶条 / 引用角标 / 学习参考 / 出处目录 */
.tb-src-head{display:flex;align-items:center;gap:.45rem;flex-wrap:wrap;margin:.1rem 0 .65rem;
  font-size:.82rem;color:var(--tb-muted);}
.tb-src-chip{display:inline-flex;align-items:center;padding:.18rem .65rem;border-radius:999px;
  background:rgba(217,164,65,.16);border:1px solid rgba(217,164,65,.55);color:#7A5A12;font-weight:700;font-size:.8rem;}
.tb-cite{display:inline-block;margin-left:.2rem;padding:0 .32rem;border-radius:5px;
  background:rgba(194,64,42,.1);color:var(--tb-cinnabar);font-weight:700;font-size:.72em;
  vertical-align:super;line-height:1.5;}
.tb-study-item{padding:.28rem .5rem;border-radius:8px;font-size:.9rem;color:var(--tb-text);
  border-left:3px solid var(--tb-jade);background:rgba(46,125,91,.06);margin:.3rem 0;}
.tb-study-item.tb-rec{border-left-color:var(--tb-azure);background:rgba(59,111,181,.06);}
.tb-rec-tag{color:var(--tb-azure);font-weight:700;font-size:.78rem;margin-right:.25rem;}
.tb-book-head{font-family:var(--tb-serif);font-weight:700;color:var(--tb-ink);margin:.5rem 0 .25rem;}
.tb-src-item{font-size:.86rem;color:var(--tb-text);padding:.14rem 0;}
.tb-sys-badge{display:inline-block;padding:0 .4rem;border-radius:5px;background:rgba(59,111,181,.12);
  color:var(--tb-azure);font-size:.72rem;font-weight:700;margin-left:.3rem;}

/* 折叠面板 / 提示条 / 表格 / 状态 */
[data-testid="stExpander"]{
  background:var(--tb-surface);border:1px solid var(--tb-line);border-radius:12px;
  box-shadow:0 1px 5px rgba(27,42,74,.05);overflow:hidden;
}
[data-testid="stExpander"] summary{font-family:var(--tb-serif);font-weight:700;color:var(--tb-ink);}
[data-testid="stExpander"] summary:hover{color:var(--tb-cinnabar);}
[data-testid="stExpander"] summary svg{fill:var(--tb-gold);}
[data-testid="stAlert"]{border-radius:10px;border:1px solid var(--tb-line);border-left-width:4px;}
[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]){background:rgba(46,125,91,.09);border-left-color:var(--tb-jade);}
[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]){background:rgba(217,164,65,.13);border-left-color:var(--tb-gold);}
[data-testid="stAlert"]:has([data-testid="stAlertContentError"]){background:rgba(194,64,42,.08);border-left-color:var(--tb-cinnabar);}
[data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]){background:rgba(59,111,181,.08);border-left-color:var(--tb-azure);}
[data-testid="stDataFrame"]{border:1px solid var(--tb-line);border-radius:10px;}
[data-testid="stCaptionContainer"]{color:var(--tb-muted);}
[data-testid="stStatusWidget"] details{background:var(--tb-surface);border:1px solid var(--tb-line);border-radius:12px;}

/* 欢迎卡与示例问题 */
.tb-welcome{background:linear-gradient(135deg,rgba(217,164,65,.12),rgba(46,125,91,.07));
  border:1px solid var(--tb-line);border-radius:14px;padding:1rem 1.2rem;margin:.4rem 0 .8rem;}
.tb-welcome-title{font-family:var(--tb-serif);font-weight:700;font-size:1.05rem;color:var(--tb-ink);margin-bottom:.3rem;}
.tb-welcome-body{font-size:.88rem;color:var(--tb-text);line-height:1.65;}
.tb-example-label{font-size:.8rem;color:var(--tb-muted);margin:.2rem 0 .35rem;}
.tb-paper-card{background:var(--tb-surface);border:1px solid var(--tb-line);border-radius:12px;
  padding:.7rem 1rem;box-shadow:0 1px 5px rgba(27,42,74,.05);}
.tb-paper-name{font-weight:700;color:var(--tb-ink);font-size:.95rem;}
.tb-paper-meta{font-size:.78rem;color:var(--tb-muted);margin-top:.15rem;}
.tb-book-card{background:rgba(255,255,255,.06);border:1px solid rgba(217,164,65,.3);
  border-radius:10px;padding:.5rem .7rem;margin:.35rem 0;}
.tb-book-title{color:#F0EAD9;font-size:.85rem;font-weight:600;line-height:1.4;}
.tb-book-fmt{display:inline-block;margin-top:.2rem;padding:0 .45rem;border-radius:5px;
  background:rgba(217,164,65,.2);color:#E8C87E;font-size:.68rem;font-weight:700;letter-spacing:.08em;}

/* ---------- 论文详情右侧栏：贴边通顶通底的一整块固定侧栏 + 右上角图标开关 ---------- */
/* 详情视图主容器放开宽度限制：问答占满侧栏以左的全部区域，不留居中空白 */
[data-testid="stApp"]:has(#tb-detail-marker) [data-testid="stMainBlockContainer"]{max-width:none;}
[data-testid="stElementContainer"]:has(#tb-detail-marker){display:none;}
/* 侧栏整体：fixed 从窗口顶到窗口底、贴右边缘，单一左边框/阴影，内部无接缝 */
.st-key-tb_ref_pane{position:fixed;top:0;right:0;bottom:0;width:38%;z-index:999992;
  display:flex;flex-direction:column;gap:0;overflow:hidden;
  background:var(--tb-surface);border-left:1px solid rgba(217,164,65,.5);
  box-shadow:-14px 0 34px rgba(27,42,74,.16);}
body.tb-ref-closed .st-key-tb_ref_pane{display:none;}
.tb-ref-titlebar{flex:0 0 auto;background:linear-gradient(135deg,#1B2A4A 0%,#131F38 100%);
  padding:.65rem 3.2rem .65rem 1rem;font-family:var(--tb-serif);color:#F5EFDF;font-size:.92rem;
  font-weight:700;line-height:1.4;border-bottom:1px solid rgba(217,164,65,.4);}
/* PDF 所在的元素容器链逐层 flex 填满剩余高度（含 stMarkdown 与容器间的无名 div） */
.st-key-tb_ref_pane [data-testid="stElementContainer"]:has(.tb-pdf-frame){
  flex:1 1 auto;min-height:0;display:flex;flex-direction:column;}
.st-key-tb_ref_pane [data-testid="stElementContainer"]:has(.tb-pdf-frame) div{
  flex:1 1 auto;min-height:0;display:flex;flex-direction:column;margin:0;}
/* 标题条链清零默认负 margin，避免与 PDF 重叠；标题条本身不伸缩 */
.st-key-tb_ref_pane [data-testid="stElementContainer"]:has(.tb-ref-titlebar){
  flex:0 0 auto;}
.st-key-tb_ref_pane [data-testid="stElementContainer"]:has(.tb-ref-titlebar) div{
  margin:0;}
.tb-pdf-frame{flex:1 1 auto;min-height:0;width:100%;height:100%;border:none;border-radius:0;
  display:block;background:var(--tb-surface);}
/* 拖拽分隔条：body 级 fixed 贴在侧栏左缘，鎏金→朱砂渐变握把，hover/拖动时点亮 */
.tb-split-handle{position:fixed;top:0;bottom:0;width:14px;
  cursor:col-resize;z-index:999993;display:flex;align-items:center;justify-content:center;
  touch-action:none;}
.tb-split-handle span{width:4px;height:54px;border-radius:4px;
  background:linear-gradient(180deg,#D9A441,#C2402A);opacity:.4;
  box-shadow:0 0 8px rgba(217,164,65,.35);transition:opacity .15s,height .15s;}
.tb-split-handle:hover span,.tb-split-handle.active span{opacity:1;height:84px;}
/* 右上角侧栏开关图标（参照 Qoder 顶栏侧栏按钮）：开着时落在标题条右端，收起后浮在纸面上 */
.tb-ref-toggle{position:fixed;top:6px;right:10px;z-index:999994;width:34px;height:34px;
  border-radius:9px;border:1px solid transparent;background:transparent;color:#F5EFDF;
  display:flex;align-items:center;justify-content:center;cursor:pointer;padding:0;
  transition:background .15s,border-color .15s,color .15s;}
.tb-ref-toggle:hover{border-color:rgba(217,164,65,.65);background:rgba(217,164,65,.18);}
body.tb-ref-closed .tb-ref-toggle{background:var(--tb-surface);border-color:var(--tb-line);
  color:var(--tb-ink);box-shadow:0 2px 10px rgba(27,42,74,.14);}
body.tb-ref-closed .tb-ref-toggle:hover{border-color:var(--tb-gold);color:var(--tb-cinnabar);}
@media (max-width:640px){
  /* 窄屏侧栏落回文档流排在问答下方，开关仍可用，拖拽禁用 */
  .st-key-tb_ref_pane{position:static;width:auto !important;height:auto;
    border-left:none;border-top:1px solid rgba(217,164,65,.5);box-shadow:none;}
  .tb-pdf-frame{height:480px;flex:0 0 auto;}
  .tb-split-handle{display:none !important;}
  .tb-ref-toggle{background:var(--tb-surface);border-color:var(--tb-line);color:var(--tb-ink);}
}

/* ---------- 登录页：整页墨色渐变 + 居中宣纸卡片 ---------- */
[data-testid="stApp"]:has(#tb-login-marker){
  background:
    radial-gradient(760px 420px at 18% 12%, rgba(194,64,42,.22), transparent 60%),
    radial-gradient(700px 460px at 85% 85%, rgba(217,164,65,.16), transparent 60%),
    radial-gradient(560px 340px at 78% 8%, rgba(59,111,181,.18), transparent 55%),
    linear-gradient(160deg,#101A30 0%,var(--tb-ink-deep) 45%,#1E2C4E 100%);
}
[data-testid="stApp"]:has(#tb-login-marker) [data-testid="stSidebarCollapsedControl"]{display:none;}
[data-testid="stApp"]:has(#tb-login-marker) [data-testid="stMainBlockContainer"]{
  max-width:480px;padding-top:7vh;
}
.tb-login-brand{text-align:center;margin-bottom:1.4rem;}
.tb-login-title{font-family:var(--tb-serif);font-size:1.75rem;font-weight:700;color:#F5EFDF;margin-top:.7rem;line-height:1.25;}
.tb-login-title em{font-style:normal;color:var(--tb-gold);}
.tb-login-sub{color:#AEB8CE;font-size:.88rem;margin-top:.35rem;letter-spacing:.06em;}
[data-testid="stApp"]:has(#tb-login-marker) [data-testid="stForm"]{
  background:var(--tb-surface);border:1px solid var(--tb-line);border-top:4px solid var(--tb-gold);
  border-radius:16px;padding:1.6rem 1.7rem 1.4rem;box-shadow:0 18px 50px rgba(0,0,0,.45);
}
[data-testid="stApp"]:has(#tb-login-marker) [data-testid="stForm"] label p{
  color:var(--tb-ink);font-weight:600;font-size:.88rem;
}
[data-testid="stApp"]:has(#tb-login-marker) [data-testid="stFormSubmitButton"] button{width:100%;padding:.6rem;font-size:1rem;letter-spacing:.35em;text-indent:.35em;}
.tb-login-pills{display:flex;justify-content:center;gap:.5rem;flex-wrap:wrap;margin-top:1.3rem;}
.tb-login-pill{padding:.26rem .8rem;border-radius:999px;font-size:.76rem;font-weight:600;
  color:#E4DECB;border:1px solid rgba(217,164,65,.45);background:rgba(255,255,255,.05);}
.tb-login-foot{text-align:center;color:#7E8AA3;font-size:.72rem;margin-top:1.1rem;letter-spacing:.05em;}

/* 移动端适配 */
@media (max-width:768px){
  [data-testid="stMainBlockContainer"]{padding-left:1rem;padding-right:1rem;}
  .tb-hero{flex-direction:column;align-items:flex-start;}
  .tb-hero-title{font-size:1.45rem;}
  [data-testid="stApp"]:has(#tb-login-marker) [data-testid="stMainBlockContainer"]{padding-top:4vh;}
  [data-testid="stTabs"] button[data-baseweb="tab"]{padding:.5rem .8rem;font-size:.9rem;}
}
"""
st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)

# ---------- 论文侧栏控制脚本（零高 components iframe 内运行，操作父文档） ----------
# 职责：右上角图标开关即时收起/展开侧栏（纯客户端、不触发 rerun）、
# 左缘握把拖拽调宽、宽度与收起状态存 localStorage、rerun/缩放后自动恢复。
_SPLIT_JS = """
<script>
(function () {
  var doc = window.parent.document;
  var win = window.parent;
  var KEY = 'tb_pdf_split_pct', CKEY = 'tb_ref_closed', MIN = 22, MAX = 62, DEF = 38;
  var ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" ' +
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
    'stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/>' +
    '<line x1="15" y1="4" x2="15" y2="20"/>' +
    '<rect x="16.6" y="6.5" width="2.8" height="11" rx="1" fill="currentColor" stroke="none" opacity=".55"/></svg>';
  function saved() {
    try { var v = parseFloat(localStorage.getItem(KEY));
      return (v >= MIN && v <= MAX) ? v : DEF; } catch (e) { return DEF; }
  }
  function isClosed() {
    try { return localStorage.getItem(CKEY) === '1'; } catch (e) { return false; }
  }
  function pane() { return doc.querySelector('.st-key-tb_ref_pane'); }
  /* 页签pane 隐藏不卸载：祖先链上有 display:none 说明详情视图不在当前页签 */
  function ancestorHidden(el) {
    for (var n = el.parentElement; n; n = n.parentElement) {
      if (win.getComputedStyle(n).display === 'none') return true;
    }
    return false;
  }
  function mainBlock() { return doc.querySelector('[data-testid="stMainBlockContainer"]'); }
  function handle() { return doc.querySelector('.tb-split-handle'); }
  function toggleBtn() { return doc.querySelector('.tb-ref-toggle'); }
  /* 按百分比落地：侧栏宽、问答区右留白、握把位置三者同步；收起/窄屏时还原 */
  function apply(pct) {
    var p = pane(), m = mainBlock(), h = handle();
    if (!p || !m) return;
    if (win.innerWidth < 640 || doc.body.classList.contains('tb-ref-closed') || ancestorHidden(p)) {
      p.style.width = ''; m.style.paddingRight = '';
      if (h) h.style.display = 'none';
      return;
    }
    var px = win.innerWidth * pct / 100;
    p.style.width = pct + '%';
    m.style.paddingRight = (px + 28) + 'px';
    if (h) { h.style.display = ''; h.style.left = (win.innerWidth - px - 7) + 'px'; }
  }
  function setClosed(v) {
    doc.body.classList.toggle('tb-ref-closed', v);
    try { localStorage.setItem(CKEY, v ? '1' : '0'); } catch (e) {}
    var b = toggleBtn();
    if (b) b.title = v ? '展开论文栏' : '收起论文栏';
    apply(saved());
  }
  /* 开关按钮挂 body：rerun 只重建 #root，body 级节点存活，避免重复创建 */
  function ensureBtn() {
    if (toggleBtn()) return;
    var b = doc.createElement('button');
    b.type = 'button';
    b.className = 'tb-ref-toggle';
    b.innerHTML = ICON;
    b.addEventListener('click', function () {
      setClosed(!doc.body.classList.contains('tb-ref-closed'));
    });
    doc.body.appendChild(b);
  }
  function ensureHandle() {
    if (handle()) return;
    var h = doc.createElement('div');
    h.className = 'tb-split-handle';
    h.title = '拖动调整论文栏宽度';
    h.innerHTML = '<span></span>';
    doc.body.appendChild(h);
    var dragging = false;
    function pctAt(x) {
      return Math.max(MIN, Math.min(MAX, (win.innerWidth - x) / win.innerWidth * 100));
    }
    h.addEventListener('pointerdown', function (e) {
      dragging = true; h.classList.add('active');
      try { h.setPointerCapture(e.pointerId); } catch (err) {}
      e.preventDefault();
    });
    h.addEventListener('pointermove', function (e) {
      if (dragging) apply(pctAt(e.clientX));
    });
    h.addEventListener('pointerup', function (e) {
      if (!dragging) return;
      dragging = false; h.classList.remove('active');
      var p = pctAt(e.clientX);
      apply(p);
      try { localStorage.setItem(KEY, String(p)); } catch (err) {}
    });
  }
  var hideTimer = null;
  function attach() {
    /* 详情视图不在当前页签（或已离开）时藏起 body 级开关与握把，避免浮在其它页签上；
       200ms 宽限避开 rerun 换装瞬间的误 hide（换装后 attach 会取消定时器） */
    var p0 = pane();
    if (!p0 || ancestorHidden(p0)) {
      if (!hideTimer) hideTimer = win.setTimeout(function () {
        hideTimer = null;
        var b0 = toggleBtn(), h0 = handle();
        if (b0) b0.style.display = 'none';
        if (h0) h0.style.display = 'none';
        apply(saved());
      }, 200);
      return;
    }
    if (hideTimer) { win.clearTimeout(hideTimer); hideTimer = null; }
    ensureBtn(); ensureHandle();
    var v = isClosed();
    doc.body.classList.toggle('tb-ref-closed', v);
    var b = toggleBtn();
    b.style.display = '';
    if (b) b.title = v ? '展开论文栏' : '收起论文栏';
    apply(saved());
  }
  attach();
  win.addEventListener('resize', function () { apply(saved()); });
  /* 用父窗口 setTimeout 而非 rAF 做防抖：隐藏页签/iframe 里 rAF 会停摆，
     setTimeout 仍会触发，保证切页签/rerun 后开关与留白正确复位 */
  var pending = false;
  new MutationObserver(function () {
    if (pending) return;
    pending = true;
    win.setTimeout(function () { pending = false; attach(); }, 60);
  }).observe(doc.body, { childList: true, subtree: true });
})();
</script>
"""


# ---------- 印章式 Logo（内联 SVG，离线零请求） ----------
def _logo_svg(size: int = 40) -> str:
    """朱砂印章风格 logo：圆角方印 + 翻开的书 + 核验对勾。"""
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 64 64" '
        'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        '<rect x="3" y="3" width="58" height="58" rx="14" fill="#C2402A"/>'
        '<rect x="3" y="3" width="58" height="58" rx="14" fill="none" stroke="#D9A441" stroke-width="2.5"/>'
        '<path d="M32 18c-5-3.2-11.5-3.6-17-1.6v26c5.5-2 12-1.6 17 1.6 5-3.2 11.5-3.6 17-1.6v-26c-5.5-2-12-1.6-17 1.6z" '
        'fill="none" stroke="#FFF3E0" stroke-width="3" stroke-linejoin="round"/>'
        '<path d="M32 18v26" stroke="#FFF3E0" stroke-width="3"/>'
        '<circle cx="47" cy="47" r="11" fill="#2E7D5B" stroke="#FFF3E0" stroke-width="2"/>'
        '<path d="M42 47l3.5 3.5L52 44" fill="none" stroke="#FFF3E0" stroke-width="2.8" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


# ---------- 后台预热重依赖（每进程一次）：登录页渲染不被 chromadb/openai/langgraph 阻塞 ----------
@st.cache_resource(show_spinner=False)
def _warmup_heavy_modules() -> bool:
    """起守护线程预 import 重模块；用户输完账号密码时通常已就绪，登录后首屏即快。"""
    def _work():
        # 先预热登录后主区立即要用的 session/paper，再预热按需懒加载的 agent/importer/vector_index
        for m in ("toolbook.session", "toolbook.paper", "toolbook.agent",
                  "toolbook.importer", "toolbook.vector_index"):
            try:
                __import__(m)
            except Exception:
                pass  # 预热失败不影响主流程，用时懒加载会再试
    threading.Thread(target=_work, daemon=True).start()
    return True


_warmup_heavy_modules()

# ---------- 登录门（云部署设 TOOLBOOK_AUTH_USER/PASS 开启；本地不设则跳过） ----------
if auth.auth_enabled() and not st.session_state.get("authed"):
    st.markdown('<div id="tb-login-marker"></div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="tb-login-brand">' + _logo_svg(64)
        + '<div class="tb-login-title">ToolBook <em>·</em> Paper Agent</div>'
        '<div class="tb-login-sub">可溯源的论文阅读辅助 Agent · 研究生知识库问答</div></div>',
        unsafe_allow_html=True)
    with st.form("login_form"):
        u = st.text_input("用户名", placeholder="请输入用户名")
        p = st.text_input("密码", type="password", placeholder="请输入密码")
        submitted = st.form_submit_button("登录")
    if submitted:
        if auth.verify_login(u, p):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("用户名或密码错误")
    st.markdown(
        '<div class="tb-login-pills">'
        '<span class="tb-login-pill">🔍 可溯源到章节页码</span></div>'
        '<div class="tb-login-foot">本地教材资源库 · 两级核验 · 出处目录</div>',
        unsafe_allow_html=True)
    st.stop()

# ---------- 登录后才加载的中等依赖（重依赖已在后台预热） ----------
from toolbook.session import Conversation
from toolbook.paper import list_papers, parse_paper


# ---------- 书目/目录树缓存（db 修改时间作失效键，导入后手动清空） ----------
def _db_mtime() -> float:
    """库文件修改时间：作为缓存失效键，导入新书后自动失效。"""
    try:
        return os.path.getmtime(config.DEFAULT_DB)
    except OSError:
        return 0.0


@st.cache_data(ttl=120, show_spinner=False)
def _load_docs(db_path: str, mtime: float) -> list:
    """缓存读取书目列表，避免每次 rerun 都开库查询（sqlite3.Row 转 dict 才可 pickle）。"""
    store = LibraryStore(db_path)
    docs = [dict(r) for r in store.list_documents()]
    store.close()
    return docs


@st.cache_data(ttl=120, show_spinner=False)
def _load_tree(db_path: str, mtime: float, doc_id: int) -> list:
    """缓存读取某书章节树（数百行），避免每次 rerun 重复查库（Row 转 dict 才可 pickle）。"""
    store = LibraryStore(db_path)
    rows = [dict(r) for r in store.get_tree(doc_id)]
    store.close()
    return rows


def render_stats(stats: dict):
    """渲染本次回答的用量统计：token 消耗 + 模型调用次数（云端重排计费，本地重排不计费）。"""
    if not stats:
        return
    total = stats.get("total_tokens", 0)
    pt = stats.get("prompt_tokens", 0)
    ct = stats.get("completion_tokens", 0)
    chat = stats.get("chat_calls", 0)
    emb = stats.get("embed_calls", 0)
    rr = stats.get("rerank_calls", 0)
    detail = f"对话 {chat} / 向量化 {emb}"
    # 云端重排（api 后端）计入调用与 token；本地重排不计费
    if rr:
        detail += f" / 重排 {rr}"
        tail = "重排走云端 API"
    else:
        tail = "重排本地不计费"
    st.caption(f"本次消耗 {total} tokens（输入 {pt} / 输出 {ct}）· "
               f"模型调用 {chat + emb + rr} 次（{detail}）· {tail}")


def render_study(g):
    """渲染「学习参考」面板：命中节在前，[相关推荐] 跨章节在后（附内容简介）。"""
    if not g or (not g.matched and not g.recommended):
        return
    with st.expander("📚 学习参考", expanded=True):
        if g.matched:
            st.markdown("**命中章节**（建议系统学习）")
            for s in g.matched:
                # 学习参考面板不显示 [系统编号] 徽章（出处目录仍保留作 D5 卖点）
                label = html.escape(section_label(s.number, s.title))
                st.markdown(
                    f'<div class="tb-study-item">📍 {label}'
                    f'（{html.escape(str(s.locator))}）《{html.escape(s.doc_title)}》</div>',
                    unsafe_allow_html=True)
        if g.recommended:
            st.markdown("**相关推荐**")
            for s in g.recommended:
                label = html.escape(section_label(s.number, s.title))
                summary = f"：{html.escape(s.summary)}" if s.summary else ""
                st.markdown(
                    f'<div class="tb-study-item tb-rec"><span class="tb-rec-tag">[相关推荐]</span>'
                    f'{label}（{html.escape(str(s.locator))}）{summary}</div>',
                    unsafe_allow_html=True)


def render_answer(r: AnswerResult):
    """渲染一条答案：节号→页码置顶 + 无徽章核验句 + 学习指引 + 出处目录 + 用量统计。"""
    if r.refused:
        st.warning(r.message)
        st.caption(f"已尝试查询：{r.searched}（重试 {r.retries} 次）")
        render_stats(r.stats)
        return
    # 出处节号 → 页码（置顶，节号在前页码在后；只列被句子引用的出处）
    cited = sorted({s.ref for s in r.sentences if 0 <= s.ref < len(r.sources)})
    if cited:
        chips = "".join(
            f'<span class="tb-src-chip">{html.escape(r.sources[i].number)} 节'
            f'（{html.escape(str(r.sources[i].locator))}）</span>' for i in cited)
        st.markdown(f'<div class="tb-src-head">📖 出处节号 → 页码 {chips}</div>',
                    unsafe_allow_html=True)
    # 核验句：去掉机械/LLM 徽章前缀（核验仍在内部完成），引用角标做成朱砂小 chip
    for s in r.sentences:
        text = html.escape(s.text, quote=False)
        st.markdown(f'{text} <sup class="tb-cite">[{s.ref}]</sup>', unsafe_allow_html=True)
    # 学习参考指引（命中节 + 相关推荐）
    render_study(r.study)
    # 完整出处目录（按书分组＝分书目参考；保留原始角标 [i] 与答案句引用一致）
    with st.expander(f"出处目录（{len(r.sources)} 条，重试 {r.retries} 次）"):
        for book, items in group_sources_by_book(r.sources):
            st.markdown(f'<div class="tb-book-head">📕 《{html.escape(book)}》</div>',
                        unsafe_allow_html=True)
            for i, src in items:
                mark = "" if src.source == "original" else '<span class="tb-sys-badge">系统编号</span>'
                label = html.escape(section_label(src.number, src.title))
                st.markdown(
                    f'<div class="tb-src-item"><span class="tb-cite">[{i}]</span> '
                    f'{label}{mark}（{html.escape(str(src.locator))}）</div>',
                    unsafe_allow_html=True)
    render_stats(r.stats)


def answer_gist(r: AnswerResult) -> str:
    """把一条答案压成记忆要点：核验句拼接；拒答记拒答原因。"""
    if r.refused:
        return r.message
    return "\n".join(s.text for s in r.sentences)[:400]


def chat_block(key: str, paper=None, conv=None, doc_ids=None, examples=None, welcome=""):
    """通用问答区：历史消息 + 输入框 + spinner 跑 ask()；key 区分会话，conv 为上下文记忆。

    doc_ids 限定检索书目（模块A 选书）；None 搜全库（模块B 默认）。
    examples 为空历史时展示的示例问题按钮；welcome 为欢迎卡文案。
    """
    hist_key = f"messages_{key}"
    if hist_key not in st.session_state:
        st.session_state[hist_key] = []
    # 空历史时展示欢迎卡 + 示例问题（点一下即提问，降低首次使用门槛）
    if not st.session_state[hist_key] and (welcome or examples):
        if welcome:
            st.markdown(f'<div class="tb-welcome"><div class="tb-welcome-title">👋 {welcome}</div>'
                        '<div class="tb-welcome-body">答案只来自你的本地资源库，逐句核验通过才返回，'
                        '并附「哪本书 → 哪一章 → 哪一节 → 第几页」的出处；库未覆盖会明确拒答。</div></div>',
                        unsafe_allow_html=True)
        if examples:
            st.markdown('<div class="tb-example-label">试试这样问（点击即提问）：</div>',
                        unsafe_allow_html=True)
            cols = st.columns(len(examples))
            for col, q in zip(cols, examples):
                with col:
                    if st.button(q, key=f"ex_{key}_{q[:12]}", use_container_width=True):
                        st.session_state[f"pending_{key}"] = q
                        st.rerun()
    for role, payload in st.session_state[hist_key]:
        with st.chat_message(role, avatar="🧑‍🎓" if role == "user" else "📚"):
            if role == "user":
                st.markdown(payload)
            else:
                render_answer(payload)
    prompt = st.chat_input("输入问题…", key=f"input_{key}")
    # 示例问题按钮通过 pending 键传入（chat_input 本身无法被程序赋值）
    if not prompt and st.session_state.get(f"pending_{key}"):
        prompt = st.session_state.pop(f"pending_{key}")
    if not prompt:
        return
    st.session_state[hist_key].append(("user", prompt))
    with st.chat_message("user", avatar="🧑‍🎓"):
        st.markdown(prompt)
    with st.chat_message("assistant", avatar="📚"):
        with st.spinner("检索 → 生成 → 核验中（约 30–60 秒）…"):
            from toolbook.agent import ask  # 懒加载：不阻塞登录门与首屏
            r = ask(prompt, use_rerank=st.session_state.get("use_rerank", True),
                    paper=paper, history_context=conv.context() if conv else "",
                    doc_ids=doc_ids)
        render_answer(r)
    st.session_state[hist_key].append(("assistant", r))
    # 答完记一轮记忆（下一问的指代/追问靠它补全）
    if conv is not None:
        conv.add(prompt, answer_gist(r))


# ---------- 侧边栏：品牌 + 重排开关 + 资源库管理 ----------
st.sidebar.markdown(
    '<div class="tb-brand">' + _logo_svg(38)
    + '<div><div class="tb-brand-name">ToolBook</div>'
    '<div class="tb-brand-sub">Paper Agent</div></div></div>',
    unsafe_allow_html=True)
# 重排开关标签随后端变化：云端 api 走硅基流动，本地走 CPU 模型
_rr_label = ("云端重排（更准，走硅基流动 API）"
             if os.environ.get("TOOLBOOK_RERANK_BACKEND", "local").lower() == "api"
             else "本地重排（更准，CPU 约 +2 秒/轮）")
st.session_state["use_rerank"] = st.sidebar.checkbox(_rr_label, value=True)
# 登录门开启时提供退出登录（清会话标记，回到登录页）
if auth.auth_enabled():
    if st.sidebar.button("退出登录", use_container_width=True):
        st.session_state["authed"] = False
        st.rerun()
st.sidebar.markdown("---")
st.sidebar.subheader("📚 资源库")
docs = _load_docs(str(config.DEFAULT_DB), _db_mtime())
if docs:
    for d in docs:
        st.sidebar.markdown(
            f'<div class="tb-book-card"><div class="tb-book-title">《{html.escape(d["title"])}》</div>'
            f'<span class="tb-book-fmt">{html.escape(str(d["format"]).upper())}</span></div>',
            unsafe_allow_html=True)
else:
    st.sidebar.info("资源库为空，请先导入书籍")

# 导入新书：上传 → 存 data/books → 导入 → 重建向量索引（会话内按文件名防重复触发）
up = st.sidebar.file_uploader("导入新书（PDF/DOCX/EPUB）", type=["pdf", "docx", "epub"])
if up is not None:
    done = st.session_state.setdefault("imported_files", set())
    if up.name not in done:
        from toolbook.importer import import_file  # 懒加载
        from toolbook.vector_index import build_vector_index  # 懒加载
        books_dir = config.DATA_DIR / "books"
        books_dir.mkdir(parents=True, exist_ok=True)
        dest = books_dir / up.name
        dest.write_bytes(up.getvalue())
        with st.sidebar.status("导入并建索引中…"):
            res = import_file(dest)
            build_vector_index(config.DEFAULT_DB, force=True)
        done.add(up.name)
        st.cache_data.clear()  # 书目/目录缓存失效，立即反映新库
        if res.skipped:
            st.sidebar.info(f"《{res.title}》已在库中（哈希去重）")
        else:
            st.sidebar.success(f"《{res.title}》导入成功：{res.sections} 章节行 / {res.chunks} 子块")

# 目录浏览：选书 → 章节树表格
if docs:
    pick = st.sidebar.selectbox("浏览目录", [d["title"] for d in docs])
    doc_id = next(d["doc_id"] for d in docs if d["title"] == pick)
    rows = _load_tree(str(config.DEFAULT_DB), _db_mtime(), doc_id)
    st.sidebar.dataframe(
        [{"编号": r["number"], "标题": r["title"],
          "来源": "原书" if r["source"] == "original" else "系统",
          "定位": r["locator"]} for r in rows],
        height=300, hide_index=True)

# ---------- 主区：页首横幅 + 两个问答页签 ----------
st.markdown(
    '<div class="tb-hero"><div>'
    '<div class="tb-hero-title">ToolBook <em>·</em> Paper Agent</div>'
    '<div class="tb-hero-tag">添加工具书构建可溯源的资源库，支持资源库问答。</div>'
    '<div class="tb-hero-tag">添加论文，支持对论文问题检索资源库，寻找对应知识点。</div>'
    '</div><div class="tb-hero-chips">'
    '<span class="tb-chip tb-chip-gold">🔍 可溯源</span>'
    '</div></div>',
    unsafe_allow_html=True)
tab_a, tab_b = st.tabs(["📖 知识点检索", "📄 论文检索"])
with tab_a:
    st.markdown('<div class="tb-strip">摘录机械子串匹配 / 归纳逐句裁判 + 原文双锚定，核验在内部完成 · '
                '上下文记忆自动保留最近 5 轮</div>', unsafe_allow_html=True)
    # 检索书目多选（默认全选＝搜全库）：只有选中的书参与检索，出处按书分组展示
    book_titles = [d["title"] for d in docs]
    picked = st.multiselect("检索书目（可多选，默认全部）", book_titles,
                            default=book_titles, key="a_books")
    a_doc_ids = [d["doc_id"] for d in docs if d["title"] in picked]
    conv_a = st.session_state.setdefault("conv_a", Conversation(max_turns=5))
    if st.button("清空对话", key="clear_a"):
        conv_a.clear()
        st.session_state["messages_a"] = []
        st.rerun()
    if not a_doc_ids:
        st.warning("请至少选择一本书再提问。")
    else:
        chat_block("a", conv=conv_a, doc_ids=a_doc_ids,
                   examples=["奈奎斯特采样定理说了什么？",
                             "怎样从离散样本无失真地恢复连续信号？",
                             "LMMSE 估计的公式是什么？"],
                   welcome="向资源库提问")
with tab_b:
    st.markdown('<div class="tb-strip">上传论文 PDF → 点进某篇：左侧问答、右侧通顶 PDF 侧栏对照 · '
                '右上角图标收起/展开，拖左缘握把调宽 · 答案附本地资源库出处（论文本身不作答案依据）</div>',
                unsafe_allow_html=True)
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
                    st.markdown(
                        f'<div class="tb-paper-card"><div class="tb-paper-name">📄 {html.escape(r["name"])}</div>'
                        f'<div class="tb-paper-meta">{r["size"] / 1024:.0f} KB · 上传于 {mtime}</div></div>',
                        unsafe_allow_html=True)
                with col_btn:
                    if st.button("进入对话 →", key=f"enter_{r['name']}"):
                        st.session_state["b_active_paper"] = r["name"]
                        st.rerun()
    else:
        # ---------- 详情/对话视图：问答占满左侧 + 右侧贴边通顶 PDF 侧栏（右上角图标开关） ----------
        # 标记供 CSS 放开主容器宽度限制；display:none 不占文档流
        st.markdown('<div id="tb-detail-marker" style="display:none"></div>',
                    unsafe_allow_html=True)
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
            # 问答区：普通文档流占满侧栏以左区域（侧栏 fixed 不占流，右留白由脚本同步）
            convs = st.session_state.setdefault("convs_b", {})
            conv = convs.setdefault(active,
                                    Conversation(max_turns=6, compress_threshold=6, keep_recent=3))
            st.caption("每篇论文的对话记忆独立；超过 6 轮自动压缩旧轮；换论文不串上下文。")
            if st.button("清空本论文对话", key=f"clear_b_{active}"):
                conv.clear()
                st.session_state[f"messages_b_{active}"] = []
                st.rerun()
            chat_block(f"b_{active}", paper=paper, conv=conv,
                       examples=["这篇论文的核心贡献是什么？",
                                 "论文里的关键公式怎么理解？"],
                       welcome="围绕这篇论文提问")
            # 右侧栏：fixed 通顶通底一整块，标题条只标论文名 + 内嵌原始 PDF；
            # 收起/展开与调宽全由 _SPLIT_JS 客户端完成，切换不 rerun、PDF 不重载
            with st.container(key="tb_ref_pane"):
                st.markdown(f'<div class="tb-ref-titlebar">{html.escape(paper.title)}</div>',
                            unsafe_allow_html=True)
                # PDF 注册进 Streamlit 媒体服务（同文件自动去重），顶层 iframe 走浏览器原生阅读器；
                # 不能用 components.html：其沙箱 iframe 会挡住原生 PDF 阅读器
                pdf_url = runtime.get_instance().media_file_mgr.add(
                    dest.read_bytes(), "application/pdf", f"paper_pdf_{active}",
                    file_name=active)
                st.markdown(f'<iframe src="{pdf_url}" class="tb-pdf-frame" '
                            'title="论文 PDF"></iframe>', unsafe_allow_html=True)
            # 侧栏控制脚本（零高 iframe，沙箱含 allow-same-origin 可操作父文档）
            components.html(_SPLIT_JS, height=0)