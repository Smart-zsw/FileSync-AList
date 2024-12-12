# 使用官方 Python 镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 复制应用代码
COPY sync_to_strm.py .

# 安装必要的依赖项
RUN pip install watchdog

# 创建日志目录
RUN mkdir -p /config/logs

# 设置默认环境变量
ENV LOG_FILE="/config/logs/sync.log"
ENV SYNC_DIRECTORIES=""
ENV MEDIA_FILE_TYPES="*.mp4;*.mkv;*.ts;*.iso;*.rmvb;*.avi;*.mov;*.mpeg;*.mpg;*.wmv;*.3gp;*.asf;*.m4v;*.flv;*.m2ts;*.strm;*.tp;*.f4v"
ENV OVERWRITE_EXISTING="False"
ENV ENABLE_CLEANUP="False"
ENV FULL_SYNC_ON_STARTUP="True"
ENV MAX_LOG_FILES="5"
ENV USE_DIRECT_LINK="False"
ENV BASE_URL=""

# 运行脚本
CMD ["python", "sync_to_strm.py"]

