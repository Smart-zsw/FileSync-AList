#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
脚本名称：文件夹同步与清理脚本
脚本功能：
    该脚本用于实时监控多个源目录的文件变化，并同步文件到目标目录。支持媒体文件类型（如视频、音频）的同步，并生成 `.strm` 文件以便于流媒体播放。
    此脚本支持文件的创建、修改、删除操作，并可清理目标目录中的过期文件。

    主要功能：
    - 同步指定目录的文件到目标目录。
    - 对媒体文件类型（如 .mp4、.mkv 等）创建 `.strm` 文件。
    - 支持覆盖已存在的文件。
    - 支持启用或禁用清理功能，删除目标目录中不再需要的文件。
    - 全量同步模式：每次脚本启动时，执行源目录与目标目录的完整同步。
    - 自动日志管理：自动分割日志文件，确保不会超过最大大小。

使用方法：
    1. 配置环境变量，设置源目录和目标目录的映射关系、媒体文件类型等。
        - `SYNC_DIRECTORIES`：源目录、目标目录以及 `.strm` 路径前缀的映射。
        - `MEDIA_FILE_TYPES`：指定要同步的媒体文件类型，使用分号分隔多个类型。
        - `OVERWRITE_EXISTING`：配置是否覆盖已存在的文件。
        - `ENABLE_CLEANUP`：启用或禁用文件清理功能。
        - `FULL_SYNC_ON_STARTUP`：是否在脚本启动时执行全量同步。
        - `LOG_FILE`：日志文件路径。
        - `MAX_LOG_FILES`：最多保留的日志文件数量。
    2. 运行脚本，脚本会根据配置开始监控文件夹，并自动同步和清理文件。

参数说明：
    - `SYNC_DIRECTORIES`：一个以分号分隔的字符串列表，定义多个源目录与目标目录的映射。每个映射由源目录、目标目录和媒体路径前缀组成，格式为：
        "源目录 目标目录 /strm路径前缀"
        示例：
            "C:/Users/Username/Desktop/media/Movies C:/Users/Username/Desktop/test/Movies /media/Movies"
            这表示源目录 `C:/Users/Username/Desktop/media/Movies` 中的文件会同步到目标目录 `C:/Users/Username/Desktop/test/Movies`，并为每个媒体文件生成一个 `.strm` 文件，路径前缀为 `/media/Movies`。
    - `MEDIA_FILE_TYPES`：指定需要同步的文件类型。使用分号分隔多个文件类型，例如：
        "*.mp4;*.mkv;*.avi" 表示同步 `.mp4`、`.mkv` 和 `.avi` 格式的文件。
    - `OVERWRITE_EXISTING`：布尔值（`True` 或 `False`），决定是否覆盖目标目录中已存在的文件。如果为 `True`，则会覆盖同名文件；如果为 `False`，则跳过已存在的文件。
    - `ENABLE_CLEANUP`：布尔值（`True` 或 `False`），启用或禁用清理功能。当为 `True` 时，如果文件在源目录中被删除，目标目录中对应的文件也会被删除。
    - `FULL_SYNC_ON_STARTUP`：布尔值（`True` 或 `False`），决定是否在脚本启动时执行全量同步。若为 `True`，则会遍历源目录中的所有文件并同步到目标目录，默认值为 `True`。
    - `LOG_FILE`：指定日志文件的路径，默认日志路径为 `/config/logs/sync.log`。如果路径中不存在相应的文件夹，脚本会自动创建。
    - `MAX_LOG_FILES`：指定最多保留的日志文件数量。若超过该数量，脚本会删除最旧的日志文件。默认值为 5。
    - `MAX_LOG_FILE_SIZE`：日志文件的最大大小（字节）。默认值为 5MB（5 * 1024 * 1024 字节）。当日志文件超过该大小时，脚本会创建新的日志文件并备份旧的日志文件。

依赖库：
    - `os`：用于处理文件和目录操作。
    - `shutil`：用于执行文件复制和删除操作。
    - `datetime`：用于获取当前时间并生成日志文件名。
    - `logging`：用于记录脚本的运行日志。
    - `re`：用于正则表达式匹配文件类型。
    - `time`：用于设置脚本的运行间隔。
    - `watchdog`：用于监控文件系统变化（文件创建、修改、删除）。

注意事项：
    - 确保在运行脚本前，已备份目标目录中的重要文件，以避免覆盖或丢失数据。
    - 脚本将同步所有符合 `MEDIA_FILE_TYPES` 中配置的文件类型，若目标目录中已有同名文件并且 `OVERWRITE_EXISTING` 设置为 `True`，这些文件会被覆盖。
    - 启用清理功能时，脚本会删除目标目录中与源目录中已删除文件对应的文件，请确保清理操作不会删除不需要的文件。
    - 启用全量同步时，脚本会遍历源目录中的所有文件并执行同步操作，这可能会导致初次运行时耗时较长。

版权信息：
    Copyright (c) 2024 作者姓名。保留所有权利。
"""

import os
import shutil
import datetime
import logging
import re
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 日志文件路径
LOG_FILE = os.getenv('LOG_FILE', '/config/logs/sync.log')

# 创建日志文件夹（如果不存在）
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# 配置路径映射
SYNC_DIRECTORIES = os.getenv('SYNC_DIRECTORIES', '').split(';')  # 多个路径映射用分号分隔

# 媒体文件类型配置（共用）
MEDIA_FILE_TYPES = os.getenv('MEDIA_FILE_TYPES', "*.mp4;*.mkv;*.ts;*.iso;*.rmvb;*.avi;*.mov;*.mpeg;*.mpg;*.wmv;*.3gp;*.asf;*.m4v;*.flv;*.m2ts;*.strm;*.tp;*.f4v").split(';')

# 是否覆盖已存在的文件
OVERWRITE_EXISTING = os.getenv('OVERWRITE_EXISTING', 'False').lower() == 'true'

# 是否启用清理功能
ENABLE_CLEANUP = os.getenv('ENABLE_CLEANUP', 'False').lower() == 'true'

# 是否执行全量遍历同步
FULL_SYNC_ON_STARTUP = os.getenv('FULL_SYNC_ON_STARTUP', 'True').lower() == 'true'

# 最大日志文件大小（字节），超过该大小时自动清理日志（5MB）
MAX_LOG_FILE_SIZE = 5 * 1024 * 1024

# 最多保留日志文件数量
MAX_LOG_FILES = int(os.getenv('MAX_LOG_FILES', 5))


# # 日志文件路径
# LOG_FILE = "C:/Users/Username/Desktop/sync.log"
# # 配置路径映射
# # 格式: "源目录 目标目录 /strm路径前缀"
# SYNC_DIRECTORIES = [
#     "C:/Users/Username/Desktop/media/Movies C:/Users/Username/Desktop/test/Movies /media/Movies",
#     "C:/Users/Username/Desktop/media/TVShows C:/Users/Username/Desktop/test/TVShows /media/TVShows",
#     "C:/Users/Username/Desktop/media/Anime C:/Users/Username/Desktop/test/Anime /media/Anime"
# ]
# # 媒体文件类型配置（共用）
# MEDIA_FILE_TYPES = [
#     "*.mp4", "*.mkv", "*.ts", "*.iso", "*.rmvb", "*.avi", "*.mov", "*.mpeg",
#     "*.mpg", "*.wmv", "*.3gp", "*.asf", "*.m4v", "*.flv", "*.m2ts", "*.strm",
#     "*.tp", "*.f4v"
# ]
# # 是否覆盖已存在的文件
# OVERWRITE_EXISTING = True
# # 是否启用清理功能
# ENABLE_CLEANUP = True
# # 是否执行全量遍历同步
# FULL_SYNC_ON_STARTUP = True
# # 最大日志文件大小（字节），超过该大小时自动清理日志（5MB）
# MAX_LOG_FILE_SIZE = 5 * 1024 * 1024
# # 最多保留日志文件数量
# MAX_LOG_FILES = 5

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
        strm_relative_path = f"{self.media_prefix}/{relative_path}"
        target_strm_file = os.path.join(self.target_dir, os.path.splitext(relative_path)[0] + ".strm").replace("\\", "/")

        # 检查是否需要跳过生成
        if os.path.exists(target_strm_file):
            if OVERWRITE_EXISTING:
                # 仅记录覆盖日志，不重复生成日志
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
                f.write(strm_relative_path)
            # 记录生成成功日志
            if not os.path.exists(target_strm_file):
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
                event_handler.create_strm_file(relative_path) if any(re.fullmatch(pattern.replace("*", ".*"), relative_path) for pattern in MEDIA_FILE_TYPES) else event_handler.sync_file(relative_path)
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
