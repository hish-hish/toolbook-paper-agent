#!/usr/bin/env bash
# 云端部署脚本（在服务器上、项目根目录内执行）：装 Docker → 建精简镜像 → 内存上限运行 → 健康检查。
# 安全底线：绝不重启服务器、绝不碰现有程序（agent-lab，端口 7860）；容器内存硬上限，
#           OOM 只可能杀本容器，绝不波及现有程序。密钥/账号由 .env 经 --env-file 注入，不烤进镜像。
# 用法：bash scripts/deploy_server.sh
set -euo pipefail

# ---- 0. 定位项目根（脚本在 scripts/ 下，根为其上一级）----
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
echo "==> 项目根：$ROOT"

# ---- 1. 前置检查：.env 必须存在且含密钥；data/library.db 必须已传上来 ----
if [[ ! -f .env ]]; then
    echo "!! 缺少 .env。请先创建：cp .env.example .env 然后用 nano .env 填入密钥与账号密码。" >&2
    exit 1
fi
if ! grep -q '^SILICONFLOW_API_KEY=.\+' .env; then
    echo "!! .env 里 SILICONFLOW_API_KEY 为空，请填入硅基流动密钥后再跑。" >&2
    exit 1
fi
# 公网安全提醒：登录门两项凭据缺一即关闭＝任何人可访问，强烈建议都填
if ! grep -q '^TOOLBOOK_AUTH_USER=.\+' .env || ! grep -q '^TOOLBOOK_AUTH_PASS=.\+' .env; then
    echo "!! 警告：TOOLBOOK_AUTH_USER / TOOLBOOK_AUTH_PASS 未填全，登录门将关闭（公网＝裸奔）。" >&2
    echo "!! 建议在 .env 补全账号密码后再部署。5 秒后继续（Ctrl-C 可中止）…" >&2
    sleep 5
fi
if [[ ! -f data/library.db ]]; then
    echo "!! 缺少 data/library.db。请先从本地把资源库（library.db/chroma/books/papers）传上来。" >&2
    exit 1
fi

# ---- 2. 记录现有程序状态（部署前后对比，确保未被动到）----
echo "==> 部署前现有程序监听端口（应含 7860）："
ss -ltnp 2>/dev/null | grep -E ':7860|:8501' || echo "   （未发现 7860/8501 监听）"

# ---- 3. 安装 Docker（缺则装 Ubuntu 自带 docker.io，无需重启）----
if ! command -v docker >/dev/null 2>&1; then
    echo "==> 未检测到 Docker，安装 docker.io（不会重启服务器）…"
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io
    systemctl enable --now docker
else
    echo "==> Docker 已安装：$(docker --version)"
    systemctl start docker 2>/dev/null || true
fi

# ---- 4. 构建精简镜像（去 torch；建议本地构建后传镜像，服务器内存小见部署指南）----
echo "==> 构建镜像 toolbook:latest（首次较久，pip 装依赖；服务器内存小会用到 swap，属正常）…"
docker build -t toolbook:latest .

# ---- 5. 运行容器：内存硬上限 600M（RAM+swap 合计），端口 8501 避开 7860 ----
echo "==> 启动容器（--memory=600m --memory-swap=600m，OOM 只杀本容器）…"
docker rm -f toolbook >/dev/null 2>&1 || true
docker run -d --name toolbook \
    --restart always \
    -p 8501:8501 \
    --memory=600m --memory-swap=600m \
    --env-file .env \
    -v "$ROOT/data:/app/data" \
    toolbook:latest

# ---- 6. 健康检查：等 Streamlit 起来，探活 /_stcore/health ----
echo "==> 等待 Streamlit 启动并探活…"
ok=""
for i in $(seq 1 30); do
    sleep 2
    if curl -fsS http://localhost:8501/_stcore/health >/dev/null 2>&1; then
        ok="yes"; break
    fi
done
if [[ -z "$ok" ]]; then
    echo "!! 健康检查未通过。最近日志：" >&2
    docker logs --tail 40 toolbook >&2 || true
    exit 1
fi
echo "==> 健康检查通过（http://localhost:8501/_stcore/health = ok）"

# ---- 7. 部署后复核：现有程序 7860 仍在；本容器内存上限生效 ----
echo "==> 部署后监听端口（7860 应仍在，8501 为本应用）："
ss -ltnp 2>/dev/null | grep -E ':7860|:8501' || true
echo "==> 容器内存上限："
docker inspect toolbook --format 'Memory={{.HostConfig.Memory}} MemorySwap={{.HostConfig.MemorySwap}}'
echo "==> 完成。浏览器访问 http://<服务器公网IP>:8501（需在阿里云安全组放行 8501 入方向）。"
echo "==> 查看日志：docker logs -f toolbook    停止：docker stop toolbook    重启：docker restart toolbook"