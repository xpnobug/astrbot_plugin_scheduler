# 更新日志

所有关于此项目的重要更改都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

## [2.0.0] - 2025-07-20

### 新增 ✨
- **图片API全面支持**
  - 支持返回图片URL的JSON API
  - 支持直接返回图片内容的二进制API
  - 智能Content-Type检测 (`image/*`, `application/octet-stream`)
  - 手动图片响应指定 (`response_is_image` 配置)
  
- **图片处理和发送**
  - 临时文件管理系统，安全存储和自动清理
  - 支持多种图片格式 (JPG, PNG, GIF, WebP, BMP, SVG)
  - 根据Content-Type自动确定文件扩展名
  - 混合消息支持 (文本+图片)
  
- **API数据提取增强**
  - 从JSON响应中提取任意嵌套字段
  - 支持数组索引访问 (`items[0].title`)
  - 自动消息模板变量替换
  - 提取失败时的优雅降级处理
  
- **图片专用变量模板**
  - `{{image_size}}` - 图片大小显示
  - `{{content_type}}` - 图片MIME类型
  - API响应字段的动态变量支持
  
- **安全性增强**
  - 命令注入漏洞修复，实现安全命令白名单机制
  - 完整的JSON Schema配置验证和安全检查
  - 并发安全改进，添加线程锁保护共享资源
  - 路径遍历攻击防护
  - 网络请求安全限制

### 改进 🔧
- **配置验证系统**
  - 新增图片相关字段验证 (`image_fields`, `send_as_image`, `image_message_template`)
  - 增强API调用配置验证
  - 更详细的错误提示信息
  
- **任务管理器优化**
  - 使用 `deque` 替代普通列表，自动限制历史记录数量
  - 添加可重入锁 (`threading.RLock`) 支持并发访问
  - 改进的统计信息计算
  
- **执行器功能增强**
  - 响应类型智能检测和分流处理
  - 改进的错误处理和日志记录
  - 更详细的执行结果信息
  
- **文档和配置**
  - 完整的图片API配置说明和示例
  - 常用免费图片API资源列表
  - 详细的故障排除指南

### 示例配置
```json
{
  "id": "daily_wallpaper",
  "name": "每日壁纸推送",
  "schedule": {
    "type": "cron",
    "config": {"expression": "0 9 * * *"}
  },
  "actions": [{
    "type": "api_call",
    "config": {
      "method": "GET",
      "url": "https://api.unsplash.com/photos/random?client_id=YOUR_KEY",
      "image_fields": ["urls.regular"],
      "send_as_image": true,
      "image_message_template": "📷 今日精选壁纸\n🎨 作者: {{user.name}}",
      "extract_fields": ["user.name", "description"],
      "send_platform": "aiocqhttp",
      "send_target_type": "group",
      "send_target_id": "123456789"
    }
  }]
}
```

### 技术详情
- **图片临时存储**: `/tmp/astrbot_scheduler_images/` 目录
- **支持的图片格式**: JPG, PNG, GIF, WebP, BMP, SVG
- **安全限制**: 内网地址禁止、危险命令检测、文件路径验证
- **并发保护**: 线程安全的任务管理和状态更新

---

## [1.3.0] - 2025-07-20

### 新增 ✨
- **API调用基础功能**
  - HTTP API调用支持 (GET, POST, PUT, DELETE, PATCH)
  - 基础的响应处理和错误处理
  - 超时控制和重试机制

- **变量模板系统**
  - 基础变量支持 (`{{timestamp}}`, `{{date}}`, `{{time}}`)
  - 执行上下文变量
  - 简单的字符串替换功能

### 改进 🔧
- 优化任务调度性能
- 改进错误日志记录
- 增强配置验证

---

## [1.2.0] - 2025-07-20

### 新增 ✨
- **文件操作支持**
  - 备份、删除、移动、复制操作
  - 压缩文件支持
  - 自动清理功能

- **条件执行系统**
  - 时间范围条件
  - 星期过滤
  - 前置动作依赖

### 修复 🐛
- 修复Cron表达式解析问题
- 解决任务重复执行的bug
- 改进时区处理

---

## [1.1.0] - 2025-07-20

### 新增 ✨
- **命令执行功能**
  - 安全的系统命令执行
  - 工作目录控制
  - 输出捕获和超时保护

- **任务分组和优先级**
  - 任务分组管理
  - 优先级排序
  - 依赖关系支持

### 改进 🔧
- 优化调度器性能
- 改进任务状态管理
- 增强错误恢复机制

---

## [1.0.0] - 2025-07-20

### 新增 ✨
- **核心调度功能**
  - Cron表达式支持
  - 固定间隔调度
  - 一次性任务
  - 手动触发

- **消息发送功能**
  - 多平台支持 (QQ, 微信, Telegram 等)
  - 群组和私聊消息
  - 消息模板支持

- **基础功能**
  - 任务CRUD操作
  - 执行历史记录
  - 简单的统计信息

### 管理命令
- `/task list` - 列出所有任务
- `/task info <task_id>` - 查看任务详情
- `/task run <task_id>` - 手动执行任务
- `/task enable/disable <task_id>` - 启用/禁用任务
- `/task status` - 查看调度器状态

---

## 发布类型说明

- **新增 ✨**: 全新功能
- **改进 🔧**: 功能优化和性能改进
- **修复 🐛**: Bug修复
- **安全 🛡️**: 安全相关更新
- **文档 📝**: 文档更新
- **其他**: 构建、测试等相关更改

## 贡献者

感谢所有为此项目做出贡献的开发者！

## 支持

如果遇到问题或有功能建议，请：
1. 查看 [README.md](./README.md) 中的故障排除部分
2. 在 GitHub 提交 Issue
3. 加入 AstrBot 社区群组讨论

---

*关注我们获取最新更新和功能预告！*