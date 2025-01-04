import asyncio
import functools
import os
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from alist import AList, AListUser


class AListSyncHandler(FileSystemEventHandler):
    def __init__(
            self,
            alist: AList,
            user: AListUser,  # 新增：接收 AListUser 对象
            remote_base_path: str,
            local_base_path: str,
            loop: asyncio.AbstractEventLoop,
            source_base_directory: str,
            subtitle_extensions: set,  # 新增：字幕扩展名
            debounce_delay: float = 1.0,
            sync_delete: bool = False,
            file_stable_time: float = 5.0  # 新增：文件稳定时间（秒）
    ):
        super().__init__()
        self.alist = alist
        self.user = user  # 新增：存储用户对象
        self.remote_base_path = remote_base_path.rstrip('/')
        self.local_base_path = local_base_path.rstrip('/')
        self.loop = loop
        self.source_base_directory = source_base_directory.rstrip('/')
        self.debounce_delay = debounce_delay  # 防抖延迟时间（秒）
        self.sync_delete = sync_delete  # 同步删除开关
        self.file_stable_time = file_stable_time  # 文件稳定时间（秒）
        self.subtitle_extensions = subtitle_extensions  # 设置字幕扩展名
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
        logging.info(f"[ALIST] 已记录 {len(self.existing_paths)} 个现有路径，不会监控这些路径。")

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
        return ext.lower() in self.subtitle_extensions

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
            task.cancel()
            logging.debug(f"[ALIST] 取消之前的任务: {file_path}")
        future = asyncio.run_coroutine_threadsafe(self.debounce(coro, file_path), self.loop)
        self._tasks[file_path] = future
        logging.debug(f"[ALIST] 调度新任务: {file_path}")

    async def debounce(self, coro, file_path):
        """
        等待防抖延迟后执行协程
        """
        try:
            await asyncio.sleep(self.debounce_delay)
            await coro
        except asyncio.CancelledError:
            logging.debug(f"[ALIST] 任务被取消: {file_path}")
            pass
        finally:
            self._tasks.pop(file_path, None)
            logging.debug(f"[ALIST] 任务完成或取消，移除任务: {file_path}")

    async def is_file_complete(self, file_path):
        """
        检查文件在指定时间内是否保持大小不变，以确定文件是否完整
        """
        logging.debug(f"[ALIST] 开始检查文件完整性: {file_path}")
        previous_size = -1
        stable_time = 0.0
        check_interval = 1.0  # 检查间隔（秒）

        while True:
            if not os.path.exists(file_path):
                logging.warning(f"[ALIST] 文件不存在，无法检查完整性: {file_path}")
                return False
            current_size = os.path.getsize(file_path)
            if current_size == previous_size:
                stable_time += check_interval
                logging.debug(f"[ALIST] 文件大小未变化，稳定时间: {stable_time:.1f}/{self.file_stable_time} 秒")
                if stable_time >= self.file_stable_time:
                    # logging.info(f"[ALIST] 文件已完成写入: {file_path}")
                    return True
            else:
                stable_time = 0.0
                logging.debug(f"[ALIST] 文件大小变化，从 {previous_size} 到 {current_size}")
                previous_size = current_size
            await asyncio.sleep(check_interval)

    async def handle_created_or_modified(self, event, retry=False):
        """
        处理文件或文件夹的创建和修改事件
        """
        relative_path = self.get_relative_path(event.src_path)
        if relative_path in ('', '.'):
            logging.warning(f"[ALIST] 跳过相对路径为 '.' 或空字符串的事件: {event.src_path}")
            return

        # 对于创建事件，忽略 .mp 文件
        if event.event_type == 'created' and self.should_ignore_file_creation_deletion(relative_path):
            logging.debug(f"[ALIST] 忽略创建事件中的 .mp 文件: {relative_path}")
            return

        # 仅在修改事件中且文件不在 existing_paths 时处理
        if event.event_type == 'modified':
            if self.is_subtitle_file(relative_path):
                logging.info(f"[ALIST] 检测到字幕文件修改: {relative_path}")
                await self.copy_subtitle_file(relative_path)

        # 仅在修改事件中且文件不在 existing_paths 时处理非字幕文件
        if event.event_type == 'modified' and relative_path not in self.existing_paths:
            self.existing_paths.add(relative_path)
            remote_source_path = self.get_remote_source_path(relative_path)
            remote_destination_path = self.get_remote_destination_path(relative_path)

            if event.is_directory:
                try:
                    success = await self.alist.mkdir(remote_destination_path)
                    if success:
                        logging.info(f"[ALIST] 文件夹创建成功: {remote_destination_path}")
                    else:
                        logging.error(f"[ALIST] 文件夹创建失败或已存在: {remote_destination_path}")
                except Exception as e:
                    if not retry and 'token is expired' in str(e).lower():
                        logging.warning(f"[ALIST] Token 过期，尝试重新登录并重试 mkdir 操作。")
                        await self.alist.login(self.user)
                        await self.handle_created_or_modified(event, retry=True)
                    else:
                        logging.error(f"[ALIST] 创建文件夹失败: {remote_destination_path}, 错误: {e}")
            else:
                file_path = event.src_path
                try:
                    if await self.is_file_complete(file_path):
                        await self.copy_file(remote_source_path, remote_destination_path)
                    else:
                        logging.error(f"[ALIST] 文件未完成写入，无法复制: {file_path}")
                except Exception as e:
                    if not retry and 'token is expired' in str(e).lower():
                        logging.warning(f"[ALIST] Token 过期，尝试重新登录并重试复制文件操作。")
                        await self.alist.login(self.user)
                        await self.handle_created_or_modified(event, retry=True)
                    else:
                        logging.error(f"[ALIST] 处理创建或修改事件时出错: {file_path}, 错误: {e}")

    async def copy_subtitle_file(self, relative_path, retry=False):
        """
        复制字幕文件到 AList
        在复制之前，先刷新源目录，确保 AList 检测到新增的文件
        """
        remote_source_path = self.get_remote_source_path(relative_path)
        remote_destination_path = self.get_remote_destination_path(relative_path)
        try:
            source_dir = os.path.dirname(remote_source_path)
            async for _ in self.alist.list_dir(source_dir, refresh=True):
                pass
        except Exception as e:
            if not retry and 'token is expired' in str(e).lower():
                logging.warning(f"[ALIST] Token 过期，尝试重新登录并重试刷新源路径目录。")
                await self.alist.login(self.user)
                await self.copy_subtitle_file(relative_path, retry=True)
                return
            logging.error(f"[ALIST] 刷新 AList 中的源路径目录失败: {source_dir}, 错误: {e}")
            return

        # 执行复制操作
        try:
            destination_dir = os.path.dirname(remote_destination_path)
            success = await self.alist.copy(remote_source_path, destination_dir)
            if success:
                logging.info(f"[ALIST] 字幕文件复制成功: {remote_source_path} -> {remote_destination_path}")
            else:
                logging.error(f"[ALIST] 字幕文件复制失败: {remote_source_path} -> {remote_destination_path}")
        except Exception as e:
            if not retry and 'token is expired' in str(e).lower():
                logging.warning(f"[ALIST] Token 过期，尝试重新登录并重试复制字幕文件操作。")
                await self.alist.login(self.user)
                await self.copy_subtitle_file(relative_path, retry=True)
                return
            logging.error(f"[ALIST] 执行复制操作时出错: {remote_source_path} -> {remote_destination_path}, 错误: {e}")

    async def handle_deleted(self, event, retry=False):
        """
        处理文件或文件夹的删除事件
        """
        relative_path = self.get_relative_path(event.src_path)
        if relative_path in ('', '.'):
            logging.warning(f"[ALIST] 跳过相对路径为 '.' 或空字符串的删除事件: {event.src_path}")
            return
        if self.should_ignore_file_creation_deletion(relative_path):
            logging.debug(f"[ALIST] 忽略删除事件中的 .mp 文件: {relative_path}")
            return
        if relative_path not in self.existing_paths:
            logging.debug(f"[ALIST] 删除事件的路径不在监控范围内，跳过: {relative_path}")
            return
        if not self.sync_delete:
            logging.info(f"[ALIST] 同步删除功能关闭，忽略删除事件: {relative_path}")
            return

        remote_destination_path = self.get_remote_destination_path(relative_path)
        try:
            if event.is_directory:
                success = await self.alist.remove_folder(remote_destination_path)
                if success:
                    logging.info(f"[ALIST] 文件夹删除成功: {remote_destination_path}")
                else:
                    logging.error(f"[ALIST] 文件夹删除失败: {remote_destination_path}")
            else:
                success = await self.alist.remove(remote_destination_path)
                if success:
                    logging.info(f"[ALIST] 文件删除成功: {remote_destination_path}")
                else:
                    logging.error(f"[ALIST] 文件删除失败: {remote_destination_path}")
            self.existing_paths.discard(relative_path)
            logging.debug(f"[ALIST] 从 existing_paths 中移除: {relative_path}")
        except Exception as e:
            if not retry and 'token is expired' in str(e).lower():
                logging.warning(f"[ALIST] Token 过期，尝试重新登录并重试删除操作。")
                await self.alist.login(self.user)
                await self.handle_deleted(event, retry=True)
            else:
                logging.error(f"[ALIST] 处理删除事件时出错: {relative_path}, 错误: {e}")

    async def handle_moved(self, event, retry=False):
        relative_src_path = self.get_relative_path(event.src_path)
        relative_dst_path = self.get_relative_path(event.dest_path)

        if relative_src_path in ('', '.') or relative_dst_path in ('', '.'):
            logging.warning(f"[ALIST] 跳过相对路径为 '.' 或空字符串的移动事件: {event.src_path} -> {event.dest_path}")
            return
        src_ext = os.path.splitext(relative_src_path)[1].lower()

        if src_ext == ".mp" and self.is_subtitle_file(relative_dst_path):
            await self.copy_subtitle_file(relative_dst_path)
            self.existing_paths.discard(relative_src_path)
            self.existing_paths.add(relative_dst_path)
            logging.debug(f"[ALIST] 更新 existing_paths: {relative_src_path} -> {relative_dst_path}")
            return

        src_in_existing = relative_src_path in self.existing_paths
        dst_in_existing = relative_dst_path in self.existing_paths

        try:
            if src_in_existing and not dst_in_existing:
                if self.sync_delete:
                    remote_src_path = self.get_remote_destination_path(relative_src_path)
                    if event.is_directory:
                        success = await self.alist.remove_folder(remote_src_path)
                        if success:
                            logging.info(f"[ALIST] 文件夹移动删除成功: {remote_src_path}")
                        else:
                            logging.error(f"[ALIST] 文件夹移动删除失败: {remote_src_path}")
                    else:
                        success = await self.alist.remove(remote_src_path)
                        if success:
                            logging.info(f"[ALIST] 文件移动删除成功: {remote_src_path}")
                        else:
                            logging.error(f"[ALIST] 文件移动删除失败: {remote_src_path}")
                self.existing_paths.discard(relative_src_path)
                logging.debug(f"[ALIST] 从 existing_paths 中移除源路径: {relative_src_path}")

            if not src_in_existing and dst_in_existing:
                remote_src_path = self.get_remote_source_path(relative_dst_path)
                remote_dst_path = self.get_remote_destination_path(relative_dst_path)
                success = await self.alist.rename(remote_src_path, remote_dst_path)
                if success:
                    logging.info(f"[ALIST] 重命名成功: {remote_src_path} -> {remote_dst_path}")
                else:
                    logging.error(f"[ALIST] 重命名失败: {remote_src_path} -> {remote_dst_path}")
                self.existing_paths.add(relative_dst_path)
                logging.debug(f"[ALIST] 添加到 existing_paths: {relative_dst_path}")

            if src_in_existing and dst_in_existing:
                remote_src_path = self.get_remote_destination_path(relative_src_path)
                remote_dst_path = self.get_remote_destination_path(relative_dst_path)
                success = await self.alist.rename(remote_src_path, remote_dst_path)
                if success:
                    logging.info(f"[ALIST] 重命名成功: {remote_src_path} -> {remote_dst_path}")
                else:
                    logging.error(f"[ALIST] 重命名失败: {remote_src_path} -> {remote_dst_path}")
                self.existing_paths.discard(relative_src_path)
                self.existing_paths.add(relative_dst_path)
                logging.debug(f"[ALIST] 更新 existing_paths: {relative_src_path} -> {relative_dst_path}")
        except Exception as e:
            if not retry and 'token is expired' in str(e).lower():
                logging.warning(f"[ALIST] Token 过期，尝试重新登录并重试移动操作。")
                await self.alist.login(self.user)
                await self.handle_moved(event, retry=True)
            else:
                logging.error(f"[ALIST] 处理移动事件时出错: {event.src_path} -> {event.dest_path}, 错误: {e}")

    def on_created(self, event):
        file_path = event.src_path
        coro = functools.partial(self.handle_created_or_modified, event)
        asyncio.run_coroutine_threadsafe(coro(), self.loop)
        logging.debug(f"[ALIST] 接收到创建事件: {file_path}")

    def on_modified(self, event):
        file_path = event.src_path
        coro = functools.partial(self.handle_created_or_modified, event)
        asyncio.run_coroutine_threadsafe(coro(), self.loop)
        logging.debug(f"[ALIST] 接收到修改事件: {file_path}")

    def on_deleted(self, event):
        file_path = event.src_path
        coro = functools.partial(self.handle_deleted, event)
        asyncio.run_coroutine_threadsafe(coro(), self.loop)
        logging.debug(f"[ALIST] 接收到删除事件: {file_path}")

    def on_moved(self, event):
        file_path = event.src_path
        coro = functools.partial(self.handle_moved, event)
        asyncio.run_coroutine_threadsafe(coro(), self.loop)
        logging.debug(f"[ALIST] 接收到移动事件: {file_path} -> {event.dest_path}")

    async def copy_file(self, remote_source_path, remote_destination_path, retry=False):
        source_dir = os.path.dirname(remote_source_path)
        try:
            async for _ in self.alist.list_dir(source_dir, refresh=True):
                pass
        except Exception as e:
            if not retry and 'token is expired' in str(e).lower():
                logging.warning(f"[ALIST] Token 过期，尝试重新登录并重试刷新源路径目录。")
                await self.alist.login(self.user)
                await self.copy_file(remote_source_path, remote_destination_path, retry=True)
                return
            logging.error(f"[ALIST] 刷新 AList 中的源路径目录失败: {source_dir}, 错误: {e}")
            return

        # 执行复制操作
        try:
            destination_dir = os.path.dirname(remote_destination_path)
            success = await self.alist.copy(remote_source_path, destination_dir)
            if success:
                logging.info(f"[ALIST] 文件复制成功: {remote_source_path} -> {remote_destination_path}")
            else:
                logging.error(f"[ALIST] 文件复制失败: {remote_source_path} -> {remote_destination_path}")
        except Exception as e:
            if not retry and 'token is expired' in str(e).lower():
                logging.warning(f"[ALIST] Token 过期，尝试重新登录并重试复制文件操作。")
                await self.alist.login(self.user)
                await self.copy_file(remote_source_path, remote_destination_path, retry=True)
                return
            logging.error(f"[ALIST] 执行复制操作时出错: {remote_source_path} -> {remote_destination_path}, 错误: {e}")


class SyncToAlist:
    def __init__(self, alist_config, sync_config):
        self.endpoint = alist_config.get('endpoint')
        self.username = alist_config.get('username')
        self.password = alist_config.get('password')
        self.source_base_directories = alist_config.get('source_base_directories', [])
        self.remote_base_directories = alist_config.get('remote_base_directories', [])
        self.local_directories = alist_config.get('local_directories', [])
        self.sync_delete = alist_config.get('sync_delete', False)

        self.debounce_delay = sync_config.get('debounce_delay', 1.0)
        self.file_stable_time = sync_config.get('file_stable_time', 5.0)

        self.subtitle_extensions = set(
            alist_config.get('subtitle_extensions', {'.srt', '.ass', '.sub', '.vtt'}))  # 新增：从配置中获取字幕扩展名，设置默认值

        self.alist = AList(endpoint=self.endpoint)
        self.user = AListUser(username=self.username, rawpwd=self.password)
        self.loop = asyncio.get_event_loop()
        self.observers = []

    async def run(self):
        """运行同步任务"""
        # 登录 AList
        login_success = await self.alist.login(self.user)
        if not login_success:
            logging.error("[ALIST] 登录失败，请检查用户名和密码。")
            return
        logging.info("[ALIST] 登录成功。")

        if (len(self.local_directories) != len(self.source_base_directories) or
                len(self.local_directories) != len(self.remote_base_directories)):
            logging.error("[ALIST] alist 本地目录、源目录、远程目录数量不匹配，请检查配置。")
            return

        for local_dir, source_dir, remote_dir in zip(self.local_directories, self.source_base_directories,
                                                     self.remote_base_directories):
            event_handler = AListSyncHandler(
                alist=self.alist,
                user=self.user,  # 新增：传递用户对象
                remote_base_path=remote_dir,
                local_base_path=local_dir,
                loop=self.loop,
                source_base_directory=source_dir,
                subtitle_extensions=self.subtitle_extensions,  # 传递字幕扩展名
                debounce_delay=self.debounce_delay,
                sync_delete=self.sync_delete,
                file_stable_time=self.file_stable_time
            )

            observer = Observer()
            observer.schedule(event_handler, path=local_dir, recursive=True)
            observer.start()
            logging.info(f"[ALIST] 开始监控本地目录: {local_dir}")
            self.observers.append(observer)

        # 保持运行
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logging.info("[ALIST] 收到取消信号，正在停止所有监控...")
        finally:
            for observer in self.observers:
                observer.stop()
            for observer in self.observers:
                observer.join()
            logging.info("[ALIST] 所有监控器已停止。")

    async def stop(self):
        """停止所有监控器"""
        for observer in self.observers:
            observer.stop()
        for observer in self.observers:
            observer.join()
        logging.info("[ALIST] 所有监控器已停止。")
