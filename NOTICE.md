# 第三方来源与致谢

本项目的**接口协议层参考了以下两个 MIT 许可的开源项目**，特此如实说明并致谢。

| 项目 | 作者 | 来源 | 许可 |
|---|---|---|---|
| 职业规划大赛闯关助手 | 毫厘 / proudly | [ScriptCat #4626](https://scriptcat.org/zh-CN/script-show-page/4626) | MIT |
| 生涯闯关助手（睡衣宝宝改版） | 睡衣宝宝（原作者：毫厘） | [ScriptCat #4732](https://scriptcat.org/zh-CN/script-show-page/4732) | MIT |

---

## 一、具体借鉴了什么

### 1. 接口路径与调用时序（主要借鉴，来自 #4626）

本项目使用的 56 个平台接口中，**有 49 个（约 88%）同样出现在 #4626 中**。具体包括：

- 各关卡接口前缀与路径，如 `/barrier-firsts/new-knowledge`、`/barrier-seconds/create-major`、
  `/barrier-thirds/create-profession`、`/barrier-fifths/create-career-interest`、
  `/barrier-sixths/create-job-info-tidy`、`/barrier-sevenths/skill-explore-list`、
  `/barrier-eighths/create-skill-promote-way`、`/barrier-ninths/create-comprehend` 等
- 每个关卡的**子任务提交顺序**（新知 → 笃行 → 领悟）
- 提交请求中的**字段名**，如 `major_course`、`tunnel`、`interviewer`、`practice_mode`、
  `identity_change`、`favorite_major`、`new_know`、`behavior`、`expect_result`、`need_resource`
- 各输入框的**字数要求**（如 100–300、210–300、80–95、110–150、55–95、100–490 字）
- 若干业务规则：兴趣测评需提交 3 个真实类型 + 3 个空占位位；
  技能盘点采用「每次取一个未处理项→提交→返回继续」的循环模式；
  重复提交类错误（"请勿重复点击""已有分析数据"）可安全忽略

### 2. AI 生成思路（来自 #4732）

「用大模型按题目要求生成答案」这一思路参考了 #4732 的改版尝试。

### 3. 历史上曾复用的资源（现已移除）

项目早期版本曾直接复用 #4626 中内嵌的**空白 PDF base64 数据**作为上传占位。
该实现已在当前版本中**完全删除**，改为由本项目自行实现的 PDF 排版引擎生成真实文档。
当前仓库中**不含**任何来自原项目的二进制资源。

---

## 二、没有借鉴、完全独立实现的部分

| 模块 | 说明 |
|---|---|
| 全部源代码 | 本项目为 Python 重写，与原项目 JavaScript 代码不同 |
| 中文文本语料 | 370 段文案为独立撰写；与原项目重合的仅 2 条极短功能性提示（"未能获取兴趣选项""所有榜样均已分析，跳过。"） |
| PDF 排版引擎 | 自行实现的 PDF 对象写入与中文折行排版（原项目上传空白占位文件） |
| 登录方案 | 基于 CDP 调试协议读取浏览器登录态（原项目为拦截 XHR Authorization 头） |
| 服务端回读校验 | 每关结束回读接口核对真实结果，未借鉴 |
| 多账号切换 / 字段级覆盖 / 单文件零依赖架构 | 未借鉴 |
| 额外 7 个接口 | 如 `career-retrospect-view`、`comprehend-view`、`practice-record-list`、`anchored-job-direction-list` 等，由本项目独立抓包归纳 |

---

## 三、许可合规

- 上述两个项目均以 **MIT 许可**发布，允许使用、修改、再分发与商业使用，
  条件是**保留版权声明与许可声明**。本项目：
  1. 在本文件与 `README.md` 中保留原作者署名与项目链接；
  2. 以 [MIT](LICENSE) 许可发布本项目；
  3. 未使用原作者名义进行任何形式的背书宣传。
- 
---

## 四、商标与关联声明

「学信网」「全国大学生职业规划大赛」等名称与标识归其权利人所有。
本项目为**非官方、非商业**的第三方工具，与赛事主办方、学信网及任何高校**无任何关联**，
不使用其商标作为项目名称、图标或宣传标识。

---

## 五、免责

本项目按「现状」提供，不附带任何明示或默示担保。
自动化操作可能违反平台用户协议与学校规定，使用者应自行评估并承担全部后果。
请勿用于正式参赛、评奖或商业用途。
