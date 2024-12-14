# 使用官方的 Python 3.11-slim 作为基础镜像
FROM python:3.11-slim

# 设置环境变量，防止 Python 生成 .pyc 文件和缓冲输出，同时指向配置文件路径
ENV CONFIG_PATH=/config/config.yaml

# 设置工作目录
WORKDIR /app

# 复制并安装 Python 依赖
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY config.yaml /default_config/config.yaml
COPY Scripts/ Scripts/
COPY main.py ./
COPY entrypoint.sh /entrypoint.sh

# 设置入口脚本的执行权限并创建必要的目录
RUN chmod +x /entrypoint.sh && \
    mkdir -p /config/logs

# 设置入口脚本
ENTRYPOINT ["/entrypoint.sh"]

# 设置默认命令
CMD ["python", "main.py"]
