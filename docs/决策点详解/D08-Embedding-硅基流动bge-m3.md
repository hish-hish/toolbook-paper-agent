# D8 Embedding：云端 API（推荐硅基流动 BAAI/bge-m3）

> 一句话：Embedding 模型是"语义翻译官"，把文字翻译成一串数字，让计算机能比较"意思像不像"；我们租用硅基流动的免费 bge-m3 来做这件事。

## 1. 这个决策点解决什么问题？

D7 的向量检索路需要先回答："两段文字意思有多接近？"计算机不懂文字，但懂数字。Embedding 模型就是中间的翻译官：

```
"傅里叶变换把信号分解为频率成分" → [0.12, -0.87, 0.33, ... ]（1024个数字）
"如何把信号拆成不同频率的叠加"   → [0.11, -0.85, 0.35, ... ]（数字很接近！）
"今天食堂的红烧肉不错"           → [-0.42, 0.66, -0.11, ...]（数字差很远）
```

比较两串数字的夹角（余弦相似度），就知道意思像不像。**英文问题和中文教材也能比**——多语言模型把两种语言翻译进同一个数字空间。

## 2. 为什么选云端 + 硅基流动 bge-m3（优势）

| 优势 | 说明 |
|---|---|
| **免费** | 硅基流动的 BAAI/bge-m3 长期免费，3 本书导入+比赛查询零成本 |
| 与 reranker 同家族 | D10 的 bge-reranker-v2-m3 和它同出 BAAI 一门，语义口径一致 |
| 不占显存 | 8GB 显存留给 MinerU 和 reranker |
| 一个 Key 管所有 | 硅基流动同平台托管 DeepSeek/Qwen 对话模型，LLM+embedding 共用一个 base_url 和一个 Key |
| 中英多语言强 | bge-m3 是开源多语言旗舰，正好覆盖你的中英混合资源库 |

**服务商对比结论**（2026-11-18 核实）：
- 硅基流动 bge-m3：免费，1024 维，单次输入上限 8192 token。担心限流可充值切 `Pro/BAAI/bge-m3`（同模型，只改模型名）。
- 阿里百炼 text-embedding-v4：¥0.5/百万 token，送 100 万免费额度，基于 Qwen3-Embedding，多语言更强。备选。
- **Qwen4 目前没有 embedding 模型**：Qwen4 尚未正式发布（只有 Qwen4-Max-Preview 对话模型），向量模型最新仍是 Qwen3-Embedding 系列。
- **DeepSeek 官方没有 embedding 接口**，别指望一个 Key 全包。

## 3. 在本项目中怎么工作（工作环节）

**导入时（批量）：**
1. 每个子块（D6）调一次 embedding API → 得到 1024 维向量。
2. 向量 + 元数据（章节号/父块ID）存入 Chroma（D9）。
3. 按文件哈希去重（计划书第7节），重复导入不重复计费。

**查询时（单次）：**
1. 用户问题（或改写后的语义查询）→ embedding API → 问题向量。
2. 拿问题向量去 Chroma 找最近的块。

接口是 OpenAI 兼容格式，代码里就是一个可配置的 `base_url + model + api_key`，换服务商改配置不改代码。

## 4. 初学者常见问题

- **Q：8192 token 上限够用吗？**
  A：子块才 300 字左右，远够。父块不直接向量化（检索用子块）。
- **Q：免费档会不会突然收费/限流？**
  A：有备胎：充值 Pro 版或切阿里 v4，都是改一行配置的事。
- **Q：向量维度 1024 是什么意思？**
  A：每段文字被翻译成 1024 个数字。维度越高表达越细腻但存储越大，1024 是效果/成本的甜点位。

## 5. 实操：怎么调模型、怎么换模型（已定案）

### 第一步：注册拿 Key（一次性，约 5 分钟）
1. 打开硅基流动官网 siliconflow.cn 注册账号（手机号即可）。
2. 进入控制台 →「API 密钥」→ 新建密钥，复制保存（形如 `sk-xxxx`）。
3. 把密钥放进项目根目录的 `.env` 文件（该文件不进 git、不上传）：
   ```
   SILICONFLOW_API_KEY=sk-你的密钥
   EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
   EMBEDDING_MODEL=BAAI/bge-m3
   ```

### 第二步：代码调用（OpenAI 兼容接口，装 openai 库即可）
```python
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(
    api_key=os.getenv("SILICONFLOW_API_KEY"),
    base_url=os.getenv("EMBEDDING_BASE_URL"),
)

resp = client.embeddings.create(
    model=os.getenv("EMBEDDING_MODEL"),   # BAAI/bge-m3
    input="傅里叶变换把信号分解为频率成分",
)
vector = resp.data[0].embedding           # 1024 个数字，存进 Chroma
```
批量导入时 `input` 可以传字符串列表一次嵌入多块；免费档有限流，代码里做分批 + 失败退避重试。

### 第三步：同一个 Key 顺便调对话模型（D2 的 LLM）
```python
resp = client.chat.completions.create(
    model="deepseek-ai/DeepSeek-V3",      # 或 Qwen 系列，硅基流动均有托管
    messages=[{"role": "user", "content": "把问题改写成中英检索关键词：..."}],
)
```
具体可用的对话模型名以硅基流动控制台「模型广场」实时列表为准。

### 换模型 = 改配置，不改代码
| 场景 | 改法 |
|---|---|
| 免费档限流，想要稳定保障 | `.env` 里模型名改 `Pro/BAAI/bge-m3`（充值，同模型） |
| 想要 32K 长输入 | 改 `Qwen/Qwen3-Embedding-8B`（付费；注意维度变化需重建索引） |
| 整体换阿里百炼 | base_url 改 `https://dashscope.aliyuncs.com/compatible-mode/v1`，模型改 `text-embedding-v4`，Key 换百炼的 |

**注意**：不同模型的向量空间互不兼容，换 embedding 模型后必须把 Chroma 里的旧向量删掉重新导入（导入幂等设计让这件事一键完成）。