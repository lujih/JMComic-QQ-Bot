# Contributing

## 开发

请先阅读 [AGENTS.md](AGENTS.md) 了解架构、已踩的坑和编码约定。

## PR 流程

1. Fork 本仓库，从 `dev` 分支创建功能分支
2. 遵循现有代码风格（详见 AGENTS.md 编码规范）
3. PR 目标分支：**`dev`**（禁止直接推 `main`）
4. HF Spaces 自动部署 `main` 分支

## 本地调试

```bash
pip install -r requirements.txt
python bot.py
```

需安装 NapCatQQ 或 mock 环境。
