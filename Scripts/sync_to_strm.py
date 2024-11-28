import os
import shutil
import datetime
import logging
import re
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 配置文件路径
LOG_FILE = "C:/Users/xxx/Desktop/sync.log"
SYNC_DIRECTORIES = [
    # "C:/Users/xxx/Desktop/media/Movies C:/Users/xxxx/Desktop/test/Movies /media/Movies",
    # "C:/Users/xxx/Desktop/media/TVShows C:/Users/xxx/Desktop/test/TVShows /media/TVShows",
    "C:/Users/xxx/Desktop/media/Anime C:/Users/xxx/Desktop/test/Anime /media/Anime"
]
MEDIA_FILE_TYPES = [
    "*.mp4", "*.mkv", "*.ts", "*.iso", "*.rmvb", "*.avi", "*.mov", "*.mpeg",
    "*.mpg", "*.wmv", "*.3gp", "*.asf", "*.m4v", "*.flv", "*.m2ts", "*.strm",
    "*.tp", "*.f4v"
]
OVERWRITE_EXISTING = True
ENABLE_CLEANUP = True
FULL_SYNC_ON_STARTUP = True
MAX_LOG_FILE_SIZE = 5 * 1024 * 1024
MAX_LOG_FILES = 5

# 是否启用直链模式 (True: 启用直链, False: 启用相对路径)
USE_DIRECT_LINK = True
# 是否启用相对路径模式 (True: 启用相对路径, False: 启用直链)
USE_RELATIVE_PATH = False

# 直链基础 URL (用户可以修改这个地址)
BASE_URL = "https://xxxx.xxxxx.com:1234/d/115网盘"


# 初始化日志
logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format='[%(asctime)s] %(message)s', datefmt='%Y/%m/%d %H:%M:%S')
console = logging.StreamHandler()
console.setLevel(logging.INFO)
formatter = logging.Formatter('%(message)s')
console.setFormatter(formatter)
logging.getLogger('').addHandler(console)

def log_message(message):
    logging.info(message)
    manage_log_files()

# 日志管理函数，用于处理日志文件大小和数量
def manage_log_files():
    # 检查日志文件大小，如果超过限制则重命名日志文件
    if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > MAX_LOG_FILE_SIZE:
        # 获取当前时间作为日志备份的后缀
        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        new_log_file = f"{LOG_FILE}.{timestamp}"
        os.rename(LOG_FILE, new_log_file)
        with open(LOG_FILE, 'w') as log_file:
            log_file.write("[{}] 日志文件大小超过限制，已创建新日志文件\n".format(datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S')))

    # 检查日志文件的数量，确保不超过最大保留数量
    log_dir = os.path.dirname(LOG_FILE)
    log_files = sorted([f for f in os.listdir(log_dir) if f.startswith(os.path.basename(LOG_FILE))], reverse=True)
    if len(log_files) > MAX_LOG_FILES:
        for old_log in log_files[MAX_LOG_FILES:]:
            os.remove(os.path.join(log_dir, old_log))

log_message("========== 同步和清理任务开始 {} ==========".format(datetime.datetime.now()))

### 功能: 文件系统监控器
class SyncHandler(FileSystemEventHandler):
    def __init__(self, source_dir, target_dir, media_prefix):
        super().__init__()
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.media_prefix = media_prefix

    def process(self, event):
        # 相对路径
        rel_path = os.path.relpath(event.src_path, self.source_dir).replace("\\", "/")
        ext = os.path.splitext(rel_path)[1].lower()
        is_media = any(re.fullmatch(pattern.replace("*", ".*"), rel_path) for pattern in MEDIA_FILE_TYPES)

        if event.event_type in ['created', 'modified']:
            # 处理文件创建和修改
            if is_media:
                self.create_strm_file(rel_path)
            else:
                self.sync_file(rel_path)
        elif event.event_type == 'deleted':
            # 处理文件删除
            if ENABLE_CLEANUP:
                self.delete_target_file(rel_path)
                if is_media:
                    self.delete_strm_file(rel_path)

    def create_strm_file(self, relative_path):
        # 如果启用了直链模式，使用 BASE_URL 拼接成完整的 URL
        if USE_DIRECT_LINK:
            # 生成完整的直链 URL
            strm_content = f"{BASE_URL}{self.media_prefix}/{relative_path}"
        else:
            # 否则，生成相对路径
            strm_content = f"{self.media_prefix}/{relative_path}"

        # 目标 .strm 文件的路径
        target_strm_file = os.path.join(self.target_dir, os.path.splitext(relative_path)[0] + ".strm").replace("\\",
                                                                                                               "/")

        # 检查是否需要跳过生成
        if os.path.exists(target_strm_file):
            if OVERWRITE_EXISTING:
                # 如果文件已存在且允许覆盖，删除并重新生成
                try:
                    os.remove(target_strm_file)
                    log_message(f"覆盖: 重新生成 .strm 文件: {target_strm_file}")
                except Exception as e:
                    log_message(f"错误: 无法删除已存在的 .strm 文件: {target_strm_file}, {e}")
            else:
                log_message(f"跳过: .strm 文件已存在: {target_strm_file}")
                return

        # 生成 .strm 文件内容
        try:
            os.makedirs(os.path.dirname(target_strm_file), exist_ok=True)
            with open(target_strm_file, "w") as f:
                f.write(strm_content)
            # 记录生成成功日志
            log_message(f"成功生成 .strm 文件: {target_strm_file}")
        except Exception as e:
            log_message(f"错误: 无法生成 .strm 文件: {target_strm_file}, {e}")

    def sync_file(self, relative_path):
        source_file_path = os.path.join(self.source_dir, relative_path).replace("\\", "/")
        target_file_path = os.path.join(self.target_dir, relative_path).replace("\\", "/")

        # 修正多余的文件夹嵌套问题
        target_parent_dir = os.path.dirname(target_file_path)

        # 创建目标文件夹结构
        os.makedirs(target_parent_dir, exist_ok=True)

        # 检查目标文件是否已存在
        if not OVERWRITE_EXISTING and os.path.exists(target_file_path):
            log_message(f"跳过: 非媒体文件已存在: {target_file_path}")
            return

        # 同步文件
        try:
            shutil.copy2(source_file_path, target_file_path)
            log_message(f"成功同步非媒体文件: {source_file_path} -> {target_file_path}")
        except Exception as e:
            log_message(f"错误: 无法同步非媒体文件: {source_file_path} -> {target_file_path}, {e}")

    def delete_target_file(self, relative_path):
        target_file_path = os.path.join(self.target_dir, relative_path).replace("\\", "/")
        if os.path.exists(target_file_path):
            try:
                if os.path.isdir(target_file_path):
                    shutil.rmtree(target_file_path)
                else:
                    os.remove(target_file_path)
                log_message(f"成功删除目标文件: {target_file_path}")
            except Exception as e:
                log_message(f"错误: 无法删除目标文件: {target_file_path}, {e}")

    def delete_strm_file(self, relative_path):
        target_strm_file = os.path.join(self.target_dir, os.path.splitext(relative_path)[0] + ".strm").replace("\\", "/")
        if os.path.exists(target_strm_file):
            try:
                os.remove(target_strm_file)
                log_message(f"成功删除关联的 .strm 文件: {target_strm_file}")
            except Exception as e:
                log_message(f"错误: 无法删除关联的 .strm 文件: {target_strm_file}, {e}")

    def on_created(self, event):
        if not event.is_directory:
            self.process(event)

    def on_modified(self, event):
        if not event.is_directory:
            self.process(event)

    def on_deleted(self, event):
        if not event.is_directory:
            self.process(event)

# 启动文件系统监控器
observers = []
for mapping in SYNC_DIRECTORIES:
    parts = mapping.split(" ", 2)
    if len(parts) != 3:
        log_message(f"错误: 路径映射格式不正确: {mapping}")
        continue
    source_dir, target_dir, media_prefix = parts
    log_message(f"开始监控目录: {source_dir} -> {target_dir} (media 前缀: {media_prefix})")

    if FULL_SYNC_ON_STARTUP:
        log_message(f"执行初始全量同步: {source_dir} -> {target_dir}")
        event_handler = SyncHandler(source_dir, target_dir, media_prefix)
        for root, _, files in os.walk(source_dir):
            for file in files:
                relative_path = os.path.relpath(os.path.join(root, file), source_dir).replace("\\", "/")
                if any(re.fullmatch(pattern.replace("*", ".*"), relative_path) for pattern in MEDIA_FILE_TYPES):
                    event_handler.create_strm_file(relative_path)
                else:
                    event_handler.sync_file(relative_path)
        FULL_SYNC_ON_STARTUP = False

    event_handler = SyncHandler(source_dir, target_dir, media_prefix)
    observer = Observer()
    observer.schedule(event_handler, path=source_dir, recursive=True)
    observer.start()
    observers.append(observer)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    for observer in observers:
        observer.stop()
    for observer in observers:
        observer.join()

log_message("========== 实时监控同步和清理任务完成 {} ==========".format(datetime.datetime.now()))