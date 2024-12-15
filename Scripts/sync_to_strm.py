import os
import shutil
import datetime
import logging
import re
import time
from logging.handlers import RotatingFileHandler
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class SyncToStrm:
    def __init__(self, config):
        self.log_file = config.get('log_file', '/config/logs/sync_to_strm.log')
        self.sync_directories = config.get('sync_directories', [])
        self.media_file_types = config.get('media_file_types', [
            "*.mp4", "*.mkv", "*.ts", "*.iso", "*.rmvb", "*.avi", "*.mov", "*.mpeg",
            "*.mpg", "*.wmv", "*.3gp", "*.asf", "*.m4v", "*.flv", "*.m2ts",
            "*.strm", "*.tp", "*.f4v"
        ])
        self.overwrite_existing = config.get('overwrite_existing', False)
        self.enable_cleanup = config.get('enable_cleanup', False)
        self.full_sync_on_startup = config.get('full_sync_on_startup', True)
        self.use_direct_link = config.get('use_direct_link', False)
        self.base_url = config.get('base_url', '')

        # 日志管理
        self.max_log_file_size = 10 * 1024 * 1024
        self.max_log_files = 5

        # 初始化日志
        self.setup_logging()

    def setup_logging(self):
        """配置日志系统"""
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        logging.basicConfig(level=logging.INFO,
                            format='[%(asctime)s] [%(levelname)s] %(message)s',
                            datefmt='%Y/%m/%d %H:%M:%S',
                            handlers=[
                                RotatingFileHandler(self.log_file, maxBytes=self.max_log_file_size,
                                                    backupCount=self.max_log_files, encoding='utf-8'),
                                logging.StreamHandler()
                            ])
        logging.info("SyncToStrm 日志系统已配置。")

    def log_message(self, message):
        logging.info("[STRM] " + message)
        self.manage_log_files()

    def manage_log_files(self):
        """管理日志文件大小和数量"""
        if os.path.exists(self.log_file) and os.path.getsize(self.log_file) > self.max_log_file_size:
            timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
            os.rename(self.log_file, f"{self.log_file}.{timestamp}")
            with open(self.log_file, 'w', encoding='utf-8') as log_file:
                log_file.write(
                    f"[{datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S')}] 日志文件大小超过限制，已创建新日志文件\n")

        log_dir = os.path.dirname(self.log_file)
        log_files = sorted([f for f in os.listdir(log_dir) if f.startswith(os.path.basename(self.log_file))],
                           reverse=True)
        if len(log_files) > self.max_log_files:
            for old_log in log_files[self.max_log_files:]:
                os.remove(os.path.join(log_dir, old_log))

    def is_media_file(self, relative_path: str) -> bool:
        """检查文件是否是媒体文件"""
        return any(re.fullmatch(pattern.replace("*", ".*"), relative_path) for pattern in self.media_file_types)

    class SyncHandler(FileSystemEventHandler):
        def __init__(self, source_dir, target_dir, media_prefix, parent):
            super().__init__()
            self.source_dir = source_dir
            self.target_dir = target_dir
            self.media_prefix = media_prefix
            self.parent = parent

        def get_relative_path(self, full_path):
            return os.path.relpath(full_path, self.source_dir).replace("\\", "/")

        def is_media_file(self, relative_path):
            """检查文件是否是媒体文件"""
            return any(re.fullmatch(pattern.replace("*", ".*"), relative_path) for pattern in self.parent.media_file_types)

        def is_file_stable(self, file_path, check_interval=2, max_checks=5):
            """
            检测文件是否稳定（大小保持不变）。
            """
            try:
                previous_size = -1
                for _ in range(max_checks):
                    if not os.path.exists(file_path):
                        return False  # 文件可能被删除
                    current_size = os.path.getsize(file_path)
                    if current_size == previous_size:
                        return True  # 文件大小稳定
                    previous_size = current_size
                    time.sleep(check_interval)  # 等待一段时间后再次检查
                return False  # 超过检查次数，文件仍不稳定
            except Exception as e:
                logging.error(f"检测文件稳定性时出错: {file_path}, 错误: {e}")
                return False

        def on_created(self, event):
            relative_path = self.get_relative_path(event.src_path)

            if event.src_path.lower().endswith('.mp'):
                logging.debug(f"忽略 .mp 文件创建事件: {event.src_path}")
                return

            if event.is_directory:
                self.handle_directory_event(event, relative_path)
            else:
                self.handle_file_event(event, relative_path)

        def on_modified(self, event):
            """去除文件修改的事件处理逻辑"""
            pass

        def on_deleted(self, event):
            relative_path = self.get_relative_path(event.src_path)
            # 删除操作一般不需要去抖动，可以立即处理
            if event.is_directory:
                self.handle_directory_event(event, relative_path)
            else:
                self.handle_file_event(event, relative_path)

        def on_moved(self, event):
            relative_path = self.get_relative_path(event.src_path)
            self.handle_file_event(event, relative_path)

        def handle_file_event(self, event, relative_path):
            """处理文件的创建、修改或删除"""
            # 检查是否是被重命名的文件
            if event.event_type == 'moved':
                # 获取源和目标的相对路径
                dest_relative_path = self.get_relative_path(event.dest_path)

                # 如果源文件是 .mp 文件且目标文件是有效的媒体文件类型，生成 .strm 文件
                if event.src_path.lower().endswith('.mp') and self.is_media_file(dest_relative_path):
                    logging.debug(f"文件重命名: {event.src_path} -> {event.dest_path}")
                    # 生成 .strm 文件
                    self.parent.create_strm_file(dest_relative_path, self.target_dir, self.media_prefix)
                    return  # 处理完后直接返回，跳过其他同步

                if event.src_path.endswith('.mp'):
                    # 重新同步文件
                    self.parent.sync_file(self.get_relative_path(event.dest_path), self.source_dir, self.target_dir)
                return

            source_file_path = os.path.join(self.source_dir, relative_path).replace("\\", "/")

            if event.event_type == 'created':  # 只处理创建事件
                if self.is_media_file(relative_path):
                    # 检测文件是否稳定
                    if self.is_file_stable(source_file_path):
                        self.parent.create_strm_file(relative_path, self.target_dir, self.media_prefix)
                    else:
                        self.parent.log_message(f"跳过: 文件不稳定或被删除: {source_file_path}")
                else:
                    # 检测文件是否稳定
                    if self.is_file_stable(source_file_path):
                        self.parent.sync_file(relative_path, self.source_dir, self.target_dir)
                    else:
                        self.parent.log_message(f"跳过: 文件不稳定或被删除: {source_file_path}")
            elif event.event_type == 'deleted' and self.parent.enable_cleanup:
                self.parent.delete_target_file(relative_path, self.target_dir)

        def handle_directory_event(self, event, relative_path):
            """处理目录的创建或删除"""
            target_dir_path = os.path.join(self.target_dir, relative_path).replace("\\", "/")
            if event.event_type == 'deleted' and self.parent.enable_cleanup:
                if os.path.exists(target_dir_path):
                    try:
                        shutil.rmtree(target_dir_path)
                        self.parent.log_message(f"成功删除目标目录: {target_dir_path}")
                    except Exception as e:
                        self.parent.log_message(f"错误: 无法删除目标目录: {target_dir_path}, {e}")
            elif event.event_type == 'created':
                if not os.path.exists(target_dir_path):
                    try:
                        os.makedirs(target_dir_path, exist_ok=True)
                        self.parent.log_message(f"成功创建目标目录: {target_dir_path}")
                    except Exception as e:
                        self.parent.log_message(f"错误: 无法创建目标目录: {target_dir_path}, {e}")

    def start(self):
        self.observers = []
        for mapping in self.sync_directories:
            source_dir = mapping.get('source_dir')
            target_dir = mapping.get('target_dir')
            media_prefix = mapping.get('media_prefix')

            if not source_dir or not target_dir or not media_prefix:
                self.log_message(f"配置错误: SYNC_DIRECTORIES 中的映射 '{mapping}' 缺少必要字段。")
                continue

            self.log_message(f"开始监控目录: {source_dir} -> {target_dir} (media 前缀: {media_prefix})")

            event_handler = self.SyncHandler(source_dir, target_dir, media_prefix, self)

            # 执行初始全量同步
            if self.full_sync_on_startup:
                self.log_message(f"执行初始全量同步: {source_dir} -> {target_dir}")
                for root, dirs, files in os.walk(source_dir):
                    relative_root = os.path.relpath(root, source_dir).replace("\\", "/")
                    if relative_root == ".":
                        relative_root = ""
                    target_root = os.path.join(target_dir, relative_root).replace("\\", "/")
                    if not os.path.exists(target_root):
                        try:
                            os.makedirs(target_root, exist_ok=True)
                            self.log_message(f"创建目录: {target_root}")
                        except Exception as e:
                            self.log_message(f"错误: 无法创建目录: {target_root}, {e}")

                    for file in files:
                        relative_path = os.path.join(relative_root, file).replace("\\", "/")
                        # 使用is_media_file判断文件类型
                        if self.is_media_file(relative_path):
                            self.create_strm_file(relative_path, target_dir, media_prefix)
                        else:
                            self.sync_file(relative_path, source_dir, target_dir)

            observer = Observer()
            observer.schedule(event_handler, path=source_dir, recursive=True)
            observer.start()
            self.observers.append(observer)

        self.full_sync_on_startup = False
        self.log_message("所有监控器已启动。")

    def stop(self):
        """停止所有监控器"""
        for observer in self.observers:
            observer.stop()
        for observer in self.observers:
            observer.join()
        self.log_message("所有监控器已停止。")

    def create_strm_file(self, relative_path, target_dir, media_prefix):
        target_strm_file = os.path.join(target_dir, os.path.splitext(relative_path)[0] + ".strm").replace("\\", "/")
        if os.path.exists(target_strm_file) and not self.overwrite_existing:
            self.log_message(f"跳过: .strm 文件已存在: {target_strm_file}")
            return

        strm_content = f"{self.base_url}{media_prefix}/{relative_path}" if self.use_direct_link else f"{media_prefix}/{relative_path}"

        try:
            os.makedirs(os.path.dirname(target_strm_file), exist_ok=True)
            with open(target_strm_file, "w", encoding='utf-8') as f:
                f.write(strm_content)
            self.log_message(f"成功生成 .strm 文件: {target_strm_file}")
        except Exception as e:
            self.log_message(f"错误: 无法生成 .strm 文件: {target_strm_file}, {e}")

    def sync_file(self, relative_path, source_dir, target_dir):
        source_file_path = os.path.join(source_dir, relative_path).replace("\\", "/")
        target_file_path = os.path.join(target_dir, relative_path).replace("\\", "/")

        os.makedirs(os.path.dirname(target_file_path), exist_ok=True)

        if not self.overwrite_existing and os.path.exists(target_file_path):
            self.log_message(f"跳过: 非媒体文件已存在: {target_file_path}")
            return

        try:
            shutil.copy2(source_file_path, target_file_path)
            self.log_message(f"成功同步非媒体文件: {source_file_path} -> {target_file_path}")
        except Exception as e:
            self.log_message(f"错误: 无法同步非媒体文件: {source_file_path} -> {target_file_path}, {e}")

    def delete_target_file(self, relative_path, target_dir):
        """删除目标文件及其关联的 .strm 文件"""
        target_file_path = os.path.join(target_dir, relative_path).replace("\\", "/")

        # 如果目标是一个文件，首先删除它
        if os.path.exists(target_file_path):
            try:
                # 如果是文件夹，使用 rmtree 删除文件夹
                if os.path.isdir(target_file_path):
                    shutil.rmtree(target_file_path)
                    self.log_message(f"成功删除目标目录: {target_file_path}")
                else:
                    os.remove(target_file_path)
                    self.log_message(f"成功删除目标文件: {target_file_path}")
            except Exception as e:
                self.log_message(f"错误: 无法删除目标文件/目录: {target_file_path}, {e}")

        # 如果是媒体文件且存在相应的 .strm 文件，删除对应的 .strm 文件
        if self.is_media_file(relative_path):
            strm_file_path = os.path.splitext(target_file_path)[0] + ".strm"
            if os.path.exists(strm_file_path):
                try:
                    os.remove(strm_file_path)
                    self.log_message(f"成功删除关联的 .strm 文件: {strm_file_path}")
                except Exception as e:
                    self.log_message(f"错误: 无法删除 .strm 文件: {strm_file_path}, {e}")
