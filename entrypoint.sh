#!/bin/bash
set -e

# 检查 /config 目录是否存在 config.yaml
if [ ! -f "$CONFIG_PATH" ]; then
    echo "config.yaml not found in /config. Copying default config."
    cp /default_config/config.yaml "$CONFIG_PATH"
fi

# 执行传递给容器的命令
exec "$@"
