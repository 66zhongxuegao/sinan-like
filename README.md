# 司南礼客

面向入境游定制师培训的个性化生成与多智能体协同决策系统。

项目采用 FastAPI 后端、Vue 3 + Vite 前端与 Electron 桌面壳，覆盖学情诊断、个性化学习、订单实战、交付物生成、证据核验、评分画像与经验沉淀等流程。

## 目录结构

- `tripcraft/`：后端服务、智能体、语音桥接、业务服务与数据存储
- `frontend/`：Vue 3 前端与 Electron 桌面应用
- `tests/`：后端测试
- `scripts/`：启动、验收、演示与维护脚本
- `data/`：领域知识与标准案例
- `docs/`：项目设计、状态与决策记录
- `_交接文档/`：安装、演示、配置与验收材料

## 环境要求

- Python 3.11+
- Node.js 22.12+
- npm

## 快速开始

1. 参照 `_交接文档/配置示例/环境变量示例.txt` 创建本地 `local.env`。真实密钥不会提交到 Git。
2. 新机器首次运行：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\_交接文档\首次安装与适配.ps1
   ```

3. 普通训练模式：双击 `司南礼客桌面版.bat`。
4. 固定案例演示模式：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\启动标准演示.ps1
   ```

更完整的启动说明、演示流程与限制说明见 `00先读我.txt` 和 `_交接文档/`。
