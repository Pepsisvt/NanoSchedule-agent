# 日程助手 - 基于 AI Agent 的个人日程管理助手

> 开源技术与应用 课程项目

## 项目简介

基于 [nanobot](https://github.com/HKUDS/nanobot)（HKUDS 开源 AI Agent 框架）二次开发，构建一个能够在移动端使用的 AI 日程管理助手。

**核心能力**：用户通过自然语言与 Agent 对话，Agent 自主调用日程管理工具完成创建、查询、修改、删除等操作，并支持定时提醒推送。

## 架构设计

```
用户（手机浏览器 / PWA）
        ↓ HTTP + WebSocket
    Web 前端（PWA）
        ↓ WebSocket:8765
    nanobot Gateway（消息路由）
        ↓
    Agent 核心引擎（ReAct 循环）
        ↓ Function Calling
    ┌─────────────────────────┐
    │  自定义工具 (8个)         │
    │  ├─ create_event        │
    │  ├─ query_events        │
    │  ├─ update_event        │
    │  ├─ delete_event        │
    │  ├─ setup_reminder      │
    │  ├─ list_reminders      │
    │  ├─ cancel_reminder     │
    │  └─ upcoming_reminders  │
    └──────────┬──────────────┘
               ↓
    SQLite 数据库（日程 + 提醒）
```

## Agent 工作流程

```
用户: "明天下午3点开会，提前10分钟提醒我"
        ↓
Agent: Thought → 需要1)创建日程 2)设置提醒
        ↓
Action: create_event(title="开会", start_time="2026-06-25T15:00:00")
Observation: ✅ 日程已创建 (ID: 1)
        ↓
Action: setup_reminder(message="开会还有10分钟", remind_at="2026-06-25T14:50:00")
Observation: ✅ 提醒已设置 (ID: 1)
        ↓
Response: 已为你创建明天下午3点的会议，并设置14:50提醒
```

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| Agent 框架 | nanobot v0.2.2 | HKUDS 开源个人 AI Agent |
| 大模型 | DeepSeek API | 兼容 OpenAI Function Calling |
| 后端语言 | Python 3.12 | 工具开发 + 服务 |
| 数据库 | SQLite | 日程和提醒存储 |
| 定时任务 | APScheduler | 提醒触发 |
| 前端 | PWA (HTML/JS) | 移动端安装到桌面 |
| 通信 | WebSocket | 实时消息推送 |

## 项目结构

```
开源技术与应用/
├── nanobot_calendar/          # 自定义工具包
│   ├── __init__.py
│   ├── db.py                  # SQLite 数据库层
│   ├── calendar_tools.py      # 日程 CRUD 工具 (4个)
│   └── reminder_tools.py      # 提醒管理工具 (4个)
├── webui/                     # PWA 前端
│   ├── index.html             # 移动端聊天界面
│   ├── manifest.json          # PWA 配置
│   └── sw.js                  # Service Worker
├── workspace/                 # nanobot 工作区
│   ├── SOUL.md               # Agent 行为配置
│   ├── AGENTS.md             # Agent 工作流
│   └── calendar.db           # 日程数据库
├── serve_pwa.py              # PWA 静态服务器
├── setup.py                  # 包安装配置
├── pyproject.toml
├── venv/                     # Python 虚拟环境
└── README.md
```

## 快速开始

### 1. 环境要求

- Python 3.11+
- DeepSeek API Key（[platform.deepseek.com](https://platform.deepseek.com) 注册获取）

### 2. 安装

```bash
# 创建虚拟环境
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Mac/Linux

# 安装 nanobot
pip install nanobot-ai

# 安装自定义工具包
pip install -e .

# 配置 API Key
# 编辑 ~/.nanobot/config.json，将 deepseek.api_key 设为你的真实 Key
```

### 3. 初始化数据库

```bash
python -c "from nanobot_calendar import db; db.init_db()"
```

### 4. 启动服务

```bash
# 终端1：启动 nanobot Gateway（WebSocket 服务）
nanobot gateway

# 终端2：启动 PWA 前端服务器
python serve_pwa.py
```

### 5. 访问

- **手机浏览器**: `http://<电脑IP>:3000`
- **添加到桌面**: 浏览器菜单 → 添加到主屏幕

### 6. 飞书机器人连接（可选）

本应用支持通过飞书接收提醒和与 Agent 对话。

**step 1**：在[飞书开放平台](https://open.feishu.cn/)创建企业自建应用。

**step 2**：获取 App ID 和 App Secret，编辑 `~/.nanobot/config.json`：

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "你的 App ID",
      "appSecret": "你的 App Secret",
      "domain": "feishu"
    }
  }
}
```

**step 3**：在飞书开放平台配置事件订阅：
- 请求网址: `http://<你的公网IP>:18790/feishu/event`
- 添加"消息与群组"相关权限

**step 4**：重启 Gateway 即可在飞书与 Agent 对话，定时提醒也会推送到飞书。

> 💡 飞书和网页端数据互通，在飞书创建的日程和提醒，网页端同样可见。

## 演示示例

```bash
# 命令行模式
nanobot agent -m "明天下午3点开会，地点A101，提前10分钟提醒我"
nanobot agent -m "我这周有什么安排"
nanobot agent -m "把上次那个会议改到周四下午4点"
nanobot agent -m "取消ID为3的提醒"
```

## 创新点

1. **基于成熟开源项目二次开发** - 体现了"开源技术应用"课程主题
2. **完整的 Agent 决策循环** - ReAct 模式：感知→规划→执行→反馈
3. **多工具协同调用** - Agent 自动选择合适的工具组合完成任务
4. **移动端 PWA** - 手机浏览器打开，可安装到桌面
5. **实用价值高** - 可作为日常使用的个人助理

## 与 nanobot (HKUDS) 的关系

本项目基于 nanobot 的 Agent 框架进行二次开发：
- 保留了 nanobot 的 Agent 循环、多通道、记忆系统
- 新增了 8 个日程管理工具
- 定制了 Agent 行为配置（SOUL.md）
- 添加了 PWA 移动端界面

## 许可证

MIT
