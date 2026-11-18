"""LangGraph 编排（D1）：检索→生成→核验→（重试≤2 / 拒答 / 定稿）状态图。

核验不通过沿回头路换查询词重检索；重试超限走拒答路径——宁缺勿错。
"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from . import config, llm
from .answering import generate_draft
from .models import AnswerResult, SourceRef
from .retrieval import hybrid_search
from .verify import verify_draft

MAX_RETRIES = 2


class AgentState(TypedDict, total=False):
    """任务单：随图流转，每个节点读取并更新其中字段。"""
    question: str
    query: str
    paper_context: str
    history_context: str
    db_path: object
    use_rerank: bool
    hits: list
    draft: list
    verified: list
    retries: int
    searched: list
    result: AnswerResult


def retrieve_node(state: AgentState) -> dict:
    """检索节点：用当前查询做混合检索，并记录已尝试的查询。"""
    hits = hybrid_search(state["query"], db_path=state.get("db_path", config.DEFAULT_DB),
                         top_k=5, use_rerank=state.get("use_rerank", True))
    return {"hits": hits, "searched": state.get("searched", []) + [state["query"]]}


def generate_node(state: AgentState) -> dict:
    """生成节点：LLM 基于检索父块写逐句带引用的草稿（可带论文与对话历史背景）。"""
    return {"draft": generate_draft(state["question"], state["hits"],
                                    state.get("paper_context", ""),
                                    state.get("history_context", ""))}


def verify_node(state: AgentState) -> dict:
    """核验节点：两级分流核验，只保留通过的句子。"""
    return {"verified": verify_draft(state["draft"], state["hits"])}


def route_after_verify(state: AgentState) -> str:
    """条件边：有核验内容→定稿；没有且还有重试额度→重试；否则→拒答。"""
    if state["verified"]:
        return "finalize"
    if state.get("retries", 0) < MAX_RETRIES:
        return "retry"
    return "refuse"


def retry_node(state: AgentState) -> dict:
    """重试节点：换一组关键词（LLM 替代查询，失败回退原问题），计数 +1。"""
    alt = llm.alternative_query(state["question"], state.get("searched", []))
    return {"retries": state.get("retries", 0) + 1, "query": alt}


def finalize_node(state: AgentState) -> dict:
    """定稿节点：组装核验答案 + 出处目录（与 hits 索引平行，供角标引用）。"""
    sources = [SourceRef(h.doc_title, h.number, h.title, h.source, h.locator)
               for h in state["hits"]]
    return {"result": AnswerResult(state["verified"], sources,
                                   retries=state.get("retries", 0),
                                   searched=state.get("searched", []))}


def refuse_node(state: AgentState) -> dict:
    """拒答节点：明确告知未覆盖，并列出已尝试的检索范围。"""
    return {"result": AnswerResult([], [], refused=True,
                                   retries=state.get("retries", 0),
                                   searched=state.get("searched", []),
                                   message="资源库未覆盖该知识点")}


def build_graph():
    """构建并编译状态图：retrieve→generate→verify→条件分支，retry 回环 retrieve。"""
    g = StateGraph(AgentState)
    for name, fn in [("retrieve", retrieve_node), ("generate", generate_node),
                     ("verify", verify_node), ("retry", retry_node),
                     ("finalize", finalize_node), ("refuse", refuse_node)]:
        g.add_node(name, fn)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", "verify")
    g.add_conditional_edges("verify", route_after_verify,
                            {"finalize": "finalize", "retry": "retry", "refuse": "refuse"})
    g.add_edge("retry", "retrieve")
    g.add_edge("finalize", END)
    g.add_edge("refuse", END)
    return g.compile()


def ask(question: str, db_path=config.DEFAULT_DB, use_rerank: bool = True,
        paper=None, history_context: str = "") -> AnswerResult:
    """问答主入口（模块A/B 共用）：paper/history_context 提供背景时先做上下文化改写。"""
    ctx_parts = []
    if paper is not None:
        ctx_parts.append(paper.context())
    if history_context:
        ctx_parts.append(history_context)
    background = "\n\n".join(ctx_parts)
    query = llm.contextualize_query(question, background) if background else question
    graph = build_graph()
    final = graph.invoke({"question": question, "query": query,
                          "paper_context": paper.context() if paper is not None else "",
                          "history_context": history_context,
                          "db_path": db_path, "use_rerank": use_rerank,
                          "retries": 0, "searched": []})
    return final["result"]