# 通用定时任务调度插件

一个功能强大的通用定时任务调度插件，支持多种调度方式和丰富的动作类型。

## 🚀 功能特性

### 调度方式
- **Cron表达式**: 支持标准的5字段Cron格式，如 `0 9 * * *` (每天9点)
- **固定间隔**: 按秒/分钟/小时间隔执行，如每5分钟、每小时
- **一次性任务**: 指定具体时间执行一次
- **手动触发**: 只能通过命令手动执行

### 动作类型
- **send_message**: 发送消息到用户、群组或广播
- **api_call**: 调用HTTP API接口
- **file_operation**: 文件操作(备份、删除、移动、复制、清理)
- **command**: 执行系统命令(需要安全配置)

### 高级功能
- **条件执行**: 支持时间范围、星期、变量条件等
- **变量模板**: 动态变量替换，如 `{{timestamp}}`、`{{date}}`
- **任务依赖**: 任务间可设置依赖关系
- **错误处理**: 自动重试、失败通知、异常恢复
- **任务分组**: 支持任务分组管理

## 📋 使用指南

### 基本命令
```
/task list [group]           # 列出所有任务
/task info <task_id>         # 查看任务详情
/task run <task_id>          # 手动执行任务
/task enable <task_id>       # 启用任务
/task disable <task_id>      # 禁用任务
/task status                 # 查看调度器状态
/task help                   # 显示帮助
```

### 配置任务

任务配置保存在 `data/scheduler/tasks.json` 文件中。基本格式：

```json
{
  "tasks": [
    {
      "id": "my_task",
      "name": "我的任务",
      "description": "任务描述",
      "enabled": true,
      "schedule": {
        "type": "cron",
        "config": {
          "expression": "0 9 * * *"
        },
        "timezone": "Asia/Shanghai",
        "enabled": true
      },
      "actions": [
        {
          "type": "send_message",
          "config": {
            "target_type": "group",
            "target_id": "123456789",
            "message": "🌅 早上好！今天是{{date}}"
          },
          "conditions": []
        }
      ],
      "group": "reminders",
      "priority": 1,
      "retry_count": 3,
      "on_failure": "log"
    }
  ]
}
```

## 🔧 配置示例

### 1. 每日提醒任务
```json
{
  "id": "daily_reminder",
  "name": "每日提醒",
  "schedule": {
    "type": "cron",
    "config": {"expression": "0 9 * * *"}
  },
  "actions": [
    {
      "type": "send_message",
      "config": {
        "target_type": "group",
        "target_id": "群组ID",
        "message": "🌅 早上好！今天是{{date}}，星期{{weekday}}"
      }
    }
  ]
}
```

### 2. 系统备份任务
```json
{
  "id": "system_backup",
  "name": "系统备份",
  "schedule": {
    "type": "cron",
    "config": {"expression": "0 2 * * 0"}
  },
  "actions": [
    {
      "type": "file_operation",
      "config": {
        "operation": "backup",
        "source_path": "./data",
        "target_path": "./backups/data_{{timestamp}}.zip",
        "compress": true
      }
    }
  ]
}
```

### 3. API监控任务
```json
{
  "id": "api_monitor",
  "name": "API监控",
  "schedule": {
    "type": "interval",
    "config": {"seconds": 300}
  },
  "actions": [
    {
      "type": "api_call",
      "config": {
        "method": "GET",
        "url": "https://api.example.com/health",
        "timeout": 10
      }
    },
    {
      "type": "send_message",
      "config": {
        "target_type": "admin",
        "target_id": "管理员ID",
        "message": "⚠️ API异常: {{api_url}}"
      },
      "conditions": [
        {
          "type": "previous_action_failed",
          "config": {}
        }
      ]
    }
  ]
}
```

## 📅 Cron表达式说明

格式：`分 时 日 月 周`

| 字段 | 范围 | 特殊字符 |
|------|------|----------|
| 分钟 | 0-59 | * , - / |
| 小时 | 0-23 | * , - / |
| 日期 | 1-31 | * , - / |
| 月份 | 1-12 | * , - / |
| 星期 | 0-6  | * , - / |

### 常用示例
- `0 9 * * *` - 每天上午9点
- `*/30 * * * *` - 每30分钟
- `0 0 1 * *` - 每月1日
- `0 8 * * 1-5` - 工作日上午8点
- `@daily` - 每天午夜
- `@hourly` - 每小时

## 🔧 变量系统

### 系统变量
- `{{timestamp}}` - 当前时间戳
- `{{date}}` - 当前日期 (YYYY-MM-DD)
- `{{time}}` - 当前时间 (HH:MM:SS)
- `{{datetime}}` - 完整日期时间
- `{{weekday}}` - 星期几
- `{{random_id}}` - 随机ID
- `{{year}}`, `{{month}}`, `{{day}}` - 年、月、日

### 执行上下文变量
- `{{api_url}}` - API调用的URL
- `{{status_code}}` - HTTP状态码
- `{{backup_file}}` - 备份文件路径
- `{{backup_size}}` - 备份文件大小

## ⚙️ 条件执行

支持多种执行条件：

### 时间条件
```json
{
  "type": "time_range",
  "config": {
    "start_time": "08:00",
    "end_time": "22:00"
  }
}
```

### 星期条件
```json
{
  "type": "weekday",
  "config": {
    "weekdays": [1, 2, 3, 4, 5]
  }
}
```

### 前置动作条件
```json
{
  "type": "previous_action_success",
  "config": {}
}
```

## 🛡️ 安全设置

### 命令执行安全
- 默认禁用系统命令执行
- 支持安全命令白名单
- 自动检测危险命令模式

### 文件操作安全
- 路径验证和限制
- 原子操作保证数据安全
- 自动备份重要文件

## 📊 监控和日志

### 任务统计
- 执行次数和成功率
- 平均执行时间
- 失败次数和错误日志

### 调度器状态
- 运行中任务数量
- 系统资源使用情况
- 任务队列状态

## 🔧 故障排除

### 常见问题

1. **任务不执行**
   - 检查任务是否启用
   - 验证Cron表达式格式
   - 查看调度器状态

2. **Cron表达式错误**
   - 使用在线Cron工具验证
   - 检查时区设置
   - 注意月份和星期的范围

3. **权限错误**
   - 检查文件系统权限
   - 确认API访问权限
   - 验证用户权限配置

### 调试技巧
- 使用 `/task run` 手动测试任务
- 查看 `/task status` 了解系统状态
- 检查AstrBot日志获取详细错误信息

## 📝 开发指南

### 扩展动作类型
在 `services/executor.py` 中添加新的动作处理方法：

```python
async def _execute_my_action(self, config: Dict[str, Any]) -> Dict[str, Any]:
    # 实现自定义动作逻辑
    return {"success": True, "message": "执行成功"}
```

### 自定义条件
在 `utils/template.py` 中扩展条件评估器：

```python
def _evaluate_my_condition(self, config: Dict[str, Any], context: Dict[str, Any]) -> bool:
    # 实现自定义条件逻辑
    return True
```

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交Issue和Pull Request来改进这个插件！