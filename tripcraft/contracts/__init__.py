"""TripCraft 数据契约 v0 —— 全系统单一数据源。

分层：
- enums        : 词汇表（状态/维度/掌握度/难度/考点类型...）
- skill_points : 8 维 61 技能点目录
- rubric       : 对齐 Rubric（BARS）
- profile      : 学情画像与能力参数
- evidence     : 证据链
- deliverables : 交付物
- task         : 任务与流程实例
"""

from . import deliverables, enums, evidence, profile, rubric, skill_points, task

__all__ = ["enums", "skill_points", "rubric", "profile", "evidence", "deliverables", "task"]