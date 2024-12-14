import asyncio
import logging
import os
import yaml
from logging.handlers import RotatingFileHandler
from Scripts.sync_to_strm import SyncToStrm
from Scripts.sync_to_alist import SyncToAlist

def setup_logging(log_file: str):
    """配置统一的日志系统"""
    log_dir = os.path.dirname(log_file)
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # 文件日志
    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8')
    file_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y/%m/%d %H:%M:%S')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # 控制台日志
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

def load_config(config_path: str):
    """加载配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

async def main():
    # 加载配置
    config_path = os.getenv('CONFIG_PATH', '/config/config.yaml')
    config = load_config(config_path)

    # 配置日志
    log_file = config.get('sync', {}).get('log_file', '/config/logs/filesync.log')
    setup_logging(log_file)
    logging.info("[MAIN] 日志系统已配置。")

    # 初始化并启动 sync_to_strm
    sync_config = config.get('sync', {})
    sync_to_strm = SyncToStrm(sync_config)
    sync_to_strm.start()

    # 初始化并启动 sync_to_alist
    alist_config = config.get('alist', {})
    sync_to_alist = SyncToAlist(alist_config, sync_config)
    asyncio.create_task(sync_to_alist.run())

    # 保持主线程运行
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logging.info("[MAIN] 收到退出信号，正在停止所有任务...")
        sync_to_strm.stop()
        await sync_to_alist.stop()
        logging.info("[MAIN] 所有任务已停止。")

if __name__ == "__main__":
    asyncio.run(main())
