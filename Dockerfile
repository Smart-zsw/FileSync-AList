# 使用官方 Python 镜像作为基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
#RUN apt-get update && apt-get install -y \
#    gcc \
#    && rm -rf /var/lib/apt/lists/*

# 复制需求文件并安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY filesync_alist.py .

# 复制配置文件到工作目录的 /config 目录
COPY config.yaml /config/config.yaml

# 设置环境变量的默认值
ENV TZ="Asia/Shanghai"

# 确保日志和秘密目录存在
RUN mkdir -p /config/logs

# 定义容器启动时执行的命令
CMD ["python", "filesync_alist.py"]
