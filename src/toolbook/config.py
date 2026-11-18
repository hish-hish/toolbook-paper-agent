"""全局配置：数据目录、数据库路径、硅基流动模型与密钥读取、重排设备。"""
import os
from pathlib import Path

# 项目根目录与数据目录（data/ 已被 gitignore，不入库）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB = DATA_DIR / "library.db"
CHROMA_DIR = DATA_DIR / "chroma"

# 硅基流动 OpenAI 兼容接口与模型（D2/D8/D10 定案）
SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
EMBED_MODEL = "BAAI/bge-m3"
CHAT_MODEL = "deepseek-ai/DeepSeek-V3.2"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
# 重排默认 CPU（D10 方案B），避免与 MinerU 争显存；可设 cuda
RERANK_DEVICE = os.environ.get("TOOLBOOK_RERANK_DEVICE", "cpu")


def load_api_key() -> str:
    """读取硅基流动密钥：优先环境变量，其次项目根 .env 文件；都没有返回空串。"""
    key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
    if key:
        return key
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("SILICONFLOW_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""