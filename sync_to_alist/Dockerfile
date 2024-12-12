# 使用官方 Python 镜像作为基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 复制需求文件并安装依赖
COPY requirements.txt .

RUN pip install -r requirements.txt

# 复制应用代码
COPY sync_to_alist.py .

# 设置环境变量的默认值
ENV ALIST_ENDPOINT=""
ENV ALIST_USERNAME=""
ENV ALIST_SOURCE_BASE_DIRECTORY=""
ENV ALIST_REMOTE_BASE_DIRECTORY=""
ENV LOCAL_DIRECTORY=""
ENV LOG_FILE="/config/logs/sync_to_alist.log"

# 确保日志和秘密目录存在
RUN mkdir -p /config/logs

# 定义容器启动时执行的命令
CMD ["python", "sync_to_alist.py"]


