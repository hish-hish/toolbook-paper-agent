# 云端精简镜像：去 torch/sentence-transformers/mineru，适配 1GB 内存云服务器。
# 重排走硅基流动 API（TOOLBOOK_RERANK_BACKEND=api），PDF 走默认 PyMuPDF。
# data/（资源库/向量/密钥）运行时挂载，绝不烤进镜像；.env 由 --env-file 注入。
FROM python:3.13-slim

# 系统库：build-essential 兜底个别源码包编译；libgomp1 供 onnxruntime（chromadb 依赖）运行
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用 Docker 层缓存，代码改动不重装依赖）；只装云端精简清单，绝不装 torch
COPY requirements-cloud.txt ./
RUN pip install --no-cache-dir -r requirements-cloud.txt

# 再拷代码：src 包 + 主程序（app.py 会把 src 加入搜索路径，另设 PYTHONPATH 供 CLI 用）
COPY src/ ./src/
COPY app.py ./

# 运行环境：云端重排 API + 无头 Streamlit + 关闭用量上报；密钥/账号由 --env-file 注入
ENV PYTHONPATH=/app/src \
    PYTHONIOENCODING=utf-8 \
    PYTHONUNBUFFERED=1 \
    TOOLBOOK_RERANK_BACKEND=api \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

EXPOSE 8501

# 无头启动；端口 8501 避开现有程序的 7860
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]