import asyncio
import os
import logging
from logging.handlers import RotatingFileHandler
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from alist import AList, AListUser
import yaml
import shutil
import re
import threading
from collections import defaultdict

# 读取配置文件
def load_config(config_path):
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

config = load_config('/config/config.yaml')

# 读取日志路径从环境变量，默认值为 /config/logs/sync.log
LOG_FILE = os.getenv('LOG_FILE', '/config/logs/sync.log')

# 创建日志目录
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",  # 添加日志标识符
    handlers=[
        RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=10, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('SyncManager')
logger.info("日志配置完成。")

# 定义 AListSyncHandler 类
class AListSyncHandler(FileSystemEventHandler):
    def __init__(
            self,
            alist: AList,
            remote_base_path: str,
            local_base_path: str,
            loop: asyncio.AbstractEventLoop,
            source_base_directory: str,
            debounce_delay: float = 1.0,
            file_stable_time: float = 5.0,  # 新增：文件稳定时间（秒）
            ignore_paths: set = None  # 新增：可选的忽略路径集合
    ):
        super().__init__()
        self.logger = logging.getLogger('AListSync')
        self.alist = alist
        self.remote_base_path = remote_base_path.rstrip('/')  # 去除末尾的斜杠
        self.local_base_path = local_base_path.rstrip('/')
        self.loop = loop  # 主线程的事件循环
        self.source_base_directory = source_base_directory.rstrip('/')
        self.debounce_delay = debounce_delay  # 防抖延迟时间（秒）
        self.file_stable_time = file_stable_time  # 文件稳定时间（秒）
        self._tasks = {}  # 跟踪文件路径到任务的映射
        self.existing_paths = set()  # 存储启动时已有的文件和文件夹的相对路径

        if ignore_paths is not None:
            self.existing_paths = set(ignore_paths)
            self.logger.info(f"使用外部提供的忽略路径，共计 {len(self.existing_paths)} 个路径。")
        else:
            # 初始化 existing_paths，遍历本地目录并记录所有现有文件和文件夹
            for root, dirs, files in os.walk(self.local_base_path):
                rel_root = os.path.relpath(root, self.local_base_path).replace("\\", "/")
                if rel_root == ".":
                    rel_root = ""
                for d in dirs:
                    path = os.path.join(rel_root, d).replace("\\", "/")
                    self.existing_paths.add(path)
                for f in files:
                    path = os.path.join(rel_root, f).replace("\\", "/")
                    self.existing_paths.add(path)
            self.logger.info(f"已记录 {len(self.existing_paths)} 个现有路径，不会监控这些路径。")

    def get_relative_path(self, src_path):
        """
        计算相对于本地监控基路径的相对路径
        """
        return os.path.relpath(src_path, self.local_base_path).replace("\\", "/")  # 确保使用正斜杠

    def get_remote_source_path(self, relative_path):
        """
        根据相对路径生成 AList 中的源路径
        """
        return f"{self.source_base_directory}/{relative_path}"

    def get_remote_destination_path(self, relative_path):
        """
        根据相对路径生成 AList 中的目的路径
        """
        return f"{self.remote_base_path}/{relative_path}"

    def schedule_task(self, coro, file_path):
        """
        调度一个防抖任务，确保在指定延迟后执行
        """
        if file_path in self._tasks:
            task = self._tasks[file_path]
            task.cancel()  # 取消之前的任务
            self.logger.debug(f"取消之前的任务: {file_path}")
        # 使用线程安全的方法调度任务
        future = asyncio.run_coroutine_threadsafe(self.debounce(coro, file_path), self.loop)
        self._tasks[file_path] = future
        self.logger.debug(f"调度新任务: {file_path}")

    async def debounce(self, coro, file_path):
        """
        等待防抖延迟后执行协程
        """
        try:
            await asyncio.sleep(self.debounce_delay)
            await coro
        except asyncio.CancelledError:
            self.logger.debug(f"任务被取消: {file_path}")
            pass
        finally:
            self._tasks.pop(file_path, None)
            self.logger.debug(f"任务完成或取消，移除任务: {file_path}")

    async def is_file_complete(self, file_path):
        """
        检查文件在指定时间内是否保持大小不变，以确定文件是否完整
        """
        self.logger.debug(f"开始检查文件完整性: {file_path}")
        previous_size = -1
        stable_time = 0.0
        check_interval = 1.0  # 检查间隔（秒）

        while True:
            if not os.path.exists(file_path):
                self.logger.warning(f"文件不存在，无法检查完整性: {file_path}")
                return False
            current_size = os.path.getsize(file_path)
            if current_size == previous_size:
                stable_time += check_interval
                self.logger.debug(f"文件大小未变化，稳定时间: {stable_time:.1f}/{self.file_stable_time} 秒")
                if stable_time >= self.file_stable_time:
                    self.logger.info(f"文件已完成写入: {file_path}")
                    return True
            else:
                stable_time = 0.0
                self.logger.debug(f"文件大小变化，从 {previous_size} 到 {current_size}")
                previous_size = current_size
            await asyncio.sleep(check_interval)

    async def handle_created_or_modified(self, event):
        """
        处理文件或文件夹的创建和修改事件
        """
        relative_path = self.get_relative_path(event.src_path)

        # 跳过相对路径为 '.' 或空字符串的事件
        if relative_path in ('', '.'):
            self.logger.warning(f"跳过相对路径为 '.' 或空字符串的事件: {event.src_path}")
            return

        # 检查是否是新增文件或文件夹
        if relative_path in self.existing_paths:
            self.logger.debug(f"路径已存在，不处理: {relative_path}")
            return

        # 标记为已存在
        self.existing_paths.add(relative_path)
        self.logger.info(f"新增路径: {relative_path}")

        remote_source_path = self.get_remote_source_path(relative_path)  # AList 中的源路径
        remote_destination_path = self.get_remote_destination_path(relative_path)  # AList 中的目的路径

        if event.is_directory:
            # 对于文件夹，只创建目标文件夹
            success = await self.alist.mkdir(remote_destination_path)
            if success:
                self.logger.info(f"文件夹创建成功: {remote_destination_path}")
            else:
                self.logger.error(f"文件夹创建失败或已存在: {remote_destination_path}")
        else:
            # 文件：先检查文件是否完整，然后复制
            file_path = event.src_path
            if await self.is_file_complete(file_path):
                await self.copy_file(remote_source_path, remote_destination_path)
            else:
                self.logger.error(f"文件未完成写入，无法复制: {file_path}")

    async def copy_file(self, remote_source_path, remote_destination_path):
        """
        复制文件到 AList
        在复制之前，先刷新源目录，确保 AList 检测到新增的文件
        """
        source_dir = os.path.dirname(remote_source_path)
        try:
            # 调用 list_dir 并强制刷新源目录
            async for _ in self.alist.list_dir(source_dir, refresh=True):
                pass  # 仅需要执行刷新，无需处理返回的生成器
            self.logger.info(f"刷新 AList 中的源路径目录: {source_dir}")
        except Exception as e:
            self.logger.error(f"刷新 AList 中的源路径目录失败: {source_dir}, 错误: {e}")
            return  # 如果刷新失败，则不进行复制操作

        # 执行复制操作
        try:
            # 根据 API 文档，copy 方法的第二个参数应该是目标目录，而不是完整的目标路径
            destination_dir = os.path.dirname(remote_destination_path)
            success = await self.alist.copy(remote_source_path, destination_dir)
            if success:
                self.logger.info(f"文件复制成功: {remote_source_path} -> {remote_destination_path}")
            else:
                self.logger.error(f"文件复制失败: {remote_source_path} -> {remote_destination_path}")
        except Exception as e:
            self.logger.error(f"执行复制操作时出错: {remote_source_path} -> {remote_destination_path}, 错误: {e}")

    async def handle_moved(self, event):
        """
        处理文件或文件夹的移动事件
        """
        relative_src_path = self.get_relative_path(event.src_path)
        relative_dst_path = self.get_relative_path(event.dest_path)

        # 跳过相对路径为 '.' 或空字符串的事件
        if relative_src_path in ('', '.') or relative_dst_path in ('', '.'):
            self.logger.warning(f"跳过相对路径为 '.' 或空字符串的移动事件: {event.src_path} -> {event.dest_path}")
            return

        src_in_existing = relative_src_path in self.existing_paths
        dst_in_existing = relative_dst_path in self.existing_paths

        if src_in_existing and not dst_in_existing:
            # 文件/文件夹被移动出监控目录
            # 从 existing_paths 中移除
            self.existing_paths.discard(relative_src_path)
            self.logger.debug(f"从 existing_paths 中移除源路径: {relative_src_path}")

        if not src_in_existing and dst_in_existing:
            # 文件/文件夹被移动到监控目录
            remote_src_path = self.get_remote_source_path(relative_dst_path)
            remote_dst_path = self.get_remote_destination_path(relative_dst_path)
            success = await self.alist.rename(remote_src_path, remote_dst_path)
            if success:
                self.logger.info(f"重命名成功: {remote_src_path} -> {remote_dst_path}")
            else:
                self.logger.error(f"重命名失败: {remote_src_path} -> {remote_dst_path}")
            # 添加到 existing_paths
            self.existing_paths.add(relative_dst_path)
            self.logger.debug(f"添加到 existing_paths: {relative_dst_path}")

        if src_in_existing and dst_in_existing:
            # 文件/文件夹在监控目录内被重命名
            remote_src_path = self.get_remote_destination_path(relative_src_path)
            remote_dst_path = self.get_remote_destination_path(relative_dst_path)
            success = await self.alist.rename(remote_src_path, remote_dst_path)
            if success:
                self.logger.info(f"重命名成功: {remote_src_path} -> {remote_dst_path}")
            else:
                self.logger.error(f"重命名失败: {remote_src_path} -> {remote_dst_path}")
            # 更新 existing_paths
            self.existing_paths.discard(relative_src_path)
            self.existing_paths.add(relative_dst_path)
            self.logger.debug(f"更新 existing_paths: {relative_src_path} -> {relative_dst_path}")

    def on_created(self, event):
        """
        Watchdog 回调：文件或文件夹被创建
        """
        file_path = event.src_path
        coro = self.handle_created_or_modified(event)
        # 使用线程安全的方法调度任务
        self.loop.call_soon_threadsafe(self.schedule_task, coro, file_path)
        self.logger.debug(f"接收到创建事件: {file_path}")

    def on_modified(self, event):
        """
        Watchdog 回调：文件或文件夹被修改
        """
        file_path = event.src_path
        coro = self.handle_created_or_modified(event)
        # 使用线程安全的方法调度任务
        self.loop.call_soon_threadsafe(self.schedule_task, coro, file_path)
        self.logger.debug(f"接收到修改事件: {file_path}")

    def on_moved(self, event):
        """
        Watchdog 回调：文件或文件夹被移动
        """
        file_path = event.src_path  # 使用源路径作为键
        coro = self.handle_moved(event)
        # 使用线程安全的方法调度任务
        self.loop.call_soon_threadsafe(self.schedule_task, coro, file_path)
        self.logger.debug(f"接收到移动事件: {file_path} -> {event.dest_path}")

# 定义 SyncHandler 类
class SyncHandler(FileSystemEventHandler):
    def __init__(self, source_dir, target_dir, media_prefix, sync_config):
        super().__init__()
        self.logger = logging.getLogger('StrmSync')
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.media_prefix = media_prefix
        self.debounce_timers = defaultdict(threading.Timer)
        # 从配置文件读取 debounce_delay 和其他配置
        self.debounce_delay = sync_config.get('debounce_delay', 120)  # 延迟时间（秒）
        self.media_file_types = sync_config.get('media_file_types', ["*.mp4", "*.mkv"])
        self.ignore_file_types = sync_config.get('ignore_file_types', ['.mp'])
        self.overwrite_existing = sync_config.get('overwrite_existing', False)
        self.enable_cleanup = sync_config.get('enable_cleanup', False)
        self.full_sync_on_startup = sync_config.get('full_sync_on_startup', True)
        self.use_direct_link = sync_config.get('use_direct_link', False)
        self.base_url = sync_config.get('base_url', '')

    def get_relative_path(self, full_path):
        return os.path.relpath(full_path, self.source_dir).replace("\\", "/")

    def is_media_file(self, relative_path):
        """检查文件是否是媒体文件"""
        return any(re.fullmatch(pattern.replace("*", ".*"), relative_path) for pattern in self.media_file_types)

    def is_ignored_file(self, relative_path):
        """检查文件是否是需要忽略的文件类型（例如 .mp）"""
        return os.path.splitext(relative_path)[1].lower() in self.ignore_file_types

    def handle_debounced_event(self, event, relative_path):
        """延迟处理文件事件以防止多次触发"""
        if event.is_directory:
            self.handle_directory_event(event, relative_path)
        else:
            self.handle_file_event(event, relative_path)
        # 移除已处理的计时器
        if relative_path in self.debounce_timers:
            del self.debounce_timers[relative_path]

    def on_created(self, event):
        relative_path = self.get_relative_path(event.src_path)
        if relative_path in self.debounce_timers:
            self.debounce_timers[relative_path].cancel()
        timer = threading.Timer(self.debounce_delay, self.handle_debounced_event, args=(event, relative_path))
        self.debounce_timers[relative_path] = timer
        timer.start()

    def on_modified(self, event):
        relative_path = self.get_relative_path(event.src_path)
        if relative_path in self.debounce_timers:
            self.debounce_timers[relative_path].cancel()
        timer = threading.Timer(self.debounce_delay, self.handle_debounced_event, args=(event, relative_path))
        self.debounce_timers[relative_path] = timer
        timer.start()

    def on_deleted(self, event):
        relative_path = self.get_relative_path(event.src_path)
        # 删除操作一般不需要去抖动，可以立即处理
        if event.is_directory:
            self.handle_directory_event(event, relative_path)
        else:
            self.handle_file_event(event, relative_path)

    def handle_file_event(self, event, relative_path):
        """处理文件的创建、修改或删除"""
        if self.is_ignored_file(relative_path):
            # self.logger.info(f"跳过: 忽略文件类型: {relative_path}")
            return

        if event.event_type in ['created', 'modified']:
            if self.is_media_file(relative_path):
                self.create_strm_file(relative_path)
            else:
                self.sync_file(relative_path)
        elif event.event_type == 'deleted' and self.enable_cleanup:
            self.delete_target_file(relative_path)

    def handle_directory_event(self, event, relative_path):
        """处理目录的创建或删除"""
        target_dir_path = os.path.join(self.target_dir, relative_path).replace("\\", "/")
        if event.event_type == 'deleted' and self.enable_cleanup:
            if os.path.exists(target_dir_path):
                try:
                    shutil.rmtree(target_dir_path)
                    self.logger.info(f"成功删除目标目录: {target_dir_path}")
                except Exception as e:
                    self.logger.error(f"错误: 无法删除目标目录: {target_dir_path}, {e}")
        elif event.event_type == 'created':
            if not os.path.exists(target_dir_path):
                try:
                    os.makedirs(target_dir_path, exist_ok=True)
                    self.logger.info(f"成功创建目标目录: {target_dir_path}")
                except Exception as e:
                    self.logger.error(f"错误: 无法创建目标目录: {target_dir_path}, {e}")

    def create_strm_file(self, relative_path):
        """生成 .strm 文件"""
        target_strm_file = os.path.join(self.target_dir, os.path.splitext(relative_path)[0] + ".strm").replace("\\", "/")
        if os.path.exists(target_strm_file) and not self.overwrite_existing:
            self.logger.info(f"跳过: .strm 文件已存在: {target_strm_file}")
            return

        strm_content = f"{self.base_url}{self.media_prefix}/{relative_path}" if self.use_direct_link else f"{self.media_prefix}/{relative_path}"

        try:
            os.makedirs(os.path.dirname(target_strm_file), exist_ok=True)
            with open(target_strm_file, "w") as f:
                f.write(strm_content)
            self.logger.info(f"成功生成 .strm 文件: {target_strm_file}")
        except Exception as e:
            self.logger.error(f"错误: 无法生成 .strm 文件: {target_strm_file}, {e}")

    def sync_file(self, relative_path):
        """同步文件"""
        source_file_path = os.path.join(self.source_dir, relative_path).replace("\\", "/")
        target_file_path = os.path.join(self.target_dir, relative_path).replace("\\", "/")

        os.makedirs(os.path.dirname(target_file_path), exist_ok=True)

        if not self.overwrite_existing and os.path.exists(target_file_path):
            self.logger.info(f"跳过: 非媒体文件已存在: {target_file_path}")
            return

        try:
            shutil.copy2(source_file_path, target_file_path)
            self.logger.info(f"成功同步非媒体文件: {source_file_path} -> {target_file_path}")
        except Exception as e:
            self.logger.error(f"错误: 无法同步非媒体文件: {source_file_path} -> {target_file_path}, {e}")

    def delete_target_file(self, relative_path):
        """删除目标文件及其关联的 .strm 文件"""
        target_file_path = os.path.join(self.target_dir, relative_path).replace("\\", "/")

        # 如果目标是一个文件，首先删除它
        if os.path.exists(target_file_path):
            try:
                # 如果是文件夹，使用 rmtree 删除文件夹
                if os.path.isdir(target_file_path):
                    shutil.rmtree(target_file_path)
                    self.logger.info(f"成功删除目标目录: {target_file_path}")
                else:
                    os.remove(target_file_path)
                    self.logger.info(f"成功删除目标文件: {target_file_path}")
            except Exception as e:
                self.logger.error(f"错误: 无法删除目标文件/目录: {target_file_path}, {e}")

        # 如果是媒体文件且存在相应的 .strm 文件，删除对应的 .strm 文件
        if self.is_media_file(relative_path):
            strm_file_path = os.path.splitext(target_file_path)[0] + ".strm"
            if os.path.exists(strm_file_path):
                try:
                    os.remove(strm_file_path)
                    self.logger.info(f"成功删除关联的 .strm 文件: {strm_file_path}")
                except Exception as e:
                    self.logger.error(f"错误: 无法删除 .strm 文件: {strm_file_path}, {e}")

async def main():
    # 获取当前事件循环
    loop = asyncio.get_running_loop()

    # 获取同步全局配置
    sync_config = config.get('sync', {})
    alist_config = config.get('alist', {})

    # 获取 alist 配置列表
    source_base_directories = alist_config.get('source_base_directories', [])
    remote_base_directories = alist_config.get('remote_base_directories', [])
    local_directories = alist_config.get('local_directories', [])

    # 获取 sync_directories 列表
    sync_directories = sync_config.get('sync_directories', [])

    observers = []

    # 初始化 AList 功能（如果配置存在）
    if alist_config:
        # 确保 base directories 的数量与 sync_directories 相同
        if not (len(source_base_directories) == len(remote_base_directories) == len(local_directories)):
            logger.error("配置错误: 'source_base_directories', 'remote_base_directories' 和 'local_directories' 的长度必须相同。")
        else:
            for index in range(len(sync_directories)):
                # 检查是否有对应的 sync_directory
                if index >= len(sync_directories):
                    logger.warning(f"目录集 {index + 1}: 缺少对应的 'sync_directories' 配置，跳过。")
                    continue

                mapping = sync_directories[index]
                source_dir = mapping.get('source_dir')
                target_dir = mapping.get('target_dir')
                media_prefix = mapping.get('media_prefix')

                if not all([source_dir, target_dir, media_prefix]):
                    logger.warning(f"目录集 {index + 1}: 'sync_directories' 配置不完整，跳过。")
                    continue

                logger.info(f"开始监控目录集 {index + 1}: {source_dir} -> {target_dir} (media 前缀: {media_prefix})")

                # 初始化 AList 实例
                alist = AList(endpoint=alist_config['endpoint'])
                user = AListUser(username=alist_config['username'], rawpwd=alist_config['password'])
                login_success = await alist.login(user)
                if not login_success:
                    logger.error(f"目录集 {index + 1}: 登录失败，请检查用户名和密码。")
                    continue
                logger.info(f"目录集 {index + 1}: 登录成功。")

                # 初始化 SyncHandler
                event_handler = SyncHandler(source_dir, target_dir, media_prefix, sync_config)

                # 执行初始全量同步并收集 ignore_paths_per_task
                ignore_paths_per_task = set()
                if sync_config.get('full_sync_on_startup', True):
                    logger.info(f"目录集 {index + 1}: 执行初始全量同步: {source_dir} -> {target_dir}")
                    for root, dirs, files in os.walk(source_dir):
                        relative_root = os.path.relpath(root, source_dir).replace("\\", "/")
                        if relative_root == ".":
                            relative_root = ""
                        # 创建目录结构
                        target_root = os.path.join(target_dir, relative_root).replace("\\", "/")
                        if not os.path.exists(target_root):
                            try:
                                os.makedirs(target_root, exist_ok=True)
                                logger.info(f"目录集 {index + 1}: 创建目录: {target_root}")
                            except Exception as e:
                                logger.error(f"目录集 {index + 1}: 错误: 无法创建目录: {target_root}, {e}")
                        for file in files:
                            relative_path = os.path.join(relative_root, file).replace("\\", "/")
                            if event_handler.is_media_file(relative_path):
                                event_handler.create_strm_file(relative_path)
                            else:
                                event_handler.sync_file(relative_path)
                            # 收集处理过的路径到 ignore_paths_per_task
                            ignore_paths_per_task.add(relative_path)

                # 初始化 AListSyncHandler，传入 ignore_paths_per_task（如果启用全量同步）
                alist_sync_handler = AListSyncHandler(
                    alist=alist,
                    remote_base_path=remote_base_directories[index],
                    local_base_path=local_directories[index],
                    loop=loop,
                    source_base_directory=source_base_directories[index],
                    debounce_delay=1.0,  # 设置防抖延迟时间为1秒
                    file_stable_time=5.0,  # 设置文件稳定时间为5秒
                    ignore_paths=ignore_paths_per_task if sync_config.get('full_sync_on_startup', True) else None  # 传入忽略路径
                )

                # 设置 AList 观察者
                alist_observer = Observer()
                alist_observer.schedule(alist_sync_handler, path=local_directories[index], recursive=True)
                alist_observer.start()
                observers.append(alist_observer)
                logger.info(f"目录集 {index + 1}: 开始监控 AList 本地目录: {local_directories[index]}")

                # 设置 SyncHandler 观察者
                sync_observer = Observer()
                sync_observer.schedule(event_handler, path=source_dir, recursive=True)
                sync_observer.start()
                observers.append(sync_observer)
                logger.info(f"目录集 {index + 1}: 开始监控同步目录: {source_dir}")

    # 初始化 Sync 功能（如果配置存在）
    if sync_config:
        # 获取 sync_directories 列表
        sync_directories = sync_config.get('sync_directories', [])

        for index, mapping in enumerate(sync_directories, start=1):
            source_dir = mapping.get('source_dir')
            target_dir = mapping.get('target_dir')
            media_prefix = mapping.get('media_prefix')

            if not all([source_dir, target_dir, media_prefix]):
                logger.warning(f"同步任务 {index}: 'sync_directories' 配置不完整，跳过。")
                continue

            logger.info(f"开始监控同步任务 {index}: {source_dir} -> {target_dir} (media 前缀: {media_prefix})")

            # 初始化 SyncHandler
            event_handler = SyncHandler(source_dir, target_dir, media_prefix, sync_config)

            # 设置 SyncHandler 观察者
            sync_observer = Observer()
            sync_observer.schedule(event_handler, path=source_dir, recursive=True)
            sync_observer.start()
            observers.append(sync_observer)
            logger.info(f"同步任务 {index}: 开始监控同步目录: {source_dir}")

    try:
        while True:
            await asyncio.sleep(1)  # 保持主线程运行
    except KeyboardInterrupt:
        logger.info("========== 停止监控任务 ==========")
        # 停止所有观察者
        for observer in observers:
            observer.stop()
        # 等待所有观察者线程结束
        for observer in observers:
            observer.join()

if __name__ == "__main__":
    asyncio.run(main())
