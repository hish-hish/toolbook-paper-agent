# ToolBook-Paper Agent — 项目全记录

> 版本：v1.8（云端部署适配：① 重排新增**云端 API 后端**（硅基流动 `/v1/rerank`，`TOOLBOOK_RERANK_BACKEND=api`，去 torch/sentence-transformers，适配 1GB 内存服务器）；② **应用内登录门** `auth.py`（环境变量凭据、常量时间比较，本地不设则关闭）；③ **精简云 Dockerfile** + `.dockerignore` + `requirements-cloud.txt`（不含 torch/mineru）+ `scripts/deploy_server.sh` + `docs/部署指南.md`（Docker `--memory=600m` 硬上限保护现有程序、端口 8501 避开 7860、绝不重启服务器）；**165 测试全过** + 登录门浏览器端到端验证。前序：学习参考去徽章 + `section_label` 理顺编号重复、非知识节过滤删 103 节、选书+分书目参考、M5 消融、检索调优①标题前缀 E 17→19/22）
> 日期：2026-11-19
> 用途：竞赛项目（非毕业论文内容）。本文件汇总「我们做了什么、怎么做的、怎么跑、踩过哪些坑、下一步做什么」，供本人回顾与交接。
> 比赛截止：**2026-11-30**。评审形式：**提交作品包**（非现场答辩）。

---

## 1. 项目是什么

面向研究生的**论文阅读辅助 Agent**：把本地教材/文档建成可溯源的资源库，读论文时针对知识点提问，系统到资源库里检索、**先核验后返回**，只给出核验通过的内容并附「哪本书 → 哪一章 → 哪一节 → 第几页」的出处。

- **用户**：研究生（本项目作者）。
- **资源库规模**：约 3 本书/文档，中英混合，不涉密，可用云端 API。
- **硬件**：计划书记录 RTX 3060 Ti（8GB）；**实测 MinerU 设备日志显示为 RTX 3060 Laptop（6GB 显存）**，Windows。MinerU 与本地重排仍可跑。
- **三条核心原则**（贯穿全部代码，绝不妥协）：
  1. **可溯源**：每条返回内容都能沿 `Chunk → Section → Document` 回溯到原文。
  2. **先核验后返回**：检索/生成的内容必须经原文核对才输出。
  3. **宁缺勿错**：资源库未覆盖就明确拒答，绝不硬答、绝不编造章节号。

---

## 2. 两大功能模块

### 模块 A：本地资源库（Library）
1. 导入 **DOCX / PDF / EPUB**。
2. 解析章节结构，建立「章节号 → 原文内容」索引。
3. 两种查询：按**章节号直查**；按**关键词/自然语言问题**检索并给出命中章节号。
4. 对命中内容做**原文核对**。
5. 只返回**核验过的内容 + 出处**（书名、章节号、页码/定位）。

### 模块 B：论文问答（Paper）
1. 上传一篇 **PDF 论文** → 解析（标题、摘要、书签目录、页数）。
2. 展示论文大纲，进入**等待提问**状态。
3. 针对论文知识点提问 → 结合论文上下文理解问题 → 到**模块 A 资源库**检索 → 返回答案并附**资源库出处目录**。
4. **论文本身不入资源库**，只作为提问背景；答案依据只能来自资源库。

---

## 3. 技术选型（D1–D13，已定案）

| 编号 | 决策点 | 最终选择 |
|---|---|---|
| D1 | Agent 编排 | **LangGraph**（状态图，核验失败→重检索循环） |
| D2 | LLM 接入 | **国内云端 API**：硅基流动 `deepseek-ai/DeepSeek-V3.2` |
| D3 | PDF 解析 | **MinerU 4.2.3**（进程内 `parse()`，pipeline 后端）；**默认 PyMuPDF**，环境变量切换 |
| D4 | DOCX/EPUB | **python-docx + ebooklib** |
| D5 | 章节识别 | **规则优先 + LLM 兜底**（兜底结果标「系统编号」） |
| D6 | 分块 | **父子块 small-to-big**（小块检索、返回所属整个小节） |
| D7 | 检索 | **BM25 + 向量混合 + RRF（k=60）+ 双语查询改写 + 章节号直查旁路** |
| D8 | Embedding | **硅基流动 `BAAI/bge-m3`**（免费，1024 维，OpenAI 兼容接口） |
| D9 | 向量库 | **Chroma**（PersistentClient，cosine） |
| D10 | 重排 | **`BAAI/bge-reranker-v2-m3` 本地 CPU**（与 MinerU 零显存冲突） |
| D11 | 原文核验 | **两级混合**：摘录机械子串匹配 + 归纳逐句 LLM 裁判（依据 quote 再机械复核＝双锚定） |
| D12 | 界面 | **Streamlit**（内核与 UI 分离，UI 只是薄壳） |
| D13 | 元数据 | **SQLite**（单文件 `data/library.db`） |

> 每个决策点的初学者详解见 `docs/决策点详解/D01–D13`（统一结构：解决什么问题→大白话名词解释→为什么选它→在本项目哪个环节→常见疑问）。

---

## 4. 系统架构与数据流

### 4.0 全景

```
交互层：Streamlit app.py（双页签） / CLI toolbook / demo 脚本
        │
        ├─ 模块A 资源库问答 ─┐
        └─ 模块B 论文问答 ───┤（论文背景 + 对话历史 → 查询上下文化）
                            ▼
              Agent 编排层 agent.py（LangGraph 状态图）
              retrieve → generate → verify → 条件边{finalize | retry | refuse}
                            │                         └─ retry → retrieve（≤2 次）
        ┌───────────────────┼─────────────────────────────┐
        ▼                   ▼                             ▼
  混合检索 retrieval.py   答案生成 answering.py        两级核验 verify.py
  改写→BM25+向量→RRF      逐句带引用草稿               摘录机械 / 归纳 LLM+双锚定
  →父块去重→本地重排      (摘录/归纳分流)              不通过剔除
        │
        ├─ bm25_index.py（jieba + rank_bm25 内存索引）
        ├─ vector_index.py（Chroma，bge-m3 向量）
        └─ rerank.py（本地 bge-reranker-v2-m3，CPU）
        │
  导入管道 importer.py：parsers/* → structure.py（章节树）→ chunking.py（父子块）→ store.py（SQLite）
  云端唯一出口 llm.py：embed_texts / chat（所有 LLM 调用都经 chat，自动计用量）
  辅助：paper.py（论文解析） session.py（对话记忆） study.py（学习指引） models.py（数据类） config.py（配置）
```

### 4.1 导入管道（M1）
`parsers/*` 把文档解析成 `Block`（heading/paragraph + level + locator）→ `structure.py` 识别章节树 `SectionNode`（规则优先：PDF 书签 / DOCX 标题样式 / EPUB 目录 / 标题编号正则；无结构时 `llm_fallback` 让 LLM 提议标题，**提议必须能在原文块定位、≥2 切分点才生效，防编造**，标 `source="system"`）→ **`prune_non_content` 剪掉非知识节（见 4.10）** → `chunking.py` 父子块切分 → `store.py` 写 SQLite（documents / sections / chunks）。
- **幂等**：按文件哈希去重，重复导入同一本书跳过（`ImportResult.skipped=True`）。
- **PDF 解析器**：书签≥3 走「书签锚点驱动」切分（`search_for` 定位 + 前缀回退处理换行标题）；无书签走字号启发。MinerU OCR 会在编号点号旁加空格（"1 . 1"），适配器已归一化。
- **章节号体系**（ISAC 书）：部分=P1–P6，章/节=原书编号，无编号标题=S 前缀系统编号（如 `1.S1 本章自测`），避免与原书编号冲突。

### 4.2 混合检索管道（M2，`retrieval.py:hybrid_search`）
1. **查询改写** `llm.rewrite_query`：原问题 → 中英双语关键词（断网自动回退原问题）。
2. **BM25 路**：原问题 + 中文关键词 + 英文关键词各查一次（top 30）。
3. **向量路**：原问题语义检索（bge-m3，top 30）。
4. **RRF 融合**（k=60）：只看名次不看原始分，`score = Σ 1/(k+rank)`。
5. **子块→父块映射去重**：保留最佳名次，记录命中方式 `bm25/vector/both`（最多 30 个父块）。**`doc_ids` 多书锁库**（`retrieval.py:40/79`）：非 None 时只保留 `doc_id` 在列表内的父块；向量路同步用 Chroma `where={"doc_id":{"$in":doc_ids}}` 过滤（`vector_index.py:60`）。None=搜全库，空列表=无命中。
6. **组装父块全文**：同编号多 part 拼接，带完整出处。
7. **本地重排** `rerank.rerank_scores`：交叉编码器逐对精打分覆盖展示分并重排；失败/关闭自动降级为 RRF 序。返回 `top_k=5` 个 `SearchHit`。
- **章节号直查旁路**：`store.get_section(doc_id, number)` 直接取原文，不走检索。

### 4.3 核验编排图（M3，`agent.py`，LangGraph 1.2.22）
`StateGraph`：`retrieve → generate → verify → 条件边{finalize | retry | refuse}`，`retry → retrieve`，`MAX_RETRIES=2`。
- 核验通过 → `finalize`：组装 `AnswerResult`（核验句 + 出处目录）。
- 核验空且重试 < 2 → `retry`：`llm.alternative_query` 换查询重检索。
- 重试用尽仍空 → `refuse`：返回「资源库未覆盖该知识点」+ 已尝试查询列表（`searched`）。
- `AgentState` 为 `TypedDict(total=False)`。

### 4.4 两级核验（D11，`verify.py`，本项目招牌防线）
- **归一化** `normalize`：NFKC 全半角统一 + 中英标点映射 + 转小写 + 去全部空白（避免「内容全对却因标点判失败」）。
- **第一级（摘录 excerpt）**：`mechanical_ok` 归一化后摘录必须是原文**子串**（零误差、零成本）。
- **第二级（归纳 summary）**：`judge_sentence` 让 LLM 逐句裁判 `{supported, quote}`；**LLM 说支持，且它给的依据 quote 还能机械锚回原文，才放行**（双重锚定）。
- ref 越界、空句、裁判失败一律剔除。**只返回核验通过的句子。**

### 4.5 论文问答（M4，`paper.py` + `agent.ask(paper=...)`）
- `parse_paper → PaperInfo`（标题/书签目录/摘要/页数）。**双栏论文必须用 PDF 自然存储顺序取文本**（书籍解析器按 y 排序会把双栏交错）；标题只取首页上 35% 区域最大字号行（CORE 正文有 28.5pt 章节首字母 "I" 会误判）。
- `llm.contextualize_query(问题, 论文背景+历史)` → 检索关键词（失败回退原问题）。
- `generate_draft(..., paper_context=...)`：背景**仅供理解问题，不作答案依据**。
- 模块 B 走**同一张核验图**，答案附资源库出处。
- **UI 重设计（2026-11-19，论文检索列表→详情两视图）**：页签改名「知识点检索/论文检索」。模块B 由"上传即解析即对话"改为：① **列表视图**——多选上传存 `data/papers/`，`list_papers` 扫目录按 mtime 倒序**每篇一行**（文件名+大小+上传时间+「进入对话→」），只读元信息不解析故秒开；② **详情视图**——点进某篇才 `parse_paper` 懒解析（按文件名缓存 `paper_cache`），展示标题/页数/目录/摘要+该篇专属对话区，「←返回论文列表」回列表。视图切换靠 `st.session_state["b_active_paper"]`（None=列表）。记忆/聊天记录键改用文件名（`convs_b[active]` / `messages_b_{active}`），换论文不串上下文。核验/学习指引/统计原样保留。

### 4.6 上下文记忆（M4 增强，`session.py`）
- `Turn / Conversation`：`max_turns` 截断（**模块 A=5**）；`compress_threshold>0` 超阈值把旧轮压缩进 digest（**模块 B=6，keep_recent=3**）；LLM 压缩失败回退旧轮原文拼接；`clear()`；无历史 `context()` 返回 ""。
- `llm.summarize_turns`：压缩 ≤200 字要点。
- 历史注入 `generate_draft(..., history_context=...)` 与 `ask(..., history_context=...)`，明确「仅供理解指代/追问，不作答案依据」。
- UI：模块 A `conv_a`(5 轮)+清空；模块 B `convs_b` 按 `paper_name` 键控(6 轮压缩)+聊天记录 `messages_b_{paper_name}` 同键 → **换论文不串上下文、切回恢复**。
- **指代消解坑（已修）**：追问「它/那…呢」须先从最近一轮历史确定被追问主题、核心术语放最前、不要改用论文未讨论主题。**该规则必须条件化（仅有历史+追问时生效）**，无条件版会削弱无历史首问的论文背景展开。

### 4.7 学习参考指引（M4 再增强，`study.py:build_study_guide`；UI 面板原名「供研究生学习」，2026-11-19 改名「学习参考」）
- **命中章节**：LLM 复核每个命中节是否相关、是否研究生该系统学习的内容，过滤后保留（keep）。
- **[相关推荐]**：放在命中节后面，LLM 跨章推荐相关章节 + 每节一句话内容简介。**推荐只从真实目录树（`store.get_tree`）选、校验编号存在、排除已命中节、去重、最多 5 个，绝不编造**。
- LLM 失败降级：命中节全保留 + 推荐空。
- 学习指引是**建议性面板**，与答案两级核验链互不影响。
- 按用户要求**不写「LLM 推荐」字样**，推荐节统一前缀 `[相关推荐]`。
- **展示理顺（2026-11-19，用户批准）**：① 学习参考面板（命中节 + 相关推荐）**去掉 `[系统编号]` 徽章**（出处目录仍保留，作 D5 防编造卖点）；② 编号+标题重复用纯函数 `sources.py:section_label(number,title)` 理顺——标题已含「第X章/节/部分」时不再叠加冗余数字编号（「1 第一章 …」→「第一章 …」），「3.1 采样…」自带编号仍正常去重，「第三方」等非章节词不误判，空标题回退编号。`render_study` 与 `render_answer` 出处目录三处统一改用该函数（出处目录保留徽章）。

### 4.8 用量统计（M4 再增强，`llm.py`）
- 模块全局 `_usage` 累加器 + `reset_usage()` / `snapshot_usage()` / `_record_usage(resp, kind)`。键含 `chat_calls/embed_calls/rerank_calls/prompt_tokens/completion_tokens/total_tokens`。
- `chat()` / `embed_texts()` 累加调用次数与 `resp.usage` 的 token（`usage=None` 时优雅跳过）；`rerank_api()` 累加 `rerank_calls` 与 token（云端重排计费）。
- **所有 LLM 调用都经 `chat()`**（改写/替代查询/上下文化/压缩/提议标题/生成/裁判），自动计入。
- `ask()` 开始 `reset_usage`、结束 `snapshot_usage` 挂到 `AnswerResult.stats`；`study` 挂 `AnswerResult.study`。
- UI 底部 caption：`本次消耗 X tokens（输入/输出）· 模型调用 N 次（对话/向量化[/重排]）· 重排本地不计费`。**本地重排不耗云端 token 不计费；云端 API 重排（`rerank_calls>0`）计入调用与 token，caption 改显「重排走云端 API」**（`app.py:render_stats` 自适应）。

### 4.9 选书检索 + 分书目参考（2026-11-19，知识点检索页签）
- **需求**：原界面回答只来自一本书；改为用户自选资源库中的书（可多选），答案出处**按书分组**展示（分书目参考）。
- **bounded 设计（用户批准）**：多选书（默认全选＝搜全库）→ **一个综合答案**（不按书拆答案）→ 出处按书分组；**综合检索、哪本相关引哪本**（不设每书配额，选中的书若无相关命中则不出现）；空选→警告「请至少选择一本书再提问」且不提问。**模块 B 不变**（仍搜全库）。不做：每书配额、模块 B 选书、答案生成改动、索引重建。
- **接线**：`app.py:176` 多选框 `检索书目` → `a_doc_ids`（`app.py:178`）→ `chat_block(..., doc_ids=a_doc_ids)`（`app.py:187`）→ `ask(doc_ids=...)`（`agent.py:115/136`）→ `retrieve_node`（`agent.py:46`）→ `hybrid_search(doc_ids=...)`。`doc_id`（单书）泛化为 `doc_ids: list[int]|None`（多书），评测锁库 `eval_m5.py --doc-id` 包装成 `[id]`。
- **分组 helper**：`sources.py:group_sources_by_book`（纯函数、不依赖 Streamlit、离线可测）按 `doc_title` 分组，**保留每条原始索引 i**，使分组展示时答案句引用角标 `[i]` 不错位；书序按首次出现。`render_answer` 出处目录 expander 改为按书分组（`app.py:80`），仍保留 `[i]` 与 `[系统编号]` 标记。
- **验证**：TDD 全过（**134 测试**：向量 doc_ids 3 + 混合 doc_ids 4 + 分组 3 + ask 透传 2 等）。live `ask(doc_ids=[1,2])` 端到端跑通、分组渲染正确；中文问法下中文书占优故仅 doc1 进前 5（符合「哪本相关引哪本」，非 bug）。**界面交互验证受限于内置浏览器隐藏视口**（按钮 click 不触发 Streamlit 提交），改用程序化 ask 验证链路；多选框默认全选已用快照确认渲染。

### 4.10 非知识节过滤 + 资源库清理（2026-11-19）
- **需求**：答案曾引到「0 前言」等非知识内容；用户要求剔除前言及与正式章节无关的东西，**每本书都清**。
- **分类器** `structure.py:is_non_content_section(number,title,source)`（纯函数离线可测）：**只判 `system` 系统编号节，`original` 正式章节一律保留**（杜绝 doc2 `2.6.2 Reference Signal`/`5.3.1 Index Modulation` 误删）；`number=="0"`（导入自动前言）或标题命中 `前言/写给读者/序言/目录/Contents/Preface/Foreword/致谢/参考文献/References/Bibliography/索引/Index/本章自测/自测答案` 即剔。**知识附录天然保留**（符号地图 S2、附录B推导 B.1–B.9、附录C术语表、附录D D.1–D.5，标题不含上述词）。档位＝**保守清理**（用户批准）。
- **导入即过滤**：`structure.py:prune_non_content(roots)` 递归剪非知识节及子树；`importer.py:35` 建树后、入库前调用 → 未来导入新书自动干净。
- **清现有库**：`scripts/clean_library.py`（触库运行器）① 备份 `data/library.db`→`.bak-时间戳`；② 分类器选拟删节 → `store.delete_sections(ids)`（FK 级联清子节+chunks）；③ `build_vector_index(force=True)` 重建清 Chroma 残留向量；④ 打印实删数。
- **执行结果（2026-11-19）**：doc1 **296→234（删 62）**、doc2 **688→647（删 41，含级联子节）**，共删 **103 节**；向量索引重建 **4534 条**，库 chunks 与 Chroma 一致；备份 `data/library.db.bak-20261119-173512`。验证：两本书残留非知识节=0，B.1/附录C/D.3/符号地图/正式章 3.1 全保留。
- **后果**：删节必须重建索引（一致性必需，非②③实验）；检索语料变化 → M5 基线可能漂移（重跑 E 付费暂缓）；有 `.bak` 可逆（恢复 db+重建即还原）。**143 测试全过**（分类器 6 + 导入剪枝 1 + 级联删 2）。

### 4.11 云端部署适配（2026-11-19，用户批准「按推荐开始」）

**背景与约束**：部署到阿里云 ECS（公网 `47.107.249.54`，Ubuntu 24.04，2 核，**物理内存仅 894M/可用约 380M**，swap 2G，磁盘 30G/余 23G）。**服务器上已有程序 agent-lab（裸进程，端口 7860，约 166M）在跑，用户明令「不要动它」**；该程序无开机自启，**故绝不重启服务器**（重启即丢失）。SSH 密码用户自己输。登录账号密码用户定 `hish/hish`（弱密码已提醒，公网建议改强）。

**可行性实测**（`data/eval/mem_probe.py`，gitignored）：关本地重排（`TOOLBOOK_RERANK=off`）逐阶段量 RSS——baseline 17.9→streamlit 51→core 139.5→chroma(4534 向量)206.3→jieba 259.6→BM25 278.2M，**torch 未被 import**；运行中 streamlit 空闲 RSS 229.4M。结论：**去 torch 后约 350M 峰值，600M 容器上限够用**；本地重排模型需 1–2G，1G 服务器装不下 → 必须改云端重排。

**① 云端重排 API 后端（去 torch）**：
- `llm.rerank_api(question, texts)`：POST 硅基流动 `/v1/rerank`（`config.RERANK_API_URL`），模型 `BAAI/bge-reranker-v2-m3`，**与向量化同密钥同 base_url**；payload `{model,query,documents,top_n,return_documents:false}`；响应 `results` 按分降序且 `index` 乱序 → **按 index 还原成与输入同序的分数**（0~1）；计入 `rerank_calls`+token；无密钥抛带指引异常。复用 `_make_http_client()`（IPv6 NO_PROXY 坑修复）。
- `rerank.py` 加**后端分发**：`TOOLBOOK_RERANK_BACKEND`（默认 `local`）＝`api` 时走 `llm.rerank_api`，**失败临时降级 None（不置 `_failed`，恢复后下次仍走 api）**；`local` 时原交叉编码器路径（加载失败永久降级）。`off` 开关与空候选 `[]` 前置不变。**api 后端不受 `_failed` 影响**（本地模型失败不该锁死云端）。
- 云端镜像**不装 sentence-transformers/torch**；`rerank.py:38` 与 `parsers/pdf_mineru.py:19` 的重依赖均为**函数内懒加载**（api 后端/默认 PyMuPDF 永不触及），故去依赖后 app 仍可 import。

**② 应用内登录门 `auth.py`**（纯函数离线可测）：
- `auth_enabled()`：`TOOLBOOK_AUTH_USER` 与 `TOOLBOOK_AUTH_PASS` **都非空才开启**（半配置视为关闭）；本地开发不设＝门关闭直接可用。
- `verify_login(user,password)`：未开启或任一不匹配/空输入返回 False；**`hmac.compare_digest` 按 utf-8 字节常量时间比较**（防时序侧信道、兼容中文密码）。
- `app.py` 门接在 `set_page_config` 后、侧边栏前：未登录渲染登录表单 + `st.stop()` 阻断全部主内容；登录成功置 `session_state["authed"]` 并 `st.rerun()`；侧边栏「退出登录」清标记回门。**凭据绝不硬编码/入库**，只走环境变量（服务器 `.env` 经 `--env-file` 注入）。
- **浏览器端到端验证**（8502 临时实例，设 auth+api 环境变量）：未登录只见登录表单（无侧边栏/页签）✓；错密码→「用户名或密码错误」门不放✓；对密码→进应用（侧边栏显两本书、**重排开关标签自适应为「云端重排（更准，走硅基流动 API）」**、退出登录按钮、双页签）✓；退出登录→回门✓。（截图受隐藏视口限制，用 `take_snapshot` 结构核验 + `evaluate_script` 原生 click 提交表单。）

**③ 精简云镜像 + 部署脚本 + 指南**：
- `requirements-cloud.txt`：pyproject 轻依赖**剔除 sentence-transformers 与 mineru[core]**（torch 携带者），另列 httpx（llm 直接 import）。`uv pip compile` 验证解析出 **128 包，零 torch/nvidia/sentence-transformers/mineru/triton/transformers**（chromadb 带 onnxruntime/numpy 但非 torch）。
- `Dockerfile`：`python:3.13-slim` + `build-essential libgomp1`（兜底编译/onnxruntime 运行）+ `pip install -r requirements-cloud.txt`（**不用 uv sync 全量 pyproject，避免装 torch**）+ COPY `src/ app.py`；ENV `TOOLBOOK_RERANK_BACKEND=api`、无头 Streamlit、`PYTHONPATH=/app/src`；`EXPOSE 8501`；**data/ 与 .env 不烤进镜像**（运行时挂载/注入）。
- `.dockerignore`：排除 `.venv/data/.git/.env/**__pycache__/.idea/docs/tests/scripts/*.md`，缩小上下文 + 绝不把密钥/资源库打进镜像。
- `.env.example`：模板（`SILICONFLOW_API_KEY=` 空、`TOOLBOOK_AUTH_USER=hish`、`TOOLBOOK_AUTH_PASS=` 空、`TOOLBOOK_RERANK_BACKEND=api`），**可提交**（无真实密钥）；`.env` 仍 gitignore。
- `scripts/deploy_server.sh`（服务器项目根内跑，`bash -n` 通过）：检查 .env 密钥/library.db → 记录部署前 7860/8501 → 缺则装 `docker.io`（**不重启**）→ `docker build` → `docker run -d --name toolbook --restart always -p 8501:8501 --memory=600m --memory-swap=600m --env-file .env -v $ROOT/data:/app/data` → 探活 `/_stcore/health` → 复核 7860 仍在 + 内存上限生效。**登录门凭据未填全会强警告**（公网裸奔风险）。
- `docs/部署指南.md`：初学者向，标明每条命令在【本地 Git Bash】/【服务器 SSH】/【阿里云控制台】哪里输；本地 `tar`（GNU tar 1.35 验证 basename 排除生效）打 ~90M 包（**排除 data/models 2.2G 本地模型**、.venv/.git/.env/eval/bak）→ scp → 解包 → 建 .env → 跑脚本 → **安全组放行 8501** → 浏览器登录验证 + 确认 7860 原样；含运维/回滚/FAQ/构建内存说明（swap 兜底，运行期 600M 硬上限保护现有程序）。
- **内存安全机制**：`--memory=600m --memory-swap=600m` 把容器 RAM+swap 合计限死 600M，**OOM 只杀本容器，绝不波及 agent-lab**；端口 8501 避开 7860；不装 nginx（不碰现有反代）；全程不重启主机。
- **未做（诚实记录）**：本地与服务器均**未装 Docker**，镜像**尚未实际构建/运行**；已验证＝依赖解析零 torch + 重依赖懒加载 + 登录门浏览器端到端 + api 降级离线单测。**真实云端重排 API 调用属付费，未自动跑**（等用户部署时验证）。构建建议在服务器 swap 兜底下进行或本地有 Docker 时构建后传镜像。
- **内存可行性算账 + 用户决定换 4GB 服务器（2026-11-19 答疑）**：
  - **原方案（本地重排）最少约 3GB**：模型权重 `data/models/` 实测 **2.2GB 须整个搬进内存** + torch 运行时 ~0.3GB + app 本体 ~0.28GB + 系统/agent-lab ~0.42GB ≈ **3.2GB** → **1GB 服务器根本装不下**（差 3 倍多），这是改云端重排的根本原因。
  - **现方案（云端重排）1GB 偏紧但可行**：app 去 torch 后稳态实测 ~278MB、峰值估 ~400MB；加系统 ~250 + agent-lab ~166 + **Docker 守护进程 ~120（裸进程测量未含此项）** ≈ **936MB vs 物理 894MB** → 贴上限、靠 **2GB swap 兜底**，高负载可能因 swap 变慢（非丝滑）；600M 硬上限保证不挤死现有程序。**三点未坐实**：镜像未实建、完整问答瞬时峰值未精确测、Docker 开销未计入裸进程测量。
  - **用户决定：准备换 4GB 服务器**。4GB 账＝~940MB 占用、**余 ~3GB** → 不借 swap、运行丝滑、**服务器上直接构建镜像也无 OOM 风险**。**现有代码原样可跑 4GB，一行不用改**；唯一可选小调整＝部署脚本 `--memory=600m`→`1g`（重负载余量，600M 亦够）。**不建议趁 4GB 改回本地重排**（云端用同一模型 bge-reranker-v2-m3、效果一样且常免费，改回纯属把简单事搞复杂）。
  - **消除「1GB 不确定」的最划算一步（待用户说跑）**：本地用 api 后端真问一题、量完整问答峰值 RSS（一次付费 API，便宜），反推服务器宽裕度。**按 [[feedback-gate-long-runs]] 不自动跑**。换 4GB 后此实测必要性下降。

### 4.12 腾讯云 Windows 部署实录（2026-11-20，✅ 已完成并重启持久化验证）

**背景**：用户实际购入**腾讯云 Windows Server 2022**（公网 `175.178.177.74`，2 核 **2G**，宝塔 Windows 面板），放弃 Ubuntu/Docker 路线（4.11 的 Dockerfile/deploy_server.sh 留作 Linux 备用）。用户授**全权 SSH 操作**（ed25519 密钥 `~/.ssh/toolbook_deploy`，服务器键放 `C:\ProgramData\ssh\administrators_authorized_keys` + icacls 收权）。**老阿里云 47.107.249.54 的 agent-lab 依旧绝不动/绝不重启**；新腾讯服务器允许重启（已做重启测试）。

**访问恢复与系统修复**（`scripts/server_recon*.ps1` 只读体检 → `server_fix1/2/3.ps1`）：
- 用户重启后全端口失联，根因＝**Windows 防火墙服务 mpssvc 被 Stopped+Disabled**（重启后默认全丢包，连 RDP 都进不去）。修复：mpssvc 置 Automatic+启动+启用配置文件，建 `tb-ssh(22)/tb-rdp(3389)/tb-bt(27750)/tb-app(8501)` 放行规则。
- 宝塔面板端口 `C:\BtSoft\panel\data\port.pl` 原为 8888，与云侧已有规则 27750 不符 → 改写 27750 + 重启 btPanel。
- 页面文件原系统托管偏小 → 注册表 `PagingFiles="C:\pagefile.sys 2048 4096"`（重启生效，实测 AllocatedBaseSize=2048）。
- 分层定位法：loopback / 内网 IP(10.1.0.17) / 公网 IP 三层 connect 测试区分 OS 防火墙 vs 腾讯云防火墙。**OS 侧全通后公网仍丢包＝腾讯云控制台防火墙只放行了 22**，需用户在控制台补 3389/27750/8501（截至部署完成仍待用户操作）。

**环境与传输**：Python 3.13.9 走 **npmmirror 二进制**静默装 `C:\Python313`（GitHub 直连会卡）；venv `C:\toolbook\.venv`；pip 清华源装 `requirements-cloud.txt`（**零 torch**）。项目+书库 tar 56M（排除 .venv/.git/.env/data/models/eval 等）→ `C:\toolbook`；`.env` 单独 scp（4 键：SILICONFLOW_API_KEY / TOOLBOOK_AUTH_USER=hish / TOOLBOOK_AUTH_PASS=hish / TOOLBOOK_RERANK_BACKEND=api），**全程未显示密钥**。

**启动与自启**：`C:\toolbook\start.ps1`（源 `scripts/server_start.ps1`）解析 .env→进程环境、PYTHONIOENCODING=utf-8、**PYTHONFAULTHANDLER=1**、无头 Streamlit 0.0.0.0:8501、末尾 **`exit $LASTEXITCODE`**。计划任务 **ToolBookApp**（`scripts/server_register_task.ps1`）：AtStartup、SYSTEM 最高权限、失败重启 3 次/间隔 1 分钟、无执行时限。调试用临时任务 tbfix1/tbinstall/tbappdebug 已删除。

**静默崩溃排查（本次最大坑）**：问答提交后数秒 app 无 traceback「exit 0」消失，复现 3 次；前台 SSH 对照同样死 → 排除计划任务因素。**Application 事件日志 APPCRASH**：python.exe 崩溃模块 **MSVCP140.dll 14.0.24215.1（2016 老版 VC++ 运行库）**、异常 c0000005 → chroma 的 hnswlib C++ 扩展需要新版运行库，一调即原生崩溃（Python 层无异常）。修复：官方 `vc_redist.x64.exe`（aka.ms/vs/17/release）静默装 → **14.44.35211.0**，无需重启即愈。

**验收（SSH 隧道 18501→8501 + browser-use，绕过云防火墙）**：
- 登录门：错密码拒 ✓、hish/hish 进 ✓、双书在库 ✓、「云端重排」标签 ✓。
- 真实问答「奈奎斯特采样定理…混叠」：3 句全核验通过、出处 3.1 节(p21)、出处目录 5 条重试 0、学习参考完整、8806 tokens/6 次调用/重排走云端 API ✓。
- **重启持久化测试全绿**：mpssvc/sshd/btPanel 均 Automatic+Running；ToolBookApp 开机自启 8501；pagefile 2048M 生效；3389/27750 监听；重启后问答复验 ✓（9205 tokens/7 次调用）。
- **内存实测**：app 稳态 ~350MB；重启前 free 仅 87MB（紧），重启后 free 511MB、pagefile 用 103MB → **2G 可用但不宽裕**（Defender ~300MB 是大头），诚实告知用户。

**遗留**：① 腾讯云控制台防火墙放行 3389/27750/8501（用户操作，OS 侧已就绪）；② 弱密码 hish/hish 建议改强（已多次提醒）；③ 公网直连验收待①完成后补。

---

## 5. 代码结构（每个文件职责）

### 核心包 `src/toolbook/`
| 文件 | 职责 |
|---|---|
| `config.py` | 全局配置：数据目录、DB/Chroma 路径、硅基流动模型与 base_url、密钥读取、重排设备 |
| `models.py` | 数据类：Block / ParsedDocument / SectionNode / ImportResult / VerifiedSentence / SourceRef / StudySection / StudyGuide / AnswerResult / PaperInfo |
| `llm.py` | **硅基流动唯一云端出口**：`embed_texts` / `chat` / `rewrite_query` / `alternative_query` / `contextualize_query` / `summarize_turns` / `propose_titles` / `rerank_api`（云端重排 `/v1/rerank`，按 index 还原同序分）；用量累加器（含 `rerank_calls`）；httpx IPv6 坑修复 |
| `parsers/base.py` | 解析器公共接口/工具 |
| `parsers/docx_parser.py` | DOCX（python-docx，标题样式） |
| `parsers/epub_parser.py` | EPUB（ebooklib，NCX/NAV 目录） |
| `parsers/pdf_pymupdf.py` | PDF 默认解析（PyMuPDF，书签锚点/字号启发） |
| `parsers/pdf_mineru.py` | MinerU 适配器（`TOOLBOOK_PDF_PARSER=mineru` 切换，编号空格归一化） |
| `structure.py` | 章节树识别（规则优先 + `_llm_fallback_nodes` 兜底，防编造）；`is_non_content_section`/`prune_non_content` 非知识节过滤 |
| `chunking.py` | 父子块 small-to-big 切分 |
| `store.py` | SQLite 元数据/原文：`import` 幂等、`get_tree` / `get_section` / `list_documents` / `delete_sections`（FK 级联） |
| `importer.py` | 导入流水线编排（`import_file`，`llm_fallback=True` 默认开；入库前 `prune_non_content` 剪非知识节） |
| `bm25_index.py` | jieba + rank_bm25 内存关键词索引 |
| `vector_index.py` | Chroma PersistentClient 向量索引（`build_vector_index` / `vector_search`，bge-m3；`doc_ids` 多书 `$in` 过滤） |
| `rerank.py` | 重排分发：`TOOLBOOK_RERANK_BACKEND`＝`local`（默认，bge-reranker-v2-m3 交叉编码器 CPU，懒加载，失败永久降级 None）/ `api`（走 `llm.rerank_api` 云端，免 torch，失败临时降级 None）；`off` 开关与空候选前置 |
| `auth.py` | **应用内登录门**（纯函数离线可测）：`auth_enabled`（用户名+密码环境变量都非空才开启）/ `verify_login`（`hmac.compare_digest` 常量时间字节比较，兼容中文密码）；凭据只走环境变量，绝不硬编码 |
| `retrieval.py` | `hybrid_search`：改写→BM25+向量→RRF→父块去重（`doc_ids` 多书锁库）→重排（标题前缀）→top_k SearchHit |
| `verify.py` | 两级核验：`normalize` / `mechanical_ok` / `split_sentences` / `judge_sentence` / `verify_draft` |
| `answering.py` | `generate_draft`：逐句带引用草稿（JSON 协议 insufficient/sentences，摘录须原话） |
| `agent.py` | LangGraph 编排 + `ask()` 主入口（reset/snapshot 用量、挂 study、`doc_ids` 选书/锁库透传） |
| `paper.py` | `parse_paper → PaperInfo`（双栏自然顺序、标题区域限定）；`list_papers(dir)` 扫目录列 PDF（按 mtime 倒序，只读元信息不解析，供论文列表秒开） |
| `session.py` | `Turn / Conversation` 对话记忆（截断/压缩/清空） |
| `study.py` | `build_study_guide`：命中节复核 + [相关推荐]跨章简介（编号校验、降级） |
| `sources.py` | `group_sources_by_book`：出处按书名分组（保留原始索引 i 供角标对齐）；`section_label`：节标签去编号重复（标题自带「第X章」时不叠加数字编号），均纯函数离线可测 |
| `evaluation.py` | **M5 评测与消融打分**（纯函数离线可测）：`hit_level`/`score_question`/`aggregate`/`select_configs`/`format_markdown` + 消融配置矩阵 `ABLATION_CONFIGS`（A–E） |
| `cli.py` | 命令行入口：import/list/tree/show/index/search/ask |

### 界面与脚本
- `app.py`：Streamlit 1.67.0 主程序（侧边栏导入/目录树 + 双页签问答 + `render_answer`/`render_study`/`render_stats`）。**内核与 UI 分离**。页签名：**知识点检索**（原模块A）/ **论文检索**（原模块B）。知识点检索含**选书多选框**（默认全选，出处按书分组，见 4.9）；论文检索为**列表→详情两视图**（见 4.5）。
- `scripts/make_demo_books.py`：生成三格式示例书。
- `scripts/demo_m1.py`：导入+章节树+直查+幂等演示。
- `scripts/demo_m2.py`：混合检索演示。
- `scripts/demo_m3.py`：归纳/摘录/超纲三场景演示。
- `scripts/demo_m4.py`：论文问答两题（附库内出处 6.2/7.4）。
- `scripts/eval_m3.py`：20 题评测（报告 `data/eval/m3_report.json`）。
- `scripts/eval_m5.py`：**M5 评测与消融 live 跑分器**（A–E 五组各对 30 题跑完整 `ask()`，增量落盘 `data/eval/m5_report.json` + 一页 `docs/评测报告-M5.md`；`--configs` 子集、`--resume` 续跑）。纯打分逻辑在 `evaluation.py`（已单测），脚本本身是触网运行器。
- `scripts/clean_library.py`：**资源库清理运行器**（备份 db → 分类器剔非知识节 → 重建向量索引 → 报告实删数，见 4.10）。判定逻辑在 `structure.py`（已单测），脚本本身触库。
- `scripts/deploy_server.sh`：**云端部署运行器**（服务器项目根内跑：装 docker.io→建精简镜像→`--memory=600m` 上限运行→探活→复核现有程序 7860 未动，见 4.11）。配套 `Dockerfile`/`.dockerignore`/`requirements-cloud.txt`/`.env.example`/`docs/部署指南.md`。

### 测试 `tests/`（共 **165 个 pytest 全过**）
`test_chunking / test_store / test_importer / test_mineru_adapter / test_structure / test_parsers / test_bm25 / test_vector_index / test_rerank / test_retrieval / test_verify / test_llm_fallback / test_paper / test_session / test_answering / test_llm / test_agent / test_study / test_evaluation / test_sources / test_auth`。
- 全部**离线**：假检索/假生成/假核验/假 LLM 客户端，不触网。
- TDD 纪律：先写失败测试（RED）→ 最小实现（GREEN）→ 重构（REFACTOR）。

---

## 6. 核心数据模型（`models.py`）

```python
Block(text, kind="heading|paragraph", level, locator)          # 解析块
ParsedDocument(title, blocks)                                   # 解析结果
SectionNode(number, title, level, source="original|system", locator, text, children)  # 章节树节点
ImportResult(doc_id, title, fmt, skipped, sections, chunks)     # 导入结果

VerifiedSentence(text, kind="excerpt|summary", ref, badge="mechanical|llm", quote)  # 核验通过句
SourceRef(doc_title, number, title, source, locator)            # 出处目录条目
StudySection(doc_title, number, title, locator, source, summary="")  # 学习指引中的一节
StudyGuide(matched=[], recommended=[])                          # 命中节 + 相关推荐节
AnswerResult(sentences, sources, refused=False, retries=0, searched=[], message="", stats={}, study=None)
PaperInfo(title, outline, abstract, n_pages)                    # 模块B 论文上下文（不入资源库）
```
- `SearchHit`（在 `retrieval.py`）：`doc_id, section_id, number, title, source, locator, text, score, matched_by, doc_title`。
- 溯源链：`Chunk → Section → Document`，任何检索结果都能回溯原文。

---

## 7. 运行方式

### 7.1 环境
- 包管理 **uv 0.13.4** + `.venv`（**Python 3.13.9**）。
- 依赖见 `pyproject.toml`：langgraph≥1.2.22、chromadb、openai、pymupdf、mineru[core]≥4.2.3、python-docx、ebooklib、jieba、rank-bm25、sentence-transformers、streamlit≥1.67.0、beautifulsoup4、lxml；dev：pytest≥9.2.0。
- 安装/同步：`uv sync`。

### 7.2 配置密钥（必须）
项目根目录建 `.env`（**已 gitignore，绝不提交、绝不贴聊天**），填：
```
SILICONFLOW_API_KEY=你的硅基流动密钥
```
读取顺序：环境变量 `SILICONFLOW_API_KEY` 优先，其次项目根 `.env`（见 `config.load_api_key`）。LLM 与 embedding **共用一个 base_url 和一个 Key**。

### 7.3 启动 Web 界面（最常用）
在项目根目录终端运行：
```bash
uv run streamlit run app.py
```
- 首次运行会问邮箱，**直接回车跳过**。
- 浏览器打开 **http://localhost:8501**（端口被占用会自动改 8502，以终端 `Local URL` 为准）。
- 换端口：`uv run streamlit run app.py --server.port 8502`。
- **必须用 `streamlit run`，不能用 `python app.py`**（后者是裸模式，只刷 `missing ScriptRunContext` 警告然后退出，不起服务）。
- PyCharm 点绿三角运行：把运行配置改成 **Module name=`streamlit`，Parameters=`run app.py`**，工作目录设为项目根。
- 后台是**独立进程，不依赖 PyCharm**；关机/关终端会停，重启跑同一命令即可。**资源库数据（data/）持久保留，聊天内存态清空**。

### 7.4 命令行 CLI
```bash
uv run python -m toolbook.cli import 书1.pdf 书2.docx 书3.epub   # 导入（幂等）
uv run python -m toolbook.cli list                              # 列出已导入文档
uv run python -m toolbook.cli tree 1                            # 显示 doc_id=1 章节树
uv run python -m toolbook.cli show 1 3.1                        # 按章节号直查原文
uv run python -m toolbook.cli index [--force]                   # 建/重建向量索引（调 bge-m3）
uv run python -m toolbook.cli search "奈奎斯特 采样" [-k 5] [--doc 1] [--no-llm] [--no-rerank]
uv run python -m toolbook.cli ask "采样定理说了什么" [--no-rerank]  # 两级核验问答（CLI 仍打印机械✓/LLM✓徽章，调试用）
```

### 7.5 演示与评测脚本
```bash
uv run python scripts/demo_m1.py     # 导入管道
uv run python scripts/demo_m2.py     # 混合检索
uv run python scripts/demo_m3.py     # 核验三场景
uv run python scripts/demo_m4.py     # 论文问答
uv run python scripts/eval_m3.py     # 20 题评测（约 35 分钟，CPU 重排是瓶颈）
```

### 7.6 测试
```bash
uv run pytest          # 全量 165 个，离线不触网
```
- Windows Git Bash 下建议 `PYTHONIOENCODING=utf-8`。
- **不要用 `pytest | tail`**（管道会掩盖 pytest 退出码），单独跑。

---

## 8. 关键配置与环境变量（`config.py`）

| 项 | 值 |
|---|---|
| 项目根 / 数据目录 | `PROJECT_ROOT` / `data/`（已 gitignore） |
| SQLite | `data/library.db`（`DEFAULT_DB`） |
| Chroma | `data/chroma/`（`CHROMA_DIR`） |
| 硅基流动 base_url | `https://api.siliconflow.cn/v1` |
| 对话模型 | `deepseek-ai/DeepSeek-V3.2`（`CHAT_MODEL`） |
| Embedding | `BAAI/bge-m3`（`EMBED_MODEL`，免费，1024 维） |
| 重排模型 | `BAAI/bge-reranker-v2-m3`（`RERANK_MODEL`，本地/云端共用模型名） |
| 云端重排接口 | `https://api.siliconflow.cn/v1/rerank`（`RERANK_API_URL`，与向量化同密钥） |
| 重排本地目录 | `data/models/bge-reranker-v2-m3`（`RERANK_MODEL_DIR`，存在则离线优先；云端 api 后端不用） |
| 重排设备 | `cpu`（`RERANK_DEVICE`，避免与 MinerU 争显存） |

| 环境变量 | 作用 |
|---|---|
| `SILICONFLOW_API_KEY` | 硅基流动密钥（或写 `.env`） |
| `TOOLBOOK_PDF_PARSER=mineru` | 切换 PDF 解析器为 MinerU（默认 PyMuPDF） |
| `TOOLBOOK_RERANK=off` | 关闭重排（降级 RRF 序） |
| `TOOLBOOK_RERANK_BACKEND=api` | 重排走云端硅基流动 API（免 torch，云镜像默认）；缺省 `local` 本地模型 |
| `TOOLBOOK_AUTH_USER` / `TOOLBOOK_AUTH_PASS` | 应用登录门账号密码（**两项都非空才开启门**；本地不设＝关闭；云部署经 `.env`→`--env-file` 注入，绝不硬编码） |
| `TOOLBOOK_RERANK_DEVICE=cuda` | 本地重排改用 GPU（默认 cpu；api 后端无关） |
| `HF_ENDPOINT` | HF 镜像（rerank.py 默认设 `https://hf-mirror.com`） |

---

## 9. 里程碑进度（按 11.30 截止倒排）

| 阶段 | 排期 | 状态 | 验收 |
|---|---|---|---|
| **M1 导入管道** | 11.18–11.20 | ✅ 11.18 完成 | 三格式各 1 本导入成功，章节号与原书目录一致；26 测试 |
| **M2 混合检索** | 11.20–11.23 | ✅ 11.18 完成 | 关键词/语义查询均命中正确章节号；46 测试 |
| **M3 核验与回答** | 11.23–11.26 | ✅ 11.18 完成 | 20 题：在库宽松命中 13/16=81%（≥80% 达标），超纲 4/4 拒答；68 测试 |
| **M4 论文问答+UI** | 11.26–11.28 | ✅ 11.18 完成 | CORE 上传→30 条目录→知识点提问附库内出处（6.2/7.4），浏览器端到端通过；79 测试 |
| **M4 增强：上下文记忆** | — | ✅ 完成 | A 5 轮 / B 按论文独立+自动压缩+换论文隔离；6 例抽检通过；87 测试 |
| **M4 再增强：回答展示** | — | ✅ 完成（commit `b64fa7a`） | 五项要求浏览器验证通过；**107 测试** |
| **M5 评测与演练** | 11.28–11.29 | ✅ 评测+消融完成（11.19 提前） | 30 题 A–E 五组消融跑完：E 完整系统宽松 17/22(77%)、拒答 8/8(100%)；**调优①重排标题前缀后锁 doc1 重跑 E→19/22(86%)、零回归**；报告落盘；剩 3 题（空正文/公式召回）待②③；彩排录屏待办 |
| **M5 UI 重设计** | 11.19 | ✅ 完成 | 页签改名（知识点检索/论文检索）+ 论文检索列表→详情两视图（磁盘持久列表+懒解析+独立记忆）；**121 测试**+浏览器验证 |
| **M5 选书+分书目参考** | 11.19 | ✅ 完成 | 知识点检索多选书（默认全选）→综合答案→出处按书分组；doc_id 泛化 doc_ids 多书锁库；**134 测试**+程序化端到端验证（界面交互受隐藏视口限制） |
| **M5 学习参考改名+非知识节清理** | 11.19 | ✅ 完成 | 面板改名「学习参考」；分类器+导入即剪枝+清库删 103 节（doc1 62/doc2 41），正式章节与知识附录全保留，索引重建一致；**143 测试** |
| **M5 学习参考展示理顺** | 11.19 | ✅ 完成 | 学习参考面板去 [系统编号] 徽章（出处目录保留）；`section_label` 理顺「1 第一章」编号+标题重复；**150 测试**+页面加载验证 |
| **M6 云端部署适配** | 11.19 | ✅ 代码就绪（待用户部署） | 云端重排 API（去 torch）+ 登录门 `auth.py` + 精简 Dockerfile/部署脚本/指南；依赖解析零 torch、登录门浏览器端到端验证；**165 测试**；镜像未实建（两端均无 Docker），真实云端重排付费调用待部署时验证（见 4.11） |
| 比赛 | 11.30 | — | 提交作品包 |

> M1–M4 均**提前于排期**完成。实施计划在 `docs/superpowers/plans/2026-11-18-m1/m2/m3/m4/m4b-*.md`。

### M5 评测与消融脚手架（已实现，待审核+跑分）

**消融矩阵**（每组对同一 30 题跑**完整 `ask()`**，核验链全程开启不消融——宁缺勿错是招牌）：

| 组 | 标签 | use_bm25 | use_vector | use_llm（双语改写） | use_rerank |
|---|---|---|---|---|---|
| A | 纯 BM25 | ✓ | ✗ | ✗ | ✗ |
| B | 纯向量 | ✗ | ✓ | ✗ | ✗ |
| C | 混合 RRF | ✓ | ✓ | ✗ | ✗ |
| D | +双语改写 | ✓ | ✓ | ✓ | ✗ |
| E | 完整系统 | ✓ | ✓ | ✓ | ✓ |

> 用户选定**跑完整问答**而非仅检索层；故 **E 组即 30 题端到端最终成绩**，与评测合并为**一个脚本** `eval_m5.py`（不再单写端到端脚本，DRY）。

**开关透传链**（默认全开，旧调用零影响）：`ask(use_bm25/use_vector/use_llm/use_rerank)` → `AgentState` → `retrieve_node` → `hybrid_search(use_bm25/use_vector)`。`retrieval.py` 关某路时该路 `search`/`vector_search` **绝不调用**（已单测断言）。

**跑分命令**（触网，约 **4–5 小时**，**不会自动启动**，等用户审核题库后明确说跑）：
```bash
# 全量五组（A→E），每跑完一组增量落盘，中断可续
PYTHONIOENCODING=utf-8 uv run --no-sync python scripts/eval_m5.py
# 只跑某几组 / 续跑已完成的
... python scripts/eval_m5.py --configs C,E
... python scripts/eval_m5.py --resume
```
产物：`data/eval/m5_report.json`（逐题+逐组）+ `docs/评测报告-M5.md`（一页对比表）。纯打分逻辑在 `evaluation.py`（7 单测），脚本本身是 live 运行器。

**题库状态**：`tests/fixtures/m5_questions.json` 30 题，22 在库（章 2/3/4/5/6/7/8/9/10/11/13/14/15/25，含公式题 id11→7.4、英文 id12/13、极化 id22→25.2）+ 8 超纲（id23–30：QCD/CRISPR/唐朝科举/LLM KV cache/AlphaFold/Black-Scholes/烤面包/莫奈）。**所有 expect 节号已对书目录核验真实（零编造）**。✅ **用户已于 2026-11-18 审核通过**，择时跑分。

### M4 再增强五项要求（全部落地）
1. **公式→章节**：改写/上下文化提示词加「遇公式/符号先识别对应知识点概念，用概念术语检索」引导。CORE LMMSE 估计式提问命中教材 **7.4 节（p31）** 并给出公式 `bh = RhA^H(ARhA^H+C)^-1 y`。
2. **出处先节号后页码**：答案顶部置顶「出处节号 → 页码：7.4 节（p31）」。
3. **供研究生学习面板**：命中节 LLM 复核 + `[相关推荐]`跨章简介（见 4.7）。
4. **去掉句首机械✓/LLM✓徽章**：UI 句子直接展示（badge 字段仍在数据里，核验链不动）；出处目录保留 `[系统编号]` 标记（D5 卖点）。
5. **token 消耗 + 调用次数**：见 4.8。

---

## 10. 验收实测数据

- **M2（ISAC 书）**：关键词「奈奎斯特 采样 混叠」与语义「怎样从离散样本无失真地恢复连续信号」均把 **3.1（p21）** 排第一（重排分 0.84/0.58）；英文跨语言查询命中第 3 章相关节；章节号直查旁路正常。
- **M3（20 题，`data/eval/m3_report.json`）**：在库 16 题严格命中 13、宽松命中 13（**81%**，达标线 80%）；超纲 **4/4 正确拒答**。未命中 3 题留 M5：Q2 两径卷积（期望 3.2 得 3.1）、Q9 SVD 可观测方向（期望 5.3 得 5.2）、Q16 英文 Doppler ICI（期望 8.4 得 8.3）——均为**相邻节混淆**，方向是查询改写/重排调优，**不砍核验链**。
- **M4 抽检（`docs/问答抽检-M4.md`）**：6 例+隔离。A1/A2 PASS（A2 追问靠记忆补全复基带采样率 3.1）；B3 PASS（7.4 公式+附录 B.1 正交原理推导）；B4 初测 FAIL→修复后 PASS（「它」锚定 LMMSE）；换论文隔离 PASS。**B1/B2 部分通过**：内容正确可溯源但章节排序偏差（B1 期望 2.3 实得 1.1/3.4；B2 期望 5.2 实得 5.1），与 M3 同类，留 M5。
- **M5 消融（30 题，`data/eval/m5_report.json` + `docs/评测报告-M5.md`，2026-11-19 跑完）**：A 纯BM25 宽松 11/22(50%)｜B 纯向量 17/22(77%)｜C 混合RRF 15/22(68%)｜D +双语改写 17/22(77%)｜**E 完整系统 17/22(77%)**；**超纲拒答全组 8/8(100%)**。组件贡献：向量是主力(A→B +27pt)；朴素RRF融合反而稀释(C<B，BM25噪声拖累)；双语改写救回(D=C+公式/英文/极化)；重排净持平但换血(E帮id6/12、挤掉id2/8)。**剩 5 个未命中全是相邻节混淆**（id2 3.2→3.1、id8 5.3→5.2、id13 8.4→8.3、id14 9.2→9.1、id21 15.2→15.1，均落目标前一节、重试0次内容核验通过）→ 调优方向是**节级区分度**，不砍核验链。**调优①已落地（11.19）**：重排文本加节标题前缀（`retrieval.py:100`），锁 doc1 重跑 E **17→19/22(86%)、救回 id2/id8、零回归**（`docs/检索调优验证-M5.md`）；剩 id13/14/21 为 9.2 空正文（导入个例 bug）+ 8.4/15.2 公式节召回不足，待②局部重导/③标题进索引。
- **M4 再增强（浏览器端到端）**：
  - 模块 A（奈奎斯特采样定理）：出处「3.1 节（p21）」；3 句无徽章；学习面板命中 3.1 + 4 个 [相关推荐]（3.2/3.3/3.4/11.1）带简介；统计「7440 tokens（输入 7012/输出 428）· 模型调用 6 次（对话 5/向量化 1）· 重排本地不计费」。
  - 模块 B（LMMSE 公式题）：返回 **7.4 节（p31）** 含公式；学习面板命中 7.4 + [相关推荐] P6.S2.S1 B.1[系统编号]/14.2 Fisher/5.2 最小二乘 带简介；无徽章；统计「8313 tokens（输入 7936/输出 377）· 模型调用 7 次（对话 6/向量化 1）」。
- **跨语言实测（2026-11-19，锁 doc2 英文书《Integrated Sensing and Communications》，`data/eval/crosslingual_doc2.json`）**：验证「中文提问 → 英文资源库」。**4 个书内中文问题全部命中预期章**：雷达测距测速→3.5.1 FMCW Radar(p127)+7.5.3 Chirp(p265)（4 句摘录✓）；频谱共享→4 章(p166)+4.2.2 Sampling(p178)+8.2（6 句归纳+摘录✓）；干扰管理→14.2.2(p447)+14.2+14 章(p441)（1 句摘录✓，答案偏薄但命中正确）；无人机检测成像→17.1 被动雷达(p492)+17.2.4 微多普勒+17.3.1（6 句中文归纳✓，含 DVB-T/SPWVD/AoS）。**超纲对照（明朝内阁）正确拒答**（重试 2 次）。机制：双语改写（`llm.rewrite_query` 出英文关键词）+ bge-m3 多语言向量；摘录句锚英文原文子串、归纳句中文经 LLM 裁判+quote 双锚定。**答案中文呈现、出处标英文书节号+页码**。5 题合计约 44366 tokens、43 对话+8 向量化调用。运行器 `data/eval/crosslingual_check.py`（gitignored，一次性验证记录）。

---

## 11. 踩过的坑与经验（重要，避免重蹈）

1. **MinerU 版本**：实际装的是 **4.2.3**（非详解文档的 2.x），进程内 `mineru.parser.parse()` 可用、无需起服务；模型约 1GB（llama.cpp VLM + ONNX 布局/OCR，DirectML）。OCR 在编号点号旁加空格（"1 . 1"），适配器已归一化。
2. **httpx IPv6 坑**：系统 `NO_PROXY` 含 `[::1]` 会让 openai SDK 底层 httpx 抛 `InvalidURL`；`llm._make_http_client()` 构造时临时剔除 IPv6 条目再恢复。
3. **BM25 IDF 退化**：rank_bm25 的 IDF 在「词出现于恰好一半文档」时为 0；小测试夹具需 **≥3 文档**避免退化（真实 551 块库无此问题）。
4. **reranker 下载**：hf-mirror 会卡死（64MB 后停滞）；改 **ModelScope** `snapshot_download('BAAI/bge-reranker-v2-m3', local_dir='data/models/bge-reranker-v2-m3')` 几分钟完成；rerank.py 优先加载该本地目录，断网可用。CPU 加载约 2 秒，打分区分度好（0.996 vs 0.008）。
5. **双栏论文解析**：必须用 PDF **自然存储顺序**取文本，书籍解析器按 y 排序会把双栏交错；标题只取首页上 35% 区域最大字号行（CORE 正文 28.5pt 首字母 "I" 会误判）。
6. **指代消解规则必须条件化**：追问锚定历史的规则只在「有历史+追问」时生效，无条件版会削弱无历史首问的论文背景展开（B3 一度丢 7.4 公式）。
7. **study 节号回显 bug（已修）**：目录标题本身已含节号（title="3.1 采样…"），catalog 描述「number title」重复节号，LLM 把整行「3.1 3.1 采样…」当节号回显 → `h.number in keep` 全失配 → 学习面板空。修复：`_norm_number` 取首个空白 token + 提示词去重复节号 + 明确「只输出节号本身」。**教训：LLM 回显的编号要归一化校验，不能假设它只吐编号。**
8. **学习指引简介小局限（可接受降级）**：系统编号节（如 P6.S2.S1 对应标题 B.1）LLM 简介可能按标题号返回 key，导致 `summaries.get(number)` 取空 → 该推荐节无简介但仍显示节号+标题+页码+[系统编号]。未过度工程化修复。
9. **Streamlit 热更新**：改 `src/` 下模块后运行中的服务**不一定热更新**（模块缓存），需**重启服务**；但改 `app.py` 主脚本每次 rerun 重新执行，点侧边栏 checkbox 触发 rerun 即可用新代码重绘存量答案。
10. **Streamlit chat_input 提交（browser-use 自动化关键）**：browser-use 的 click 发送按钮 / press_key Enter 都**不触发** React 提交。必须用 `evaluate_script` 原生 click：`document.querySelector('button[data-testid="stChatInputSubmitButton"]').click()`；模块 A/B 两个 chat_input 共存时选 **enabled 的那个**（`[...querySelectorAll(...)].filter(b=>!b.disabled)` 取最后一个=当前活动页签）。提取答案用 evaluate_script 开 details + 取 `stMain.innerText`（**15s 硬超时**，长等待用 Bash sleep 100–110s + 短脚本）。
11. **评测耗时**：20 题全量约 **35 分钟**（超纲题各跑满 3 轮检索，共约 40 轮，每轮 CPU 重排是瓶颈）；后台管道输出有缓冲，中途看不到逐题进度，只能看进程 CPU 时间判断是否卡死。
12. **GitHub 推送**：连接间歇性重置，push 失败时隔几分钟重试即可。
13. **`pytest | tail` 掩盖退出码**：单独跑 pytest，别接管道。
14. **Windows VC++ 运行库过旧 → 原生静默崩溃**：Server 2022 自带 MSVCP140.dll 14.0（2016），chroma/hnswlib 等新版 C++ 扩展一调就 c0000005 崩溃，**Python 无 traceback、进程直接消失**。装最新 `vc_redist.x64.exe`（14.44）即愈。**进程无声死亡先查 Application 事件日志的 APPCRASH（WER 1000/1001），别只盯 app 日志。**
15. **`powershell -File` 掩盖原生退出码**：脚本里 python 崩溃，powershell 自身仍返回 0 → 「exit 0」假象。启动脚本末尾必须 `exit $LASTEXITCODE`（计划任务失败重启也依赖真实退出码）。
16. **mpssvc 被禁用 = 重启后全端口失联**（含 RDP/SSH，只能控制台 VNC 救）；防火墙服务必须 Automatic。mpssvc 停止时 CIM NetFirewall cmdlets 报 1753。宝塔 Windows 面板端口在 `C:\BtSoft\panel\data\port.pl`，改后重启 btPanel。
17. **Git Bash `ssh-keygen -N '""'` 会设字面 `""` 密码**（不是空密码），必须 `-N ""`；Windows 管理员 SSH 公钥放 `administrators_authorized_keys` 而非用户目录，且要 icacls 收权到 Administrators/SYSTEM。
18. **.env 追加粘连**：原文件末行无换行符时，追加的第一行会粘到末行（密钥损坏）。重建文件显式补换行；scp 覆盖后按键数验证。

---

## 12. 安全与协作约定

- **密钥**：只放 `.env`（用户自己填）或环境变量 `SILICONFLOW_API_KEY`；**绝不贴聊天、绝不提交**；`.env` 已 gitignore。
- **数据**：书/论文 PDF 存 `data/`（已 gitignore），**不提交**；`data/library.db`、`data/chroma/`、`data/models/` 均本地持久。
- **Git**：仓库 https://github.com/hish-hish/toolbook-paper-agent（**私有**）；master 跟踪 origin/master。**已推送至 `a3c9394`**（含 `ae4da30` 云端部署适配、`c55e343` 内存算账/换服务器决定、`f658ea7` 指针同步、`a3c9394` 腾讯云 Windows 部署实录+server_*.ps1 脚本入库）；2026-11-20 推送一次成功。
- **中文 commit**：每次新增 commit 说明用中文（可保留 `feat:/fix:/docs:` 前缀），正文中文；**不改写/翻译/rebase 已有历史**。
- **中文注释**：每个 `.py` 文件开头中文模块 docstring + 每个函数/类/功能块中文注释（zh-code-style 规范）。
- **核验链绝不砍**：工期再紧，两级核验 + 出处 + 拒答路径是底线，可砍的只有增强项（重排/双语改写可后置）。
- **开发流程**：设计确认 → 正式 spec（architectural 路径）→ 用户批准 → writing-plans → TDD 实现；bounded 小改动在对话给短设计获批后直接实现，不另写 spec/plan。

---

## 13. 下一步（M5，11.28–11.29，可提前）

### 今日任务（2026-11-19，用户指定三项）
1. **跑消融**：✅ **2026-11-19 跑完**（A–E 五组×30 题，exit 0）。最终成绩与组件贡献见 §10；报告 `data/eval/m5_report.json` + `docs/评测报告-M5.md`。E 完整系统宽松 17/22(77%)、拒答 8/8。剩 5 题相邻节混淆留检索调优。
2. **新增资料库**：✅ **用户自行完成（2026-11-19 13:33）**：通过界面侧栏导入第二本书 `Integrated Sensing and Communications`（Husheng Li 著，英文 PDF，22MB）→ **doc_id=2，688 章节行**，向量索引 13:33–13:42 自动重建。**关键时间线**：消融跑在 13:33 之前（当时仅 doc1），故 A–E 成绩**干净有效、未被污染**；此后所有诊断跑在 **doc1+doc2 双库**上，与消融**不是同一库状态**。`hybrid_search` 默认 `doc_id=None` 搜全库，doc2 同主题节会挤占 doc1 目标节候选位。**评测口径**：题库 30 题标准答案按 **doc1 章节号**出，衡量检索组件贡献须**评测锁 doc1**（`doc_id=1`），产品实际使用搜全库。
3. **UI 重新设计**：✅ **2026-11-19 完成**（页签改名知识点检索/论文检索；模块B 改列表→详情两视图，扫磁盘持久列表+懒解析+按论文独立记忆）。`list_papers` TDD 3 测试，全量 **121 测试**通过，浏览器端到端验证（列表→点进 CORE→目录+对话→返回）。详见 4.5。

### 其后
4. **选书检索 + 分书目参考**：✅ **2026-11-19 完成（用户批准 bounded 设计，TDD）**。知识点检索页签加多选书框（默认全选），`doc_id` 泛化为 `doc_ids` 多书锁库（向量 `$in` + 父块过滤），出处按书分组（`sources.py`，保留引用角标）。**134 测试全过** + 程序化端到端验证；界面交互验证受内置浏览器隐藏视口限制（详见 4.9）。**未提交②③（空正文/公式召回重建），需用户批准。**
5. **学习参考改名 + 非知识节清理**：✅ **2026-11-19 完成（用户批准保守档，TDD）**。面板「供研究生学习」→「学习参考」；`is_non_content_section`/`prune_non_content` 分类剪枝（只动 system，正式章节零误删）+ 导入即过滤 + `clean_library.py` 清现有库：doc1 删 62、doc2 删 41（共 103 节），重建索引 4534 条一致，知识附录全保留，备份可逆。**143 测试全过**（详见 4.10）。**展示理顺（同日，用户批准「只删学习参考面板」+「理顺」）**：学习参考面板去 `[系统编号]` 徽章（出处目录保留作 D5 卖点）；`sources.py:section_label` 去「1 第一章」编号+标题重复（标题自带「第X章/节/部分」时不叠加数字编号），三处渲染统一改用，**150 测试全过**（详见 4.7）。
6. **检索调优**：🔨 **进行中（2026-11-19）**。
   - **已改（TDD，未提交）**：重排文本加节标题前缀 `f"{h.title}\n{h.text[:1400]}"`（`retrieval.py:100`），新增测试断言重排文本含节标题，**122 测试全过**。离线重跑 5 miss：**救回 id2(3.2)/id8(5.3)→rank1**（这两节标题逐字对应问题、正文公式开头被 cross-encoder 压分，加标题前缀后纠正）。不碰核验链/向量索引。
   - **剩余 3 miss 完整根因（双库取证后）**：
     - **id14→9.2「用 SVD 把 MIMO 化成并行信道」：doc1 该节正文为空（0 字）**——doc1 全 296 节**唯一**空正文节，导入个例 bug（非系统性）。检索/重排救不了空节，按宁缺勿错本应拒答。修法：查导入流水线为何漏抽 9.2 正文，局部补抽/重导该节。
     - **id13→8.4(231 字)/id21→15.2(330 字)：正文极短几乎全公式**（doc1 有 57 节正文 1–120 字）。根因在**召回阶段**：索引文本（BM25 分词/向量 embedding）只喂正文，公式节缺主题词→目标节进不了 top-30 候选池；重排加标题只能救「已进池」的（id2/id8），救不了「没进池」的。修法：**节标题并入索引文本**（需重建向量索引，耗时+跑分期间禁做+需批准）。
     - **doc2 干扰（主要 id13）**：英文 ISAC 书同主题，doc2 的 17.2 Micro-Doppler 等节挤占候选；但那些节讲 micro-Doppler sensing 与「子载波间干扰 ICI」不完全对题。
   - **下一步 ROI 排序（待用户批准）**：① 评测锁 doc1 重跑 E 确认 title-prefix 净收益（不重建索引，~15–20min 付费 API，预计 17→19/22）→ 坐实后提交；② 修 9.2 空正文（局部重导，预计 +1→20/22）；③ 标题进索引+重建（救公式节召回，预计 →22/22，代价最大）。**未确认净收益前不提交 title-prefix；不擅自重建索引/重导/重跑。**
   - **① ✅ 完成（2026-11-19，用户批准）**：ask() 加 `doc_id` 参数透传检索节点（TDD +2 测试，**124 全过**）；`eval_m5.py` 加 `--doc-id` 锁库开关。锁 doc1 重跑 E（`data/eval/m5_E_doc1_titlefix.json`，不覆盖原消融报告）：**在库 17→19/22(86%)、拒答 8/8、救回 id2(3.2)/id8(5.3) 均升 rank1、零回归**（原 17 命中全保住）。BM25 语料漂移未致回归。**净收益坐实 → title-prefix 修复 + doc_id 接线 + 测试 + 报告已提交**。验证报告 `docs/检索调优验证-M5.md`。剩 id13/14/21 属②③（空正文/公式召回），非重排可解。
7. **演示彩排 + 录屏备份**（现场网络风险预案：提前预导入资源库、缓存 embedding）。
8. 整理**作品包**（评审形式为提交作品包，非现场答辩；消融对比表是实验数据卖点）。
9. **云端部署执行**：✅ **2026-11-20 完成（腾讯云 Windows 175.178.177.74，见 4.12）**——原生 Python+venv+计划任务自启（非 Docker），登录门+真实问答+重启持久化全部验收通过；VC++ 运行库过旧导致的静默崩溃已修（踩坑#14）。**剩用户一步：腾讯云控制台防火墙放行 3389/27750/8501**（OS 侧已就绪，当前公网仅 22 通）。原 Linux/Docker 方案（4.11、`docs/部署指南.md`）留作备用。**铁律不变：老阿里云 agent-lab 绝不动/绝不重启。** 弱密码 hish/hish 建议改强。

---

## 14. 关键文件索引

- 计划书（选型详解+里程碑）：`项目计划书.md`
- 决策点初学者详解：`docs/决策点详解/README.md`（D01–D13）
- 实施计划：`docs/superpowers/plans/2026-11-18-m1/m2/m3/m4/m4b-*.md`
- M4 问答抽检记录：`docs/问答抽检-M4.md`
- M3 评测报告：`data/eval/m3_report.json`（本地，不提交）
- 核心包：`src/toolbook/`（见第 5 节）
- 界面：`app.py`
- **云端部署**：`docs/部署指南.md`（Linux/Docker 备用方案）+ `Dockerfile` + `.dockerignore` + `requirements-cloud.txt` + `.env.example` + `scripts/deploy_server.sh`（见 4.11）；**Windows 实机部署（现行）**：`scripts/server_*.ps1`（recon 体检/fix1-3 修复/install_env 装环境/start 启动/register_task 自启/vc_redist 运行库，见 4.12）
- 依赖：`pyproject.toml`
- 配置：`src/toolbook/config.py`

---

*本文件由开发过程汇总而成，记录截至 2026-11-18（commit b64fa7a）。后续进展请同步更新此文件与项目记忆。*