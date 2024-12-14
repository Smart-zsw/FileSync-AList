import asyncio
import functools
import os
import logging
from logging.handlers import RotatingFileHandler
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from alist import AList, AListUser

# 定义字幕文件的扩展名
SUBTITLE_EXTENSIONS = {'.srt', '.ass', '.sub', '.vtt'}

class AListSyncHandler(FileSystemEventHandler):
    def __init__(
            self,
            alist: AList,
            remote_base_path: str,
            local_base_path: str,
            loop: asyncio.AbstractEventLoop,
            source_base_directory: str,
            debounce_delay: float = 1.0,
            sync_delete: bool = False,
            file_stable_time: float = 5.0  # 新增：文件稳定时间（秒）
    ):
        super().__init__()
        self.alist = alist
        self.remote_base_path = remote_base_path.rstrip('/')  # 去除末尾的斜杠
        self.local_base_path = local_base_path.rstrip('/')
        self.loop = loop  # 主线程的事件循环
        self.source_base_directory = source_base_directory.rstrip('/')
        self.debounce_delay = debounce_delay  # 防抖延迟时间（秒）
        self.sync_delete = sync_delete  # 同步删除开关
        self.file_stable_time = file_stable_time  # 文件稳定时间（秒）
        self._tasks = {}  # 跟踪文件路径到任务的映射
        self.existing_paths = set()  # 存储启动时已有的文件和文件夹的相对路径

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
        logging.info(f"已记录 {len(self.existing_paths)} 个现有路径，不会监控这些路径。")

    def should_ignore_file_creation_deletion(self, file_path):
        """
        判断文件是否是以 .mp 结尾的文件，若是则在创建和删除事件中忽略。
        """
        return file_path.lower().endswith(".mp")

    def is_subtitle_file(self, file_path):
        """
        判断文件是否为字幕文件。
        """
        _, ext = os.path.splitext(file_path)
        return ext.lower() in SUBTITLE_EXTENSIONS

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
            logging.debug(f"取消之前的任务: {file_path}")
        # 使用线程安全的方法调度任务
        future = asyncio.run_coroutine_threadsafe(self.debounce(coro, file_path), self.loop)
        self._tasks[file_path] = future
        logging.debug(f"调度新任务: {file_path}")

    async def debounce(self, coro, file_path):
        """
        等待防抖延迟后执行协程
        """
        try:
            await asyncio.sleep(self.debounce_delay)
            await coro
        except asyncio.CancelledError:
            logging.debug(f"任务被取消: {file_path}")
            pass
        finally:
            self._tasks.pop(file_path, None)
            logging.debug(f"任务完成或取消，移除任务: {file_path}")

    async def is_file_complete(self, file_path):
        """
        检查文件在指定时间内是否保持大小不变，以确定文件是否完整
        """
        logging.debug(f"开始检查文件完整性: {file_path}")
        previous_size = -1
        stable_time = 0.0
        check_interval = 1.0  # 检查间隔（秒）

        while True:
            if not os.path.exists(file_path):
                logging.warning(f"文件不存在，无法检查完整性: {file_path}")
                return False
            current_size = os.path.getsize(file_path)
            if current_size == previous_size:
                stable_time += check_interval
                logging.debug(f"文件大小未变化，稳定时间: {stable_time:.1f}/{self.file_stable_time} 秒")
                if stable_time >= self.file_stable_time:
                    # logging.info(f"文件已完成写入: {file_path}")
                    return True
            else:
                stable_time = 0.0
                logging.debug(f"文件大小变化，从 {previous_size} 到 {current_size}")
                previous_size = current_size
            await asyncio.sleep(check_interval)

    async def handle_created_or_modified(self, event):
        """
        处理文件或文件夹的创建和修改事件
        """
        relative_path = self.get_relative_path(event.src_path)

        # 跳过相对路径为 '.' 或空字符串的事件
        if relative_path in ('', '.'):
            logging.warning(f"跳过相对路径为 '.' 或空字符串的事件: {event.src_path}")
            return

        # 对于创建事件，忽略 .mp 文件
        if event.event_type == 'created' and self.should_ignore_file_creation_deletion(relative_path):
            logging.debug(f"忽略创建事件中的 .mp 文件: {relative_path}")
            return

        # 对于修改事件，处理所有文件
        if event.event_type == 'modified':
            # 这里可以添加针对修改事件的特定逻辑
            if self.is_subtitle_file(relative_path):
                logging.info(f"检测到字幕文件修改: {relative_path}")
                await self.copy_subtitle_file(relative_path)

        # 检查是否是新增文件或文件夹（仅处理修改事件中的新增）
        if event.event_type == 'modified' and relative_path not in self.existing_paths:
            # 标记为已存在
            self.existing_paths.add(relative_path)
            # logging.info(f"新增路径 (修改事件): {relative_path}")

            remote_source_path = self.get_remote_source_path(relative_path)  # AList 中的源路径
            remote_destination_path = self.get_remote_destination_path(relative_path)  # AList 中的目的路径

            if event.is_directory:
                # 对于文件夹，只创建目标文件夹
                success = await self.alist.mkdir(remote_destination_path)
                if success:
                    logging.info(f"文件夹创建成功: {remote_destination_path}")
                else:
                    logging.error(f"文件夹创建失败或已存在: {remote_destination_path}")
            else:
                # 文件：先检查文件是否完整，然后复制
                file_path = event.src_path
                if await self.is_file_complete(file_path):
                    await self.copy_file(remote_source_path, remote_destination_path)
                else:
                    logging.error(f"文件未完成写入，无法复制: {file_path}")

    async def copy_subtitle_file(self, relative_path):
        """
        复制文件到 AList
        在复制之前，先刷新源目录，确保 AList 检测到新增的文件
        """
        remote_source_path = self.get_remote_source_path(relative_path)
        remote_destination_path = self.get_remote_destination_path(relative_path)

        try:
            # 调用 list_dir 并强制刷新源目录
            source_dir = os.path.dirname(remote_source_path)
            async for _ in self.alist.list_dir(source_dir, refresh=True):
                pass  # 仅需要执行刷新，无需处理返回的生成器
            # logging.info(f"刷新 AList 中的源路径目录: {source_dir}")
        except Exception as e:
            logging.error(f"刷新 AList 中的源路径目录失败: {source_dir}, 错误: {e}")
            return  # 如果刷新失败，则不进行复制操作

        # 执行复制操作
        try:
            # 根据 API 文档，copy 方法的第二个参数应该是目标目录，而不是完整的目标路径
            destination_dir = os.path.dirname(remote_destination_path)
            success = await self.alist.copy(remote_source_path, destination_dir)
            if success:
                logging.info(f"字幕文件复制成功: {remote_source_path} -> {remote_destination_path}")
            else:
                logging.error(f"字幕文件复制失败: {remote_source_path} -> {remote_destination_path}")
        except Exception as e:
            logging.error(f"执行复制操作时出错: {remote_source_path} -> {remote_destination_path}, 错误: {e}")

    async def handle_deleted(self, event):
        """
        处理文件或文件夹的删除事件
        """
        relative_path = self.get_relative_path(event.src_path)

        # 跳过相对路径为 '.' 或空字符串的事件
        if relative_path in ('', '.'):
            logging.warning(f"跳过相对路径为 '.' 或空字符串的删除事件: {event.src_path}")
            return

        # 对于删除事件，忽略 .mp 文件
        if self.should_ignore_file_creation_deletion(relative_path):
            logging.debug(f"忽略删除事件中的 .mp 文件: {relative_path}")
            return

        # 仅处理程序启动后新增的文件或文件夹的删除
        if relative_path not in self.existing_paths:
            logging.debug(f"删除事件的路径不在监控范围内，跳过: {relative_path}")
            return

        if not self.sync_delete:
            logging.info(f"同步删除功能关闭，忽略删除事件: {relative_path}")
            return

        remote_destination_path = self.get_remote_destination_path(relative_path)
        if event.is_directory:
            success = await self.alist.remove_folder(remote_destination_path)
            if success:
                logging.info(f"文件夹删除成功: {remote_destination_path}")
            else:
                logging.error(f"文件夹删除失败: {remote_destination_path}")
        else:
            success = await self.alist.remove(remote_destination_path)
            if success:
                logging.info(f"文件删除成功: {remote_destination_path}")
            else:
                logging.error(f"文件删除失败: {remote_destination_path}")

        # 从 existing_paths 中移除
        self.existing_paths.discard(relative_path)
        logging.debug(f"从 existing_paths 中移除: {relative_path}")

    async def handle_moved(self, event):
        """
        处理文件或文件夹的移动事件
        """
        relative_src_path = self.get_relative_path(event.src_path)
        relative_dst_path = self.get_relative_path(event.dest_path)

        # 跳过相对路径为 '.' 或空字符串的事件
        if relative_src_path in ('', '.') or relative_dst_path in ('', '.'):
            logging.warning(f"跳过相对路径为 '.' 或空字符串的移动事件: {event.src_path} -> {event.dest_path}")
            return

        # 检查是否是从 .mp 重命名为字幕文件
        src_ext = os.path.splitext(relative_src_path)[1].lower()
        dst_ext = os.path.splitext(relative_dst_path)[1].lower()

        if src_ext == ".mp" and self.is_subtitle_file(relative_dst_path):
            # logging.info(f"检测到 .mp 文件重命名为字幕文件: {relative_src_path} -> {relative_dst_path}")
            await self.copy_subtitle_file(relative_dst_path)
            # 更新 existing_paths
            self.existing_paths.discard(relative_src_path)
            self.existing_paths.add(relative_dst_path)
            logging.debug(f"更新 existing_paths: {relative_src_path} -> {relative_dst_path}")
            return

        src_in_existing = relative_src_path in self.existing_paths
        dst_in_existing = relative_dst_path in self.existing_paths

        if src_in_existing and not dst_in_existing:
            # 文件/文件夹被移动出监控目录
            if self.sync_delete:
                remote_src_path = self.get_remote_destination_path(relative_src_path)
                if event.is_directory:
                    success = await self.alist.remove_folder(remote_src_path)
                    if success:
                        logging.info(f"文件夹移动删除成功: {remote_src_path}")
                    else:
                        logging.error(f"文件夹移动删除失败: {remote_src_path}")
                else:
                    success = await self.alist.remove(remote_src_path)
                    if success:
                        logging.info(f"文件移动删除成功: {remote_src_path}")
                    else:
                        logging.error(f"文件移动删除失败: {remote_src_path}")
            # 从 existing_paths 中移除
            self.existing_paths.discard(relative_src_path)
            logging.debug(f"从 existing_paths 中移除源路径: {relative_src_path}")

        if not src_in_existing and dst_in_existing:
            # 文件/文件夹被移动到监控目录
            remote_src_path = self.get_remote_source_path(relative_dst_path)
            remote_dst_path = self.get_remote_destination_path(relative_dst_path)
            success = await self.alist.rename(remote_src_path, remote_dst_path)
            if success:
                logging.info(f"重命名成功: {remote_src_path} -> {remote_dst_path}")
            else:
                logging.error(f"重命名失败: {remote_src_path} -> {remote_dst_path}")
            # 添加到 existing_paths
            self.existing_paths.add(relative_dst_path)
            logging.debug(f"添加到 existing_paths: {relative_dst_path}")

        if src_in_existing and dst_in_existing:
            # 文件/文件夹在监控目录内被重命名
            remote_src_path = self.get_remote_destination_path(relative_src_path)
            remote_dst_path = self.get_remote_destination_path(relative_dst_path)
            success = await self.alist.rename(remote_src_path, remote_dst_path)
            if success:
                logging.info(f"重命名成功: {remote_src_path} -> {remote_dst_path}")
            else:
                logging.error(f"重命名失败: {remote_src_path} -> {remote_dst_path}")
            # 更新 existing_paths
            self.existing_paths.discard(relative_src_path)
            self.existing_paths.add(relative_dst_path)
            logging.debug(f"更新 existing_paths: {relative_src_path} -> {relative_dst_path}")

    def on_created(self, event):
        """
        Watchdog 回调：文件或文件夹被创建
        """
        file_path = event.src_path
        # 使用 asyncio.run_coroutine_threadsafe 调度协程
        coro = functools.partial(self.handle_created_or_modified, event)
        asyncio.run_coroutine_threadsafe(coro(), self.loop)  # 通过主线程的事件循环调度
        logging.debug(f"接收到创建事件: {file_path}")

    def on_modified(self, event):
        """
        Watchdog 回调：文件或文件夹被修改
        """
        file_path = event.src_path
        # 使用 asyncio.run_coroutine_threadsafe 调度协程
        coro = functools.partial(self.handle_created_or_modified, event)
        asyncio.run_coroutine_threadsafe(coro(), self.loop)  # 通过主线程的事件循环调度
        logging.debug(f"接收到修改事件: {file_path}")

    def on_deleted(self, event):
        """
        Watchdog 回调：文件或文件夹被删除
        """
        file_path = event.src_path
        # 使用 asyncio.run_coroutine_threadsafe 调度协程
        coro = functools.partial(self.handle_deleted, event)
        asyncio.run_coroutine_threadsafe(coro(), self.loop)  # 通过主线程的事件循环调度
        logging.debug(f"接收到删除事件: {file_path}")

    def on_moved(self, event):
        """
        Watchdog 回调：文件或文件夹被移动
        """
        file_path = event.src_path  # 使用源路径作为键
        # 使用 asyncio.run_coroutine_threadsafe 调度协程
        coro = functools.partial(self.handle_moved, event)
        asyncio.run_coroutine_threadsafe(coro(), self.loop)  # 通过主线程的事件循环调度
        logging.debug(f"接收到移动事件: {file_path} -> {event.dest_path}")

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
            # logging.info(f"刷新 AList 中的源路径目录: {source_dir}")
        except Exception as e:
            logging.error(f"刷新 AList 中的源路径目录失败: {source_dir}, 错误: {e}")
            return  # 如果刷新失败，则不进行复制操作

        # 执行复制操作
        try:
            # 根据 API 文档，copy 方法的第二个参数应该是目标目录，而不是完整的目标路径
            destination_dir = os.path.dirname(remote_destination_path)
            success = await self.alist.copy(remote_source_path, destination_dir)
            if success:
                logging.info(f"文件复制成功: {remote_source_path} -> {remote_destination_path}")
            else:
                logging.error(f"文件复制失败: {remote_source_path} -> {remote_destination_path}")
        except Exception as e:
            logging.error(f"执行复制操作时出错: {remote_source_path} -> {remote_destination_path}, 错误: {e}")

async def main():
    # 从环境变量读取配置
    endpoint = os.getenv("ALIST_ENDPOINT")
    username = os.getenv("ALIST_USERNAME")
    password_file = os.getenv("ALIST_PASSWORD_FILE", "/config/secrets/alist_password.txt")
    log_file = os.getenv("LOG_FILE", "/config/logs/sync_to_alist.log")
    sync_delete_env = os.getenv("SYNC_DELETE", "false").lower()
    sync_delete = sync_delete_env == "true"

    # 多个源和目标目录的配置
    source_base_directories = os.getenv("ALIST_SOURCE_BASE_DIRECTORIES").split(";")
    remote_base_directories = os.getenv("ALIST_REMOTE_BASE_DIRECTORIES").split(";")
    local_directories = os.getenv("LOCAL_DIRECTORIES").split(";")

    if len(source_base_directories) != len(remote_base_directories) or len(local_directories) != len(remote_base_directories):
        logging.error("源目录、远程目录、本地目录数量不匹配，请检查配置。")
        return

    # 读取密码
    if not os.path.exists(password_file):
        logging.error(f"密码文件 {password_file} 不存在。")
        return
    with open(password_file, "r") as f:
        password = f.read().strip()

    # 配置日志
    log_dir = os.path.dirname(log_file)
    os.makedirs(log_dir, exist_ok=True)

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    logging.info("日志配置完成。")

    # 初始化 AList 实例
    alist = AList(endpoint=endpoint)
    user = AListUser(username=username, rawpwd=password)
    login_success = await alist.login(user)
    if not login_success:
        logging.error("登录失败，请检查用户名和密码。")
        return
    logging.info("登录成功。")

    # 获取当前事件循环
    loop = asyncio.get_running_loop()
    observers = []

    # 为每对目录设置同步处理器和监控
    for local_dir, source_dir, remote_dir in zip(local_directories, source_base_directories, remote_base_directories):
        event_handler = AListSyncHandler(
            alist=alist,
            remote_base_path=remote_dir,
            local_base_path=local_dir,
            loop=loop,
            source_base_directory=source_dir,
            debounce_delay=1.0,  # 设置防抖延迟时间为1秒
            sync_delete=sync_delete,  # 同步删除开关
            file_stable_time=5.0  # 设置文件稳定时间为5秒
        )

        observer = Observer()
        observer.schedule(event_handler, path=local_dir, recursive=True)
        observer.start()
        logging.info(f"开始监控本地目录: {local_dir}")
        observers.append(observer)

    try:
        while True:
            await asyncio.sleep(1)  # 保持主线程运行
    except KeyboardInterrupt:
        for observer in observers:
            observer.stop()
        logging.info("停止所有监控。")
    for observer in observers:
        observer.join()

if __name__ == "__main__":
    asyncio.run(main())
