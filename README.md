# FileSync-AList

- **本自动化脚本主要针对于自用，如有其他使用场景纯属巧合。**
- **本人使用场景针对于MP媒体库自动化整理工具，硬链接整理方式进行使用**

**FileSync-AList** 是一款基于 Python 的灵活同步工具，专为实时监控本地目录并将文件变更同步到 AList 服务器而设计。它支持多个同步任务，每个任务可以单独配置，确保不同位置的文件保持最新。除此之外，FileSync-AList 还能自动为媒体文件生成 `.strm` 文件，优化媒体内容的管理与播放。通过高度可配置的 `YAML` 文件，用户可以根据具体需求自定义同步行为，提供更强大的操作灵活性。
## 目录

- [功能](#功能)
- [Docker部署](#Docker部署)
- [配置](#配置)

## 功能

- **多任务同步**：支持监控和同步多个目录对，每个任务可单独配置。
- **实时监控**：将源文件实时同步到目标的文件夹中，包括实时同步到alist远端存储。
- **AList 集成**：连接到 AList 服务器，实时监控执行上传、删除和重命名文件及目录等操作。
- **strm 文件生成**：自动为媒体文件生成 `.strm` 文件到目标文件夹。
- **初始全量同步**：（可选）启动时执行初始全量同步，确保所有现有文件的正确。
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

```yaml
# config.yaml
alist:
  endpoint: "http://your-alist-endpoint"
  username: "your-username"
  password: "your-secure-password"
  source_base_directories:
    - "/path/to/source1_base"
    - "/path/to/source2_base"
    # 添加更多的 base directories 如需
  remote_base_directories:
    - "/path/to/remote1_base"
    - "/path/to/remote2_base"
    # 添加更多的 base directories 如需
  local_directories:
    - "/path/to/local1_base"
    - "/path/to/local2_base"
    # 添加更多的 base directories 如需
  sync_delete: false

sync:
  sync_directories:
    - source_dir: "/path/to/source1"
      target_dir: "/path/to/target1"
      media_prefix: "prefix1"
    - source_dir: "/path/to/source2"
      target_dir: "/path/to/target2"
      media_prefix: "prefix2"
    # 添加更多的同步任务如需
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
  overwrite_existing: false
  enable_cleanup: false
  full_sync_on_startup: true
  use_direct_link: true
  base_url: "http://your-base-url"
```

## 本项目遵循以下开源许可证：

- **LGPL 2.1 许可证**：适用于本项目使用的 [AList3SDK](https://github.com/moyanj/AList3SDK) 库。
