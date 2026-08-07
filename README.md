# 兔兔 - AmiyaBot 群聊日报插件

每天定时（默认 **23:00**，可在控制台修改）自动生成一份当天的群聊日常分析报告并发到群里，包含基础统计、热门话题、群友称号和群圣经。

> 插件 id：`siwu-daily-report`　当前版本：`1.0.0`

## 报告长什么样

```
🎯 群聊日常分析报告
📅 2026年08月07日

📊 基础统计
• 消息总数: 993
• 参与人数: 31
• 总字符数: 49429
• 表情数量: 50
• 最活跃时段: 18:00-19:00

💬 热门话题
1. 外企编程与AI应用
   参与者: Ivy Xu、あやは、奥古斯都康斯坦丁大妖精、Coloryr、观星
   讨论了如何在外企进行编程工作，以及AI在编程领域的应用……

🏆 群友称号
• 阿米娅 - 沉默终结者 (INTJ)
   发言频率低，但每次发言平均字数较多，可能是一个深思熟虑的人，适合「沉默终结者」称号。

💬 群圣经
1. "结果：桑吉亚夫 胜（win）" —— 阿米娅
   这句话看似简单，实则充满反差感和冲击力……
```

## 工作原理

1. **记录**：插件监听群消息，把每个群当天的消息（发言者、昵称、内容、表情、时间）写入 `data/siwu_daily_report.db`
2. **触发**：内置定时任务每分钟检查一次，到达 `report_time`（默认 23:00）后，对当天有消息的每个群生成日报并主动推送
3. **生成**：
   - **基础统计**（消息总数/参与人数/总字符数/表情数量/最活跃时段）全部本地计算，准确可靠
   - **热门话题 / 群友称号 / 群圣经** 优先调用 LLM（OpenAI 兼容接口）分析生成
   - 未配置 LLM 或调用失败时，自动回退到本地规则版本（jieba 关键词话题、行为特征称号、热度金句），**日报始终能发出来**

## 控制台配置

安装后可在兔兔控制台修改（对应 `config_default.yaml` / `jsonSchema.json`）：

| 配置项 | 说明 | 默认 |
| --- | --- | --- |
| `report_enabled` | 插件总开关 | `true` |
| `report_time` | 每天生成日报的时间（HH:MM） | `23:00` |
| `report_llm_api_key` | LLM API Key，留空则用本地规则生成 | 空 |
| `report_llm_base_url` | OpenAI 兼容接口地址 | `https://api.deepseek.com` |
| `report_llm_model` | 模型名 | `deepseek-chat` |
| `report_topics_count` | 热门话题数量 | `5` |
| `report_titles_count` | 群友称号数量 | `6` |
| `report_bible_count` | 群圣经条数 | `3` |
| `report_max_transcript` | 传给 LLM 的对话样本上限 | `150` |
| `report_retention_days` | 历史消息保留天数（自动清理） | `7` |
| `report_debug_log` | 调试日志 | `true` |

> 提示：想立刻看效果，可临时把 `report_time` 改成当前时间下一分钟（如 `12:01`），或配置好 LLM 后等自然到点。LLM 建议填 DeepSeek Key；任意 OpenAI 兼容服务均可。

## 依赖

- 无额外 Python 依赖（SQLite 使用标准库；`jieba` 由 AmiyaBot 自带）
- 多账号（MultipleAccounts）场景下，会按消息来源账号分别推送到对应群

## 安装方法

1. 把 `siwu-daily-report-1.0.zip` 放到 `plugins/` 目录下
2. 重启兔兔（或在控制台重载插件）即可自动加载
3. 在控制台为需要日报的群启用本插件

### 修改后重新打包

```bash
python pluginsServer/siwu-daily-report-1_0/build.py
```

## 版本记录

每次发版在表格最上方追加一行。

| 版本 | 更新内容 |
|---|---|
| `1.0.0` | 初始版本：每日定时（默认 23:00）生成群聊日报；本地统计 + 可选 LLM 分析，未配置自动降级；SQLite 记录、按保留天数自动清理 |
