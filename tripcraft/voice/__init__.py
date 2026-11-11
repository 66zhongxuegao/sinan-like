"""实时语音模块（移植自旧库，已脱离旧 sandbox 结构）。

- language_profiles.py : 语言-国籍-音色配置
- realtime_qwen.py     : Qwen-Omni-Realtime 服务端客户端
"""

from .language_profiles import LANG_NAMES_EN, pick_voice, supported_languages
from .realtime_qwen import (
    QwenRealtimeClient,
    build_scene_voice_instructions,
    resolve_env,
    speak_text,
)

__all__ = [
    "LANG_NAMES_EN",
    "pick_voice",
    "supported_languages",
    "QwenRealtimeClient",
    "build_scene_voice_instructions",
    "resolve_env",
    "speak_text",
]