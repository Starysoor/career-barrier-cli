# career-barrier-cli

> 生涯闯关（全国大学生职业规划大赛）自动化命令行工具

[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)]()

---

## ⚠️ 免责声明（请先阅读）

- 本项目为**非官方**第三方工具，与赛事主办方、学信网及任何高校**无任何关联**。
- 仅供**学习交流**与完成学校布置的练习任务使用。**请勿用于正式参赛、评奖、排名或任何商业用途。**
- 自动化操作可能违反平台用户协议；使用前请自行确认所在学校的要求与风险，**一切后果由使用者自行承担**。
- 本项目**不收集、不上传**任何用户数据。登录凭据仅保存在本地 `config.json`，请勿提交到代码仓库。

## 功能

| 能力 | 说明 |
|---|---|
| 一键完成关卡 | 依次完成全部 8 个可提交关卡，支持中途失败续跑 |
| 真实结果校验 | 每关结束**回读服务端**核对，输出真实完成情况 |
| 三种答案模式 | 内置模板 / AI 生成（任意 OpenAI 兼容接口）/ 快速随机 |
| 个性化 | 专业、目标职业、兴趣、经历注入生成内容 |
| 真 PDF 附件 | 内置 PDF 排版引擎，按题目生成可正常打开的招聘简章、访谈报告、实践报告、求职计划书 |
| 多账号 | 支持切换账号，以浏览器实际登录态为准 |
| 覆盖重刷 | 替换此前提交的内容（仅限平台开放覆盖通道的部分） |

## 环境要求

- Python 3.8 及以上（**无需 pip 安装任何依赖**）
- Windows / macOS / Linux
- 本机安装 Edge 或 Chrome（用于登录，无需额外配置）

## 快速开始

```bash
# 1. 运行（首次会引导配置）
python 刷生涯闯关.py

# 2. 选择登录方式：脚本会弹出独立浏览器窗口，直接在内登录即可
# 3. 确认显示的账号无误 → 回车开始
# 4. 跑完用只读工具核对真实进度
python 查看进度.py
```

> 首次弹出浏览器时若未安装脚本专用配置，会提示登录；登录态保存在 `.browser_profile/`）。

## 命令行参数

| 参数 | 说明 |
|---|---|
| （无） | 常规刷，自动跳过已完成的关卡 |
| `--overwrite` | 覆盖重刷，用当前模式重新生成可覆盖的内容 |
| `--only 7,8` | 只执行指定关卡（序号 1–8） |
| `--switch-account` | 清空登录态，切换为其他账号 |
| `--fresh` | 忽略已保存配置，重新进入配置向导 |
| `--dry` | 离线自检，不联网、不写数据 |

## 配置说明

首次运行会在同目录生成 `config.json`（**含登录凭据**）：

```jsonc
{
  "mode": "ai",                  // template | ai | random
  "ai": { "base_url": "...", "api_key": "...", "model": "..." },
  "profile": {
    "major": "人工智能",          // 影响生成内容的专业方向
    "job1": "软件开发工程师",      // 目标职业
    "interests": "...",           // 兴趣
    "highlights": "..."           // 经历，用于成就故事取材
  },
  "overrides": {}                // 字段级覆盖：{"b1.retrospect": "自写内容"}
}
```

### AI 接口

兼容任意 OpenAI 格式接口，内置常用平台预设：

| 平台 | Base URL | 推荐模型 |
|---|---|---|
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash`（免费） |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| 本地 Ollama | `http://localhost:11434/v1` | 任意 |

AI 调用失败会自动回退到内置模板，不会中断流程。

## 项目结构

```
.
├── 刷生涯闯关.py      # 主程序（单文件，含 PDF 引擎与登录模块）
├── 查看进度.py        # 只读进度核对工具
├── LICENSE           # MIT
├── NOTICE.md         # 第三方来源与商标说明
├── README.md
└── .gitignore        # 已排除 config.json / .browser_profile 等
```

## 常见问题

**Q：提示 Token 无效或账号不对？**
A：脚本以浏览器当前登录态为准。运行 `python 刷生涯闯关.py --switch-account` 可清空登录态重新登录。

**Q：某关一直失败？**
A：查看打印的原始接口报错。平台对部分字段有长度校验（如"预期结果至少 50 字符"）；若返回 500「响应超时」，通常是该账号该关数据异常，网页同样会空白，需联系平台客服处理。

**Q：附件 PDF 在网页里预览空白？**
A：平台的在线预览服务本身不可用（对所有 PDF 均报错）。下载到本地用任何 PDF 阅读器打开正常。

**Q：进度显示 ✅ 但平台显示未完成？**
A：脚本校验的是接口回读数据。若不一致，请刷新页面或联系客服确认平台侧状态。

## 贡献

欢迎 Issue 与 PR。提交前请确保：

1. 不包含任何真实账号、Token、API Key、手机号等个人信息；
2. 不提交 `.browser_profile/`、`config.json` 等本地文件；
3. `python 刷生涯闯关.py --dry` 通过。

## 致谢

本项目的**接口协议层**参考了以下 MIT 许可的开源项目（详见 [NOTICE.md](NOTICE.md)）：

- [职业规划大赛闯关助手](https://scriptcat.org/zh-CN/script-show-page/4626)（作者：毫厘 / proudly，MIT）
  —— 本项目使用的 56 个平台接口中，有 49 个源自该项目；各关卡的提交顺序、字段名、字数要求亦参考其实现
- [生涯闯关助手（睡衣宝宝改版）](https://scriptcat.org/zh-CN/script-show-page/4732)（作者：睡衣宝宝，原作者：毫厘，MIT）
  —— AI 生成答案的思路参考其改版尝试

**未借用部分**：全部代码为 Python 独立重写（与原项目逐行比对重合 0 行）；中文语料、PDF 排版引擎、
CDP 登录方案、服务端回读校验、多账号切换。

以上项目均允许再分发，本项目已按要求保留署名与本声明。

## 许可证

[MIT](LICENSE) © 2026 生涯闯关助手 contributors
