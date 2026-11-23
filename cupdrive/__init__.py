"""cupdrive — 把视频节奏翻译成设备动作"""

__version__ = "0.3.2"

# 子模块按需导入：
#   from cupdrive import protocol, safety, ble, tune
# 这里不预先 import，避免 python -m cupdrive.xxx 触发重复导入警告。
__all__ = ["protocol", "safety", "ble", "tune", "play", "audition"]
