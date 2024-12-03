import asyncio
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from alist import AList, AListUser  # 确保正确导入 AList SDK

class AListSyncHandler(FileSystemEventHandler):
    def __init__(self, alist: AList, remote_path: str, local_base_path: str, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.alist = alist
        self.remote_path = remote_path
        self.local_base_path = local_base_path
        self.loop = loop  # 保存主线程的事件循环

    def get_remote_path(self, src_path):
        # 计算相对于监控目录的相对路径，并拼接到远程路径
        relative_path = os.path.relpath(src_path, self.local_base_path)
        return os.path.join(self.remote_path, relative_path).replace("\\", "/")  # 确保使用正斜杠

    async def handle_created_or_modified(self, event):
        if event.is_directory:
            # 创建文件夹
            remote_dir = self.get_remote_path(event.src_path)
            success = await self.alist.mkdir(remote_dir)
            if success:
                print(f"文件夹创建成功: {remote_dir}")
            else:
                print(f"文件夹创建失败: {remote_dir}")
        else:
            # 上传文件
            remote_file = self.get_remote_path(event.src_path)
            success = await self.alist.upload(remote_file, event.src_path)
            if success:
                print(f"文件上传成功: {remote_file}")
            else:
                print(f"文件上传失败: {remote_file}")

    async def handle_deleted(self, event):
        remote_path = self.get_remote_path(event.src_path)
        if event.is_directory:
            success = await self.alist.remove_folder(remote_path)
            if success:
                print(f"文件夹删除成功: {remote_path}")
            else:
                print(f"文件夹删除失败: {remote_path}")
        else:
            success = await self.alist.remove(remote_path)
            if success:
                print(f"文件删除成功: {remote_path}")
            else:
                print(f"文件删除失败: {remote_path}")

    async def handle_moved(self, event):
        src_remote = self.get_remote_path(event.src_path)
        dest_remote = self.get_remote_path(event.dest_path)
        success = await self.alist.rename(src_remote, dest_remote)
        if success:
            print(f"重命名成功: {src_remote} -> {dest_remote}")
        else:
            print(f"重命名失败: {src_remote} -> {dest_remote}")

    def on_created(self, event):
        asyncio.run_coroutine_threadsafe(self.handle_created_or_modified(event), self.loop)

    def on_modified(self, event):
        asyncio.run_coroutine_threadsafe(self.handle_created_or_modified(event), self.loop)

    def on_deleted(self, event):
        asyncio.run_coroutine_threadsafe(self.handle_deleted(event), self.loop)

    def on_moved(self, event):
        asyncio.run_coroutine_threadsafe(self.handle_moved(event), self.loop)

async def main():
    # 配置参数
    endpoint = "https://your-alist-endpoint.com"  # AList 服务器地址
    username = "your_username"  # AList 用户名
    password = "your_password"  # AList 密码
    local_directory = "/path/on/"  # 本地监控目录
    remote_directory = "/path/on/alist"  # AList 服务器上的目标目录

    # 初始化 AList 实例
    alist = AList(endpoint=endpoint)
    user = AListUser(username=username, rawpwd=password)
    login_success = await alist.login(user)
    if not login_success:
        print("登录失败，请检查用户名和密码。")
        return
    print("登录成功。")

    # 获取当前事件循环
    loop = asyncio.get_running_loop()

    # 初始化事件处理器
    event_handler = AListSyncHandler(alist, remote_directory, local_directory, loop)

    # 设置观察者
    observer = Observer()
    observer.schedule(event_handler, path=local_directory, recursive=True)
    observer.start()
    print(f"开始监控本地目录: {local_directory}")

    try:
        while True:
            await asyncio.sleep(1)  # 保持主线程运行
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    asyncio.run(main())
