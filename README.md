# FileSync-AList

**FileSync-AList** 是一款功能强大且灵活的基于 Python 的同步工具，旨在监控本地目录并将更改同步到 AList 服务器。它支持多个同步任务，确保您的文件在不同位置保持最新。此外，它还能为媒体内容生成 `.strm` 文件，便于无缝的媒体管理。

## 目录

- [功能](#功能)
- [Docker部署](#Docker部署)
- [配置](#配置)

## 功能

- **多任务同步**：支持监控和同步多个目录对，每个任务可单独配置。
- **实时监控**：利用 `watchdog` 监控文件系统事件，如文件和目录的创建、修改、删除和移动。
- **AList 集成**：连接到 AList 服务器，执行上传、删除和重命名文件及目录等操作。
- **.strm 文件生成**：自动为媒体文件生成 `.strm` 文件，便于媒体流管理。
- **初始全量同步**：可选地在启动时执行初始全量同步，确保所有现有文件正确镜像。
- **防抖机制**：实现防抖延迟，防止在快速文件更改期间执行冗余的同步操作。
- **日志记录**：全面的日志记录和轮转功能，跟踪同步活动并排查问题。
- **高度可配置**：通过 YAML 配置文件高度自定义，同步行为可根据需求调整。

## Docker部署
```bash
docker run -d \
  --name filesync-alist \
  -v /path/to/config/config.yaml:/config/config.yaml \
  -v /path/to/config/logs:/config/logs \
  -v /media/source1:/media/source1 \
  -v /media/target1:/media/target1 \
  -v /media/source2:/media/source2 \
  -v /media/target2:/media/target2 \
  -e LOG_FILE=/config/logs/sync.log \
  smartzsw/filesync-alist:latest
```
## 配置
同步行为通过 config.yaml 文件进行控制。该文件定义了与 AList 服务器的连接详情、需要监控和同步的目录、媒体文件类型以及其他同步选项。
```python
# config.yaml

alist:
  endpoint: "http://your-alist-endpoint"          # AList 服务器 URL
  username: "your-username"                      # AList 用户名
  password: "your-secure-password"               # AList 密码
  source_base_directories:
    - "/path/to/source1_base"                    # 同步任务 1 的源基础目录
    - "/path/to/source2_base"                    # 同步任务 2 的源基础目录
    # 根据需要添加更多基础目录
  remote_base_directories:
    - "/path/to/remote1_base"                    # 同步任务 1 的远程基础目录
    - "/path/to/remote2_base"                    # 同步任务 2 的远程基础目录
    # 根据需要添加更多远程基础目录
  local_directories:
    - "/path/to/local1_base"                     # 同步任务 1 的本地基础目录
    - "/path/to/local2_base"                     # 同步任务 2 的本地基础目录
    # 根据需要添加更多本地基础目录
  sync_delete: false                             # 启用或禁用删除同步

sync:
  sync_directories:
    - source_dir: "/path/to/source1"             # 同步任务 1 的源目录
      target_dir: "/path/to/target1"             # 同步任务 1 的目标目录
      media_prefix: "prefix1"                     # 同步任务 1 的媒体前缀
    - source_dir: "/path/to/source2"             # 同步任务 2 的源目录
      target_dir: "/path/to/target2"             # 同步任务 2 的目标目录
      media_prefix: "prefix2"                     # 同步任务 2 的媒体前缀
    # 根据需要添加更多同步任务
  media_file_types:
    - "*.mp4"
    - "*.mkv"
    - "*.ts"
    - "*.iso"
    - "*.rmvb"
    - "*.avi"
    - "*.mov"
    - "*.mpeg"
    - "*.mpg"
    - "*.wmv"
    - "*.3gp"
    - "*.asf"
    - "*.m4v"
    - "*.flv"
    - "*.m2ts"
    - "*.strm"
    - "*.tp"
    - "*.f4v"
  ignore_file_types:
    - ".mp"
  overwrite_existing: false                       # 是否覆盖目标中的现有文件
  enable_cleanup: false                           # 是否启用目标中已删除文件的清理
  full_sync_on_startup: true                      # 启动时是否执行初始全量同步
  use_direct_link: false                           # 是否为 .strm 文件使用直接链接
  base_url: "http://your-base-url"                # 生成 .strm 文件链接的基础 URL
  debounce_delay: 120                             # 防抖延迟时间（秒）
```

## 本项目遵循以下开源许可证：

- **MIT 许可证**：适用于本项目的所有代码。
- **LGPL 2.1 许可证**：适用于本项目使用的 [AList3SDK](https://github.com/moyanj/AList3SDK) 库。

### 许可证详情

- 本项目代码使用 **MIT 许可证**，可以自由使用、复制、修改、合并、发布、分发、再授权和销售。
- 本项目使用的 **AList3SDK** 库遵循 **LGPL 2.1 许可证**，该库的使用和分发需遵循相应的开源条款。具体许可证内容请参见 [LGPL 2.1 官方文档](https://www.gnu.org/licenses/lgpl-2.1.html)。
