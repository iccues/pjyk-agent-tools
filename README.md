# pjyk-admin-cli

`pjyk-admin-cli` 是有希计划（Project Yuki）的本地后台数据管理命令行工具。它通过调用 `pjyk-server` 的管理端 RESTful API（`/api/admin/*`），配合同目录下的 [`SKILL.md`](./SKILL.md) 供 AI Agent（如 Antigravity）按需读取并执行动画数据巡检、智能关联、重复合并、四语标题补全和自动审核。

## 特点

- **零外部依赖**：仅使用 Python 3 标准库（`urllib.request`、`argparse`、`json`），无需额外安装第三方依赖包，即跑即停、无需后台常驻进程。
- **Token 友好**：`dump`、`animes`、`unlinked` 默认输出精简版 JSON（自动过滤冗长的封面图片 URL 等非核心字段），大幅降低大模型上下文消耗。
- **批量执行**：提供 `apply --file <plan.json>` 子命令，支持一次调用批量完成映射绑定、重复动画合并、标题补全和审核状态更新，并支持 `--dry-run` 预演。

## 配置

默认连接本地 `http://localhost:8080`。如需自定义后端地址或配置 OIDC Bearer Token，可复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

环境变量说明：
- `PJYK_ADMIN_BASE_URL`：后端服务地址，默认 `http://localhost:8080`
- `PJYK_ADMIN_TOKEN`：开启 OIDC 鉴权时的 Bearer Token（本地开发环境 `oidc.enabled=false` 时留空即可）

## 常用命令

在仓库根目录下直接运行：

```bash
# 查看待审核动画与未关联映射数量统计
python3 pjyk_admin.py --pretty status
python3 pjyk_admin.py --pretty status --year 2026 --season SPRING

# 导出精简版待审核动画与未关联映射 JSON（供 AI 分析）
python3 pjyk_admin.py dump --status PENDING --year 2026 --season SPRING

# 按关键词搜索动画或未关联映射
python3 pjyk_admin.py --pretty animes --status ALL --keyword "芙莉莲"
python3 pjyk_admin.py --pretty unlinked --keyword "Frieren"

# 单条更新动画标题或审核状态
python3 pjyk_admin.py update-anime 100 --status APPROVED --title-cn "葬送的芙莉莲"

# 合并两个重复的动画（将 source 的所有 Mapping 迁移至 target 并删除 source）
python3 pjyk_admin.py merge-anime <targetAnimeId> <sourceAnimeId>

# 批量执行修改计划（支持 --dry-run）
python3 pjyk_admin.py apply --file /tmp/pjyk_plan.json --dry-run
python3 pjyk_admin.py apply --file /tmp/pjyk_plan.json
```

批处理会先校验整份计划的操作、字段和参数类型。预演只做本地校验，资源是否存在会在执行时检查。正式执行按顺序逐次写入，失败前已完成的修改会保留。默认继续执行后续动作，添加 `--fail-fast` 可在首次失败时停止。重试前请核对 `results` 中的资源 ID、已成功关联或迁移的映射，以及服务端当前状态，按剩余操作生成新计划。
