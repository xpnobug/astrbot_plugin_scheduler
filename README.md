# 通用定时任务调度插件

一个功能强大的通用定时任务调度插件，支持多种调度方式和丰富的动作类型。

## 🆕 最新更新

### v2.0.0 - 图片API支持
- ✨ **全新图片API支持**: 支持返回图片URL和直接返回图片内容的API
- 🔄 **智能Content-Type检测**: 自动识别图片响应类型
- 📊 **API数据提取增强**: 从JSON响应中提取任意字段并自动发送消息
- 🖼️ **临时文件管理**: 安全的图片临时存储和自动清理
- 🎨 **丰富的变量模板**: 支持图片大小、类型等专用变量
- 🛡️ **安全性增强**: 命令注入防护、配置验证、并发安全

## 🚀 功能特性

### 调度方式
- **Cron表达式**: 支持标准的5字段Cron格式，如 `0 9 * * *` (每天9点)
- **固定间隔**: 按秒/分钟/小时间隔执行，如每5分钟、每小时
- **一次性任务**: 指定具体时间执行一次
- **手动触发**: 只能通过命令手动执行

### 动作类型
- **send_message**: 发送消息到用户、群组或广播
- **api_call**: 调用HTTP API接口，🆕支持图片API和数据提取
- **file_operation**: 文件操作(备份、删除、移动、复制、清理)
- **command**: 执行系统命令(需要安全配置)

### 高级功能
- **条件执行**: 支持时间范围、星期、变量条件等
- **变量模板**: 动态变量替换，如 `{{timestamp}}`、`{{date}}`
- **🆕图片API支持**: 支持返回图片URL或直接返回图片内容的API
- **🆕数据提取**: 从API响应中提取字段并自动发送消息
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

## 🖼️ 图片API支持

### 图片API类型

插件支持两种图片API：

#### 1. 返回图片URL的API
适用于API响应为JSON，包含图片URL字段的情况。

```json
{
  "id": "daily_wallpaper",
  "name": "每日壁纸",
  "description": "每天推送精美壁纸",
  "schedule": {
    "type": "cron",
    "config": {"expression": "0 9 * * *"}
  },
  "actions": [
    {
      "type": "api_call",
      "config": {
        "method": "GET",
        "url": "https://api.unsplash.com/photos/random?client_id=YOUR_KEY",
        "image_fields": ["urls.regular"],
        "send_as_image": true,
        "image_message_template": "📷 今日精选壁纸\n🎨 作者: {{user.name}}\n📝 {{description}}",
        "extract_fields": ["user.name", "description"],
        "send_platform": "aiocqhttp",
        "send_target_type": "group",
        "send_target_id": "123456789"
      }
    }
  ]
}
```

#### 2. 直接返回图片内容的API
适用于API直接返回图片二进制数据的情况。

```json
{
  "id": "random_image",
  "name": "随机图片",
  "description": "每小时推送随机图片",
  "schedule": {
    "type": "interval",
    "config": {"hours": 1}
  },
  "actions": [
    {
      "type": "api_call",
      "config": {
        "method": "GET",
        "url": "https://picsum.photos/800/600",
        "response_is_image": true,
        "image_message_template": "🎨 随机美图 {{image_size}} | {{time}}",
        "send_platform": "aiocqhttp",
        "send_target_type": "group",
        "send_target_id": "123456789"
      }
    }
  ]
}
```

### 图片API配置说明

#### 通用配置
- **`send_as_image`**: 设为 `true` 启用图片发送模式
- **`image_message_template`**: 图片消息的文本部分模板
- **`send_platform`**: 目标平台 (aiocqhttp, gewechat, telegram 等)
- **`send_target_type`**: 消息类型 (group, private, channel)
- **`send_target_id`**: 目标群组或用户ID

#### 返回图片URL的API专用配置
- **`image_fields`**: 图片字段路径数组，支持嵌套路径
  - 简单字段: `["image_url"]`
  - 嵌套字段: `["data.image_url", "thumbnail"]`
  - 数组索引: `["images[0].url"]`
- **`extract_fields`**: 提取其他字段用于消息模板
- **`image_download_timeout`**: 图片下载超时时间(秒)，默认30秒

#### 直接返回图片的API专用配置
- **`response_is_image`**: 设为 `true` 表示响应为图片内容

### 更多图片API示例

#### AI生成图片
```json
{
  "id": "ai_avatar",
  "name": "AI头像生成",
  "schedule": {
    "type": "cron",
    "config": {"expression": "0 12 * * *"}
  },
  "actions": [
    {
      "type": "api_call",
      "config": {
        "method": "GET",
        "url": "https://thispersondoesnotexist.com/image",
        "response_is_image": true,
        "image_message_template": "🤖 AI生成头像 {{date}}\n📏 大小: {{image_size}}",
        "send_platform": "aiocqhttp",
        "send_target_type": "private",
        "send_target_id": "987654321"
      }
    }
  ]
}
```

#### 天气图表
```json
{
  "id": "weather_chart",
  "name": "天气图表",
  "schedule": {
    "type": "interval",
    "config": {"hours": 6}
  },
  "actions": [
    {
      "type": "api_call",
      "config": {
        "method": "GET",
        "url": "https://api.openweathermap.org/data/2.5/weather?q=Beijing&appid=YOUR_KEY",
        "image_fields": ["weather[0].icon"],
        "send_as_image": true,
        "image_message_template": "🌤️ 北京天气 {{date}}\n🌡️ 温度: {{main.temp}}°C\n💧 湿度: {{main.humidity}}%\n☁️ 状况: {{weather[0].description}}",
        "extract_fields": ["main.temp", "main.humidity", "weather[0].description"],
        "send_platform": "aiocqhttp",
        "send_target_type": "group",
        "send_target_id": "weather_group"
      }
    }
  ]
}
```

#### 可爱宠物图片
```json
{
  "id": "cute_pets",
  "name": "每日萌宠",
  "schedule": {
    "type": "cron",
    "config": {"expression": "0 8 * * *"}
  },
  "actions": [
    {
      "type": "api_call",
      "config": {
        "method": "GET",
        "url": "https://cataas.com/cat",
        "response_is_image": true,
        "image_message_template": "🐱 今日份猫咪治愈 {{date}}",
        "send_platform": "aiocqhttp",
        "send_target_type": "group",
        "send_target_id": "pet_lovers"
      }
    }
  ]
}
```

### 图片API变量

图片消息模板支持以下专用变量：

#### 直接图片API变量
- **`{{image_size}}`**: 图片大小 (如 "256KB")
- **`{{content_type}}`**: 图片MIME类型 (如 "image/jpeg")

#### API响应变量
- **`{{字段名}}`**: API响应中提取的任何字段值
- **`{{timestamp}}`**: 当前时间戳
- **`{{date}}`**: 当前日期 (YYYY-MM-DD)
- **`{{time}}`**: 当前时间 (HH:MM:SS)

### 常用免费图片API

#### 直接返回图片的API
- **Lorem Picsum**: `https://picsum.photos/800/600` (随机图片)
- **PlaceKitten**: `https://placekitten.com/800/600` (可爱小猫)
- **Cat API**: `https://cataas.com/cat` (猫咪图片)
- **ThisPersonDoesNotExist**: `https://thispersondoesnotexist.com/image` (AI人脸)
- **Unsplash Source**: `https://source.unsplash.com/800x600/?nature` (自然风景)

#### 返回图片URL的API
- **Unsplash API**: 需要API Key，返回高质量图片和详细信息
- **Dog API**: `https://dog.ceo/api/breeds/image/random` 
- **Cat Facts API**: 部分端点返回猫图片URL
- **NASA APOD**: NASA每日天文图片API

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

### 🆕 图片API专用变量
- `{{image_size}}` - 图片大小 (如 "256KB")
- `{{content_type}}` - 图片MIME类型 (如 "image/jpeg")
- `{{字段名}}` - API响应中提取的任何字段值

### 🆕 API数据提取变量
使用 `extract_fields` 配置从API响应中提取任意字段：
```json
{
  "extract_fields": ["user.name", "description", "stats.downloads"],
  "message_template": "作者: {{name}}, 描述: {{description}}, 下载: {{downloads}}"
}
```

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

4. **🆕 图片API问题**
   - **图片无法显示**: 检查图片URL是否有效，确保以http/https开头
   - **字段提取失败**: 验证 `image_fields` 路径是否正确，可以先用浏览器查看API响应
   - **Content-Type检测失败**: 手动设置 `response_is_image: true`
   - **平台不支持**: 确认目标平台支持图片发送功能
   - **临时文件问题**: 检查系统临时目录权限

5. **🆕 API数据提取问题**
   - **变量替换失败**: 检查 `extract_fields` 和模板中的字段名是否匹配
   - **嵌套字段**: 使用正确的路径语法，如 `data.user.name` 或 `items[0].title`
   - **JSON解析错误**: 确认API返回有效的JSON格式

### 调试技巧
- 使用 `/task run` 手动测试任务
- 查看 `/task status` 了解系统状态
- 检查AstrBot日志获取详细错误信息

#### 🆕 图片API调试
- **查看API响应**: 先在浏览器中访问API URL，确认返回内容
- **测试字段路径**: 使用在线JSON格式化工具验证字段路径
- **检查日志**: 查看详细的图片处理日志输出
- **平台兼容性**: 测试不同平台的图片发送支持

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

## 🚀 快速开始

### 1. 安装插件
在AstrBot管理面板中安装并启用"通用定时任务调度插件"。

### 2. 创建第一个任务
使用 `/task create` 命令或在插件配置中直接编辑JSON：

```json
{
  "tasks": [
    {
      "id": "hello_world",
      "name": "Hello World",
      "description": "我的第一个定时任务",
      "schedule": {
        "type": "cron",
        "config": {"expression": "0 9 * * *"}
      },
      "actions": [
        {
          "type": "send_message",
          "config": {
            "target_type": "group",
            "target_id": "YOUR_GROUP_ID",
            "message": "🌅 早上好！今天是 {{date}}"
          }
        }
      ]
    }
  ]
}
```

### 3. 测试任务
使用 `/task run hello_world` 命令手动执行任务进行测试。

### 4. 监控任务
使用 `/task status` 查看调度器状态和任务执行情况。

## 🤝 贡献

欢迎提交Issue和Pull Request来改进这个插件！