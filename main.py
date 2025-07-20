"""
通用定时任务调度插件
支持完全可配置的定时任务，包括Cron表达式、间隔执行、条件执行等
"""
import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.core.utils.session_waiter import session_waiter, SessionController

# 导入模块化组件
from .models.task import Task, TaskManager, TaskAction, TaskSchedule
from .services.scheduler import TaskScheduler
from .services.executor import ActionExecutor
from .utils.cron_parser import CronParser, IntervalParser, NaturalTimeParser
from .utils.template import VariableReplacer, ConditionEvaluator


@register("scheduler", "Couei", "通用定时任务调度插件", "1.0.0")
class SchedulerPlugin(Star):
    """通用定时任务调度插件"""
    
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        
        # 初始化配置
        self.plugin_config = config or {}
        self.astrbot_config = config
        
        # 初始化数据目录
        self.data_dir = Path("data/scheduler")
        self.data_dir.mkdir(exist_ok=True)
        
        # 配置文件路径
        self.config_file = Path(__file__).parent / "config" / "tasks.json"
        self.tasks_file = self.data_dir / "tasks.json"
        self.history_file = self.data_dir / "history.json"
        
        # 获取配置参数 - 扁平化配置结构
        self.max_concurrent_tasks = getattr(self.plugin_config, "max_concurrent_tasks", 10)
        self.task_timeout = getattr(self.plugin_config, "task_timeout", 300)
        self.scheduler_check_interval = getattr(self.plugin_config, "scheduler_check_interval", 30)
        self.enable_file_operations = getattr(self.plugin_config, "enable_file_operations", True)
        self.enable_command_execution = getattr(self.plugin_config, "enable_command_execution", False)
        self.admin_user_id = getattr(self.plugin_config, "admin_user_id", "admin")
        
        # 初始化核心组件
        self.task_manager = TaskManager()
        self.variable_replacer = VariableReplacer()
        self.condition_evaluator = ConditionEvaluator(self.variable_replacer)
        self.action_executor = ActionExecutor(
            context, 
            self.variable_replacer,
            self.enable_file_operations,
            self.enable_command_execution
        )
        
        # 初始化调度器
        self.scheduler = TaskScheduler(self.task_manager, self._execute_task, self.scheduler_check_interval)
        
        # 解析器
        self.cron_parser = CronParser()
        self.interval_parser = IntervalParser()
        self.natural_parser = NaturalTimeParser()
        
        # 加载任务配置
        self._load_tasks()
        
        # 启动调度器 - 保存任务引用避免被垃圾回收
        self._scheduler_task = asyncio.create_task(self._start_scheduler())
        
        logger.info("通用定时任务调度插件已初始化")
    
    async def terminate(self):
        """插件终止时的清理工作"""
        try:
            # 停止调度器
            if hasattr(self, '_scheduler_task') and not self._scheduler_task.done():
                self._scheduler_task.cancel()
                try:
                    await self._scheduler_task
                except asyncio.CancelledError:
                    pass
                    
            # 停止调度器服务
            if hasattr(self, 'scheduler'):
                await self.scheduler.stop()
                
            logger.info("定时任务插件已安全终止")
            
        except Exception as e:
            logger.error(f"插件终止时出错: {e}")
    
    def _load_tasks(self):
        """加载任务配置"""
        try:
            tasks_loaded = 0
            
            # 1. 处理快速创建任务
            self._handle_quick_create_tasks()
            
            # 2. 优先从配置界面JSON加载任务（带安全验证）
            tasks_config_json = getattr(self.plugin_config, "tasks_config_json", "")
            if tasks_config_json and tasks_config_json.strip():
                try:
                    # 直接解析JSON配置
                    config_data = json.loads(tasks_config_json)
                    
                    # 加载任务
                    for task_data in config_data.get("tasks", []):
                        task = Task.from_dict(task_data)
                        # 注意：这里是同步上下文，我们需要使用同步方法或者延迟加载
                        # 暂时使用直接赋值，后续可以改为异步加载
                        if task.id not in self.task_manager.tasks:
                            self.task_manager.tasks[task.id] = task
                            tasks_loaded += 1
                    
                    logger.info(f"✅ 从配置JSON安全加载了 {tasks_loaded} 个任务")
                    return
                    
                except Exception as e:
                    logger.error(f"❌ 配置加载异常: {e}")
                    logger.error("配置加载被阻止，插件将使用默认配置运行")
            
            # 3. 尝试加载用户任务文件
            if self.tasks_file.exists():
                with open(self.tasks_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for task_data in data.get("tasks", []):
                        task = Task.from_dict(task_data)
                        self.task_manager.add_task(task)
                        tasks_loaded += 1
                logger.info(f"从文件加载了 {tasks_loaded} 个用户任务")
                return
            
            # 4. 加载示例配置
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 只加载启用的示例任务
                    for task_data in data.get("tasks", []):
                        if task_data.get("enabled", False):
                            task = Task.from_dict(task_data)
                            self.task_manager.add_task(task)
                            tasks_loaded += 1
                logger.info(f"加载了 {tasks_loaded} 个示例任务")
            
            # 5. 同步当前任务到配置界面
            self._sync_tasks_to_config()
            
        except Exception as e:
            logger.error(f"加载任务配置失败: {e}", exc_info=True)
    
    def _handle_quick_create_tasks(self):
        """处理快速创建任务"""
        try:
            # 检查快速创建开关 - 扁平化配置
            if getattr(self.plugin_config, "quick_create_reminder", False):
                self._create_quick_reminder_task()
            
            if getattr(self.plugin_config, "quick_create_backup", False):
                self._create_quick_backup_task()
            
            if getattr(self.plugin_config, "quick_create_monitor", False):
                self._create_quick_monitor_task()
                
        except Exception as e:
            logger.error(f"处理快速创建任务失败: {e}")
    
    def _sync_tasks_to_config(self):
        """同步当前任务到配置界面显示"""
        try:
            # 获取当前所有任务
            tasks = self.task_manager.list_tasks()
            
            if not tasks:
                # 如果没有任务，显示提示信息
                tasks_config = {
                    "tasks": [],
                    "_info": "暂无任务。使用 /task create 命令创建新任务，或启用上方的快速创建选项。",
                    "_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            else:
                # 将任务转换为配置格式，按状态和组织分类
                enabled_tasks = [task for task in tasks if task.enabled]
                disabled_tasks = [task for task in tasks if not task.enabled]
                
                tasks_config = {
                    "tasks": [task.to_dict() for task in tasks],
                    "_info": f"📊 任务统计: 总共 {len(tasks)} 个任务 (运行中 {len(enabled_tasks)} 个, 已停用 {len(disabled_tasks)} 个)",
                    "_usage_hint": "💡 可直接编辑此JSON配置，或使用 /task 命令系列进行可视化管理",
                    "_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            
            # 格式化JSON
            formatted_json = json.dumps(tasks_config, indent=2, ensure_ascii=False)
            
            # 尝试通过多种方式更新配置显示
            try:
                # 方法1: 直接更新插件配置属性
                if hasattr(self.plugin_config, '__setitem__'):
                    self.plugin_config["tasks_config_json"] = formatted_json
                elif hasattr(self.plugin_config, '__dict__'):
                    setattr(self.plugin_config, "tasks_config_json", formatted_json)
                
                logger.debug(f"✅ 已同步 {len(tasks)} 个任务到配置界面")
                
            except Exception as e:
                logger.warning(f"配置界面更新失败，但不影响任务管理功能: {e}")
                
        except Exception as e:
            logger.error(f"同步任务到配置失败: {e}")
    
    def _create_quick_reminder_task(self):
        """创建快速提醒任务"""
        reminder_task = {
            "id": "quick_daily_reminder",
            "name": "每日提醒 (快速创建)",
            "description": "通过配置界面快速创建的每日提醒任务示例",
            "enabled": True,
            "schedule": {
                "type": "cron",
                "config": {"expression": "0 9 * * *"},
                "timezone": "Asia/Shanghai",
                "enabled": True
            },
            "actions": [
                {
                    "type": "send_message",
                    "config": {
                        "platform": "aiocqhttp",
                        "target_type": "group",
                        "target_id": "请修改为实际群组ID",
                        "message": "🌅 早上好！新的一天开始了！\n今天是{{date}}，{{weekday}}"
                    },
                    "conditions": []
                }
            ],
            "group": "quick_created",
            "priority": 1,
            "retry_count": 3,
            "on_failure": "log",
            "created_by": "quick_create",
            "tags": ["快速创建", "提醒"]
        }
        
        task = Task.from_dict(reminder_task)
        if self.task_manager.add_task(task):
            logger.info("已创建快速提醒任务")
    
    def _create_quick_backup_task(self):
        """创建快速备份任务"""
        backup_task = {
            "id": "quick_weekly_backup",
            "name": "定时备份 (快速创建)",
            "description": "通过配置界面快速创建的定时备份任务示例",
            "enabled": True,
            "schedule": {
                "type": "cron",
                "config": {"expression": "0 2 * * 0"},
                "timezone": "Asia/Shanghai",
                "enabled": True
            },
            "actions": [
                {
                    "type": "file_operation",
                    "config": {
                        "operation": "backup",
                        "source_path": "./data",
                        "target_path": "./backups/data_backup_{{timestamp}}.zip",
                        "compress": True
                    },
                    "conditions": []
                }
            ],
            "group": "quick_created",
            "priority": 5,
            "retry_count": 2,
            "on_failure": "notify",
            "created_by": "quick_create",
            "tags": ["快速创建", "备份"]
        }
        
        task = Task.from_dict(backup_task)
        if self.task_manager.add_task(task):
            logger.info("已创建快速备份任务")
    
    def _create_quick_monitor_task(self):
        """创建快速监控任务"""
        monitor_task = {
            "id": "quick_api_monitor",
            "name": "API监控 (快速创建)",
            "description": "通过配置界面快速创建的API监控任务示例",
            "enabled": True,
            "schedule": {
                "type": "interval",
                "config": {"seconds": 300},
                "timezone": "Asia/Shanghai",
                "enabled": True
            },
            "actions": [
                {
                    "type": "api_call",
                    "config": {
                        "method": "GET",
                        "url": "https://httpbin.org/status/200",
                        "timeout": 10,
                        "expected_status": 200
                    },
                    "conditions": []
                },
                {
                    "type": "send_message",
                    "config": {
                        "target_type": "user",
                        "target_id": self.admin_user_id,
                        "message": "⚠️ API监控异常\nURL: {{api_url}}\n状态码: {{status_code}}"
                    },
                    "conditions": [
                        {
                            "type": "previous_action_failed",
                            "config": {}
                        }
                    ]
                }
            ],
            "group": "quick_created",
            "priority": 3,
            "retry_count": 1,
            "on_failure": "notify",
            "created_by": "quick_create",
            "tags": ["快速创建", "监控"]
        }
        
        task = Task.from_dict(monitor_task)
        if self.task_manager.add_task(task):
            logger.info("已创建快速监控任务")
    
    def _convert_config_to_task(self, config_task: dict) -> dict:
        """将配置界面的任务格式转换为内部Task格式"""
        # 解析调度配置
        schedule_type = config_task.get("schedule_type", "manual")
        schedule_config_str = config_task.get("schedule_config", "")
        schedule_config = {}
        
        if schedule_type == "cron" and schedule_config_str:
            schedule_config = {"expression": schedule_config_str}
        elif schedule_type == "interval" and schedule_config_str:
            # 解析间隔时间
            seconds = self.interval_parser.parse_interval(schedule_config_str)
            if seconds:
                schedule_config = {"seconds": seconds}
        elif schedule_type == "once" and schedule_config_str:
            schedule_config = {"datetime": schedule_config_str}
        
        # 解析动作配置
        action_config_str = config_task.get("action_config", "{}")
        try:
            action_config = json.loads(action_config_str) if action_config_str else {}
        except json.JSONDecodeError:
            action_config = {}
        
        # 构建完整的任务配置
        task_data = {
            "id": config_task.get("id", config_task.get("name", "").lower().replace(" ", "_")),
            "name": config_task.get("name", "未命名任务"),
            "description": config_task.get("description", ""),
            "enabled": config_task.get("enabled", True),
            "schedule": {
                "type": schedule_type,
                "config": schedule_config,
                "timezone": "Asia/Shanghai",
                "enabled": config_task.get("enabled", True)
            },
            "actions": [
                {
                    "type": config_task.get("action_type", "send_message"),
                    "config": action_config,
                    "conditions": []
                }
            ],
            "group": config_task.get("group", "config"),
            "priority": config_task.get("priority", 1),
            "retry_count": config_task.get("retry_count", 3),
            "on_failure": config_task.get("on_failure", "log"),
            "created_by": "config_ui",
            "tags": ["配置界面创建"]
        }
        
        return task_data
    
    def _save_tasks(self):
        """保存任务配置"""
        try:
            tasks_data = {
                "tasks": [task.to_dict() for task in self.task_manager.tasks.values()],
                "updated_at": datetime.now().isoformat()
            }
            
            with open(self.tasks_file, 'w', encoding='utf-8') as f:
                json.dump(tasks_data, f, ensure_ascii=False, indent=2)
            
            # 同步任务到配置界面显示
            self._sync_tasks_to_config()
                
        except Exception as e:
            logger.error(f"保存任务配置失败: {e}")
    
    async def _start_scheduler(self):
        """启动调度器"""
        try:
            await asyncio.sleep(2)  # 等待插件完全初始化
            await self.scheduler.start()
        except Exception as e:
            logger.error(f"启动调度器失败: {e}")
    
    async def _execute_task(self, task: Task) -> Dict:
        """执行任务"""
        logger.info(f"开始执行任务: {task.name}")
        
        # 清空执行上下文
        self.action_executor.clear_execution_context()
        
        # 准备任务上下文
        task_context = {
            "task_id": task.id,
            "task_name": task.name,
            "execution_time": datetime.now().isoformat()
        }
        
        previous_action_success = True
        
        try:
            for i, action in enumerate(task.actions):
                # 更新上下文
                action_context = task_context.copy()
                action_context.update(self.action_executor.get_execution_context())
                action_context["previous_action_success"] = previous_action_success
                
                # 检查条件
                if not self.condition_evaluator.evaluate_conditions(action.conditions, action_context):
                    logger.info(f"任务 {task.name} 动作 {i+1} 条件不满足，跳过")
                    continue
                
                # 执行动作
                result = await self.action_executor.execute_action(action, action_context)
                previous_action_success = result.get("success", False)
                
                if not previous_action_success:
                    logger.warning(f"任务 {task.name} 动作 {i+1} 执行失败: {result.get('message', '')}")
                    return result
                else:
                    logger.info(f"任务 {task.name} 动作 {i+1} 执行成功")
            
            return {
                "success": True,
                "message": f"任务 {task.name} 执行完成"
            }
            
        except Exception as e:
            logger.error(f"任务 {task.name} 执行异常: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"任务执行异常: {str(e)}",
                "error": str(e)
            }
    
    @filter.command_group("task")
    def task(self):
        """定时任务管理命令组"""
        pass
    
    @task.command("list")
    async def list_tasks(self, event: AstrMessageEvent, group: str = ""):
        """列出所有任务 - 使用方法: /task list [group]"""
        try:
            user_id = event.get_sender_id()
            
            
            tasks = self.task_manager.list_tasks(group if group else None)
            
            if not tasks:
                yield event.plain_result("📋 没有找到任务")
                return
            
            # 按组分类
            groups = {}
            for task in tasks:
                if task.group not in groups:
                    groups[task.group] = []
                groups[task.group].append(task)
            
            result_lines = ["📋 定时任务列表\\n"]
            
            for group_name, group_tasks in groups.items():
                result_lines.append(f"📁 **{group_name}** ({len(group_tasks)}个任务)")
                
                for task in group_tasks:
                    status = "🟢" if task.enabled and task.schedule.enabled else "🔴"
                    schedule_desc = self._get_schedule_description(task.schedule)
                    next_run = task.next_run.strftime("%m-%d %H:%M") if task.next_run else "未知"
                    
                    # 安全地处理task.id，确保是字符串类型
                    task_id_short = str(task.id)[:8] if task.id else "未知"
                    
                    result_lines.append(
                        f"  {status} `{task.name}` ({task_id_short})"
                        f"\\n    📅 {schedule_desc}"
                        f"\\n    ⏰ 下次: {next_run}"
                        f"\\n    📊 成功/失败: {task.success_count}/{task.fail_count}"
                    )
                result_lines.append("")
            
            stats = self.task_manager.get_task_statistics()
            result_lines.append(f"📈 **统计**: 总计{stats['total_tasks']}个, 运行中{stats['running_tasks']}个, 成功率{stats['success_rate']}%")
            
            yield event.plain_result("\\n".join(result_lines))
            
        except Exception as e:
            logger.error(f"列出任务失败: {e}")
            yield event.plain_result("😥 获取任务列表失败")
    
    @task.command("info")
    async def task_info(self, event: AstrMessageEvent, task_id: str):
        """查看任务详情 - 使用方法: /task info <task_id>"""
        try:
            task = self.task_manager.get_task(task_id)
            if not task:
                yield event.plain_result(f"❌ 任务不存在: {task_id}")
                return
            
            status = "🟢 运行中" if task.enabled and task.schedule.enabled else "🔴 已停止"
            schedule_desc = self._get_schedule_description(task.schedule)
            
            info_text = f"""📋 **任务详情**
            
**基本信息:**
• ID: `{task.id}`
• 名称: {task.name}
• 描述: {task.description}
• 状态: {status}
• 分组: {task.group}
• 优先级: {task.priority}

**调度配置:**
• 类型: {task.schedule.type}
• 规则: {schedule_desc}
• 时区: {task.schedule.timezone}

**执行统计:**
• 总运行次数: {task.run_count}
• 成功次数: {task.success_count}
• 失败次数: {task.fail_count}
• 最后运行: {task.last_run.strftime('%Y-%m-%d %H:%M:%S') if task.last_run else '从未运行'}
• 下次运行: {task.next_run.strftime('%Y-%m-%d %H:%M:%S') if task.next_run else '未知'}

**错误处理:**
• 重试次数: {task.retry_count}
• 重试延迟: {task.retry_delay}秒
• 失败处理: {task.on_failure}

**动作列表:**"""
            
            for i, action in enumerate(task.actions, 1):
                info_text += f"\\n{i}. {action.type} - {len(action.conditions)}个条件"
            
            if task.dependencies:
                info_text += f"\\n\\n**依赖任务:** {', '.join(task.dependencies)}"
            
            if task.tags:
                info_text += f"\\n**标签:** {', '.join(task.tags)}"
            
            yield event.plain_result(info_text)
            
        except Exception as e:
            logger.error(f"查看任务详情失败: {e}")
            yield event.plain_result("😥 获取任务详情失败")
    
    @task.command("run")
    async def run_task(self, event: AstrMessageEvent, task_id: str):
        """手动执行任务 - 使用方法: /task run <task_id>"""
        try:
            task = self.task_manager.get_task(task_id)
            if not task:
                yield event.plain_result(f"❌ 任务不存在: {task_id}")
                return
            
            # 检查任务状态
            current_status = self.scheduler.get_task_status(task_id)
            if current_status == "运行中":
                yield event.plain_result(f"⚠️ 任务 {task.name} 正在运行中，请稍后再试")
                return
            
            yield event.plain_result(f"🚀 开始手动执行任务: {task.name}")
            
            # 手动执行任务
            success = await self.scheduler.run_task_manually(task_id)
            if success:
                yield event.plain_result(f"✅ 任务 {task.name} 已提交执行")
            else:
                yield event.plain_result(f"❌ 任务 {task.name} 执行失败")
                
        except Exception as e:
            logger.error(f"手动执行任务失败: {e}")
            yield event.plain_result("😥 手动执行任务失败")
    
    @task.command("enable")
    async def enable_task(self, event: AstrMessageEvent, task_id: str):
        """启用任务 - 使用方法: /task enable <task_id>"""
        try:
            task = self.task_manager.get_task(task_id)
            if not task:
                yield event.plain_result(f"❌ 任务不存在: {task_id}")
                return
            
            task.enabled = True
            task.schedule.enabled = True
            task.updated_at = datetime.now()
            self._save_tasks()
            
            yield event.plain_result(f"✅ 任务 {task.name} 已启用")
            
        except Exception as e:
            logger.error(f"启用任务失败: {e}")
            yield event.plain_result("😥 启用任务失败")
    
    @task.command("disable")
    async def disable_task(self, event: AstrMessageEvent, task_id: str):
        """禁用任务 - 使用方法: /task disable <task_id>"""
        try:
            task = self.task_manager.get_task(task_id)
            if not task:
                yield event.plain_result(f"❌ 任务不存在: {task_id}")
                return
            
            task.enabled = False
            task.schedule.enabled = False
            task.updated_at = datetime.now()
            self._save_tasks()
            
            yield event.plain_result(f"🔴 任务 {task.name} 已禁用")
            
        except Exception as e:
            logger.error(f"禁用任务失败: {e}")
            yield event.plain_result("😥 禁用任务失败")
    
    @task.command("status")
    async def scheduler_status(self, event: AstrMessageEvent):
        """查看调度器状态"""
        try:
            stats = self.scheduler.get_scheduler_stats()
            task_stats = self.task_manager.get_task_statistics()
            
            status_text = f"""📊 **调度器状态**

**运行状态:**
• 调度器: {'🟢 运行中' if stats['running'] else '🔴 已停止'}
• 总任务数: {stats['total_tasks']}
• 运行中任务: {stats['running_tasks']}
• 已完成任务: {stats['completed_tasks']}
• 失败任务: {stats['failed_tasks']}

**任务统计:**
• 启用任务: {task_stats['enabled_tasks']}
• 活跃任务: {task_stats['running_tasks']}
• 总执行次数: {task_stats['total_executions']}
• 成功率: {task_stats['success_rate']}%
• 近期失败: {task_stats['recent_failures']}

**任务分组:**
{', '.join(task_stats['groups']) if task_stats['groups'] else '无'}
"""
            
            yield event.plain_result(status_text)
            
        except Exception as e:
            logger.error(f"查看调度器状态失败: {e}")
            yield event.plain_result("😥 获取调度器状态失败")
    
    @task.command("create")
    async def create_task(self, event: AstrMessageEvent):
        """创建新任务 - 可视化配置向导"""
        try:
            user_id = event.get_sender_id()
            
            
            yield event.plain_result("🔧 **任务创建向导**\n\n请按照步骤创建新的定时任务：")
            
            # 任务基本信息
            task_data = {
                "id": "",
                "name": "",
                "description": "",
                "enabled": True,
                "group": "custom",
                "priority": 1,
                "retry_count": 3,
                "on_failure": "log"
            }
            
            # 步骤1: 任务基本信息
            yield event.plain_result("**步骤 1/4: 基本信息**\n请输入任务名称：")
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_task_name(controller: SessionController, event: AstrMessageEvent):
                task_name = event.message_str.strip() if event.message_str else ""
                if not task_name:
                    await event.send(event.plain_result("❌ 任务名称不能为空，请重新输入："))
                    controller.keep(timeout=60, reset_timeout=True)
                    return
                
                task_data["name"] = task_name
                task_data["id"] = task_name.lower().replace(" ", "_").replace("-", "_")
                
                await event.send(event.plain_result(f"✅ 任务名称：{task_name}\n\n请输入任务描述："))
                controller.stop()
            
            await get_task_name(event)
            
            @session_waiter(timeout=60, record_history_chains=False)  
            async def get_task_description(controller: SessionController, event: AstrMessageEvent):
                description = event.message_str.strip() if event.message_str else ""
                if not description:
                    description = f"由可视化向导创建的任务: {task_data['name']}"
                
                task_data["description"] = description
                
                schedule_options = """✅ 任务描述设置完成

**步骤 2/4: 调度设置**
请选择调度类型：

1️⃣ **cron** - Cron表达式 (如: 每天9点)
2️⃣ **interval** - 固定间隔 (如: 每5分钟)  
3️⃣ **once** - 一次性任务 (指定时间执行)
4️⃣ **manual** - 手动触发

请回复数字 1-4："""
                
                await event.send(event.plain_result(schedule_options))
                controller.stop()
            
            await get_task_description(event)
            
            # 步骤2: 调度设置
            @session_waiter(timeout=120, record_history_chains=False)
            async def get_schedule_type(controller: SessionController, event: AstrMessageEvent):
                choice = event.message_str.strip() if event.message_str else ""
                
                schedule_types = {"1": "cron", "2": "interval", "3": "once", "4": "manual"}
                
                if choice not in schedule_types:
                    await event.send(event.plain_result("❌ 请输入有效数字 1-4："))
                    controller.keep(timeout=120, reset_timeout=True)
                    return
                
                schedule_type = schedule_types[choice]
                task_data["schedule_type"] = schedule_type
                
                if schedule_type == "cron":
                    cron_help = """🕐 **Cron表达式设置**

常用示例：
• `0 9 * * *` - 每天上午9点
• `*/30 * * * *` - 每30分钟
• `0 0 1 * *` - 每月1日
• `0 8 * * 1-5` - 工作日上午8点
• `@daily` - 每天午夜
• `@hourly` - 每小时

请输入Cron表达式："""
                    await event.send(event.plain_result(cron_help))
                    
                elif schedule_type == "interval":
                    interval_help = """⏱️ **间隔时间设置**

支持格式：
• `30s` - 30秒
• `5m` - 5分钟  
• `2h` - 2小时
• `1d` - 1天

请输入间隔时间："""
                    await event.send(event.plain_result(interval_help))
                    
                elif schedule_type == "once":
                    once_help = """📅 **一次性任务时间设置**

格式：YYYY-MM-DD HH:MM:SS
示例：2024-12-25 09:00:00

请输入执行时间："""
                    await event.send(event.plain_result(once_help))
                    
                else:  # manual
                    task_data["schedule_config"] = {}
                    await event.send(event.plain_result("✅ 设置为手动触发任务\n\n进入下一步..."))
                    # 直接进入下一步
                
                controller.stop()
            
            await get_schedule_type(event)
            
            # 获取调度配置
            if task_data.get("schedule_type") != "manual":
                @session_waiter(timeout=120, record_history_chains=False)
                async def get_schedule_config(controller: SessionController, event: AstrMessageEvent):
                    config_input = event.message_str.strip() if event.message_str else ""
                    
                    if not config_input:
                        await event.send(event.plain_result("❌ 配置不能为空，请重新输入："))
                        controller.keep(timeout=120, reset_timeout=True)
                        return
                    
                    schedule_type = task_data["schedule_type"]
                    
                    # 验证配置
                    if schedule_type == "cron":
                        if not self.cron_parser.parse(config_input):
                            await event.send(event.plain_result("❌ Cron表达式格式错误，请重新输入："))
                            controller.keep(timeout=120, reset_timeout=True)
                            return
                        task_data["schedule_config"] = {"expression": config_input}
                        desc = self.cron_parser.describe(config_input)
                        
                    elif schedule_type == "interval":
                        seconds = self.interval_parser.parse_interval(config_input)
                        if not seconds:
                            await event.send(event.plain_result("❌ 间隔时间格式错误，请重新输入："))
                            controller.keep(timeout=120, reset_timeout=True)
                            return
                        task_data["schedule_config"] = {"seconds": seconds}
                        desc = self.interval_parser.describe_interval(seconds)
                        
                    elif schedule_type == "once":
                        try:
                            datetime.fromisoformat(config_input.replace(" ", "T"))
                            task_data["schedule_config"] = {"datetime": config_input}
                            desc = f"一次性任务: {config_input}"
                        except ValueError:
                            await event.send(event.plain_result("❌ 时间格式错误，请重新输入："))
                            controller.keep(timeout=120, reset_timeout=True)
                            return
                    
                    await event.send(event.plain_result(f"✅ 调度设置：{desc}\n\n进入下一步..."))
                    controller.stop()
                
                await get_schedule_config(event)
            
            # 步骤3: 动作设置
            action_menu = """**步骤 3/4: 动作设置**
请选择要执行的动作类型：

1️⃣ **send_message** - 发送消息
2️⃣ **api_call** - 调用API接口
3️⃣ **file_operation** - 文件操作
4️⃣ **command** - 执行系统命令

请回复数字 1-4："""
            
            yield event.plain_result(action_menu)
            
            @session_waiter(timeout=120, record_history_chains=False)
            async def get_action_type(controller: SessionController, event: AstrMessageEvent):
                choice = event.message_str.strip() if event.message_str else ""
                
                action_types = {"1": "send_message", "2": "api_call", "3": "file_operation", "4": "command"}
                
                if choice not in action_types:
                    await event.send(event.plain_result("❌ 请输入有效数字 1-4："))
                    controller.keep(timeout=120, reset_timeout=True)
                    return
                
                action_type = action_types[choice]
                task_data["action_type"] = action_type
                
                # 根据动作类型提供配置模板
                if action_type == "send_message":
                    config_template = """📨 **发送消息配置**

请按以下格式输入配置信息，每行一个参数：

target_type: group
target_id: 你的群组ID
message: 🌅 早上好！今天是{{date}}

请输入配置（可复制上面模板修改）："""
                    
                elif action_type == "api_call":
                    config_template = """🌐 **API调用增强配置**

使用高级配置向导，支持响应数据提取和自动消息发送功能。

请回复 'wizard' 使用可视化配置，或按以下格式输入基本配置：

method: GET
url: https://api.example.com/data
timeout: 30

请输入 'wizard' 或基本配置："""
                    
                elif action_type == "file_operation":
                    config_template = """📁 **文件操作配置**

请按以下格式输入：

operation: backup
source_path: ./data
target_path: ./backups/backup_{{timestamp}}.zip
compress: true

请输入配置："""
                    
                else:  # command
                    config_template = """💻 **命令执行配置**

⚠️ 注意：命令执行有安全风险，请谨慎使用

请按以下格式输入：

command: echo "Hello World"
working_dir: .
timeout: 60

请输入配置："""
                
                await event.send(event.plain_result(config_template))
                controller.stop()
            
            await get_action_type(event)
            
            # 获取动作配置
            @session_waiter(timeout=600, record_history_chains=False)
            async def get_action_config(controller: SessionController, event: AstrMessageEvent):
                config_text = event.message_str.strip() if event.message_str else ""
                
                if not config_text:
                    await event.send(event.plain_result("❌ 配置不能为空，请重新输入："))
                    controller.keep(timeout=600, reset_timeout=True)
                    return
                
                # 检查是否使用向导模式
                if config_text.lower() == 'wizard' and task_data.get('action_type') == 'api_call':
                    await event.send(event.plain_result("🧙‍♂️ **启动API配置向导**\n\n即将进入高级配置模式，支持响应数据提取和自动消息发送..."))
                    
                    # 调用高级API配置向导
                    action_config = {}
                    await self._configure_api_call_action_wizard(event, action_config, controller)
                    
                    task_data["action_config"] = action_config
                    
                    # 向导完成后直接跳到确认步骤
                    await self._show_task_creation_summary(event, task_data, controller)
                    return
                
                # 解析配置文本
                try:
                    config_dict = {}
                    for line in config_text.split('\n'):
                        line = line.strip()
                        if ':' in line:
                            key, value = line.split(':', 1)
                            key = key.strip()
                            value = value.strip()
                            
                            # 类型转换
                            if value.lower() == 'true':
                                value = True
                            elif value.lower() == 'false':
                                value = False
                            elif value.isdigit():
                                value = int(value)
                            
                            config_dict[key] = value
                    
                    if not config_dict:
                        await event.send(event.plain_result("❌ 配置格式错误，请检查格式后重新输入："))
                        controller.keep(timeout=600, reset_timeout=True)
                        return
                    
                    task_data["action_config"] = config_dict
                    
                    # 步骤4: 确认和保存
                    summary = f"""**步骤 4/4: 确认信息**

📋 **任务摘要：**
• 名称：{task_data['name']}
• 描述：{task_data['description']}
• 调度：{task_data.get('schedule_type', 'manual')}
• 动作：{task_data['action_type']}

是否确认创建此任务？
• 回复 **yes** 确认创建
• 回复 **no** 取消创建"""
                    
                    await event.send(event.plain_result(summary))
                    controller.stop()
                    
                except Exception as e:
                    await event.send(event.plain_result(f"❌ 配置解析错误：{str(e)}\n请检查格式后重新输入："))
                    controller.keep(timeout=600, reset_timeout=True)
                    return
            
            await get_action_config(event)
            
            # 确认创建
            @session_waiter(timeout=600, record_history_chains=False)
            async def confirm_creation(controller: SessionController, event: AstrMessageEvent):
                confirmation = event.message_str.strip().lower() if event.message_str else ""
                
                if confirmation == "yes":
                    # 创建任务对象
                    try:
                        # 构建完整的任务配置
                        full_task_config = {
                            "id": task_data["id"],
                            "name": task_data["name"],
                            "description": task_data["description"],
                            "enabled": True,
                            "schedule": {
                                "type": task_data.get("schedule_type", "manual"),
                                "config": task_data.get("schedule_config", {}),
                                "timezone": "Asia/Shanghai",
                                "enabled": True
                            },
                            "actions": [
                                {
                                    "type": task_data["action_type"],
                                    "config": task_data["action_config"],
                                    "conditions": []
                                }
                            ],
                            "group": task_data["group"],
                            "priority": task_data["priority"],
                            "retry_count": task_data["retry_count"],
                            "on_failure": task_data["on_failure"],
                            "created_by": event.get_sender_id() or "unknown",
                            "tags": ["可视化创建"]
                        }
                        
                        # 创建任务
                        task = Task.from_dict(full_task_config)
                        success = self.task_manager.add_task(task)
                        
                        if success:
                            self._save_tasks()
                            
                            await event.send(event.plain_result(f"""✅ **任务创建成功！**

• 任务ID：`{task.id}`
• 任务名称：{task.name}
• 状态：已启用

使用以下命令管理任务：
• `/task info {task.id}` - 查看详情
• `/task run {task.id}` - 手动执行
• `/task disable {task.id}` - 禁用任务"""))
                        else:
                            await event.send(event.plain_result("❌ 任务创建失败：任务ID已存在"))
                            
                    except Exception as e:
                        logger.error(f"创建任务失败: {e}", exc_info=True)
                        await event.send(event.plain_result(f"❌ 任务创建失败：{str(e)}"))
                        
                elif confirmation == "no":
                    await event.send(event.plain_result("❌ 任务创建已取消"))
                else:
                    await event.send(event.plain_result("❌ 请回复 yes 或 no："))
                    controller.keep(timeout=60, reset_timeout=True)
                    return
                
                controller.stop()
            
            await confirm_creation(event)
            
        except TimeoutError:
            yield event.plain_result("⏰ 操作超时，任务创建已取消")
        except Exception as e:
            logger.error(f"创建任务向导异常: {e}", exc_info=True)
            yield event.plain_result("😥 创建任务时发生异常")
    
    
    @task.command("edit")  
    async def edit_task(self, event: AstrMessageEvent, task_id: str):
        """编辑现有任务 - 可视化编辑"""
        try:
            task = self.task_manager.get_task(task_id)
            if not task:
                yield event.plain_result(f"❌ 任务不存在: {task_id}")
                return
            
            edit_menu = f"""🔧 **任务编辑菜单**

当前任务：**{task.name}** (`{task_id}`)

请选择要编辑的内容：

1️⃣ **基本信息** (名称、描述、分组)
2️⃣ **调度设置** (时间、频率)  
3️⃣ **动作配置** (执行内容)
4️⃣ **高级设置** (重试、失败处理)
5️⃣ **启用/禁用** 任务

请回复数字 1-5："""
            
            yield event.plain_result(edit_menu)
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def handle_edit_choice(controller: SessionController, event: AstrMessageEvent):
                choice = event.message_str.strip() if event.message_str else ""
                
                if choice == "1":
                    # 编辑基本信息
                    await self._edit_basic_info(event, task)
                elif choice == "2":
                    # 编辑调度设置
                    await self._edit_schedule_settings(event, task)
                elif choice == "3":
                    # 编辑动作配置
                    await self._edit_actions(event, task)
                elif choice == "4":
                    # 编辑高级设置
                    await self._edit_advanced_settings(event, task)
                elif choice == "5":
                    # 启用/禁用任务
                    current_status = "启用" if task.enabled else "禁用"
                    new_status = "禁用" if task.enabled else "启用"
                    
                    task.enabled = not task.enabled
                    task.schedule.enabled = task.enabled
                    task.updated_at = datetime.now()
                    self._save_tasks()
                    
                    await event.send(event.plain_result(f"✅ 任务已{new_status}"))
                else:
                    await event.send(event.plain_result("❌ 请输入有效数字 1-5"))
                
                controller.stop()
            
            await handle_edit_choice(event)
            
        except Exception as e:
            logger.error(f"编辑任务失败: {e}")
            yield event.plain_result("😥 编辑任务失败")
    
    async def _edit_basic_info(self, event: AstrMessageEvent, task: Task):
        """编辑任务基本信息"""
        try:
            current_info = f"""📝 **编辑基本信息**

当前信息：
• 名称：{task.name}
• 描述：{task.description}
• 分组：{task.group}
• 优先级：{task.priority}

请输入新的任务名称（回复 skip 跳过）："""
            
            await event.send(event.plain_result(current_info))
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_new_name(controller: SessionController, event: AstrMessageEvent):
                new_name = event.message_str.strip() if event.message_str else ""
                if new_name and new_name.lower() != "skip":
                    task.name = new_name
                
                await event.send(event.plain_result("请输入新的任务描述（回复 skip 跳过）："))
                controller.stop()
            
            await get_new_name(event)
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_new_description(controller: SessionController, event: AstrMessageEvent):
                new_desc = event.message_str.strip() if event.message_str else ""
                if new_desc and new_desc.lower() != "skip":
                    task.description = new_desc
                
                await event.send(event.plain_result("请输入新的分组名称（回复 skip 跳过）："))
                controller.stop()
            
            await get_new_description(event)
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_new_group(controller: SessionController, event: AstrMessageEvent):
                new_group = event.message_str.strip() if event.message_str else ""
                if new_group and new_group.lower() != "skip":
                    task.group = new_group
                
                task.updated_at = datetime.now()
                self._save_tasks()
                
                await event.send(event.plain_result(f"""✅ **基本信息更新完成**

新信息：
• 名称：{task.name}
• 描述：{task.description}
• 分组：{task.group}"""))
                controller.stop()
            
            await get_new_group(event)
            
        except Exception as e:
            logger.error(f"编辑基本信息失败: {e}")
            await event.send(event.plain_result("😥 编辑基本信息失败"))
    
    async def _edit_schedule_settings(self, event: AstrMessageEvent, task: Task):
        """编辑调度设置"""
        try:
            current_schedule = f"""⏰ **编辑调度设置**

当前调度：
• 类型：{task.schedule.type}
• 配置：{task.schedule.config}
• 时区：{task.schedule.timezone}
• 状态：{'启用' if task.schedule.enabled else '禁用'}

请选择新的调度类型：
1️⃣ **cron** - Cron表达式
2️⃣ **interval** - 固定间隔
3️⃣ **once** - 一次性任务
4️⃣ **manual** - 手动触发
5️⃣ **保持不变**

请回复数字 1-5："""
            
            await event.send(event.plain_result(current_schedule))
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_schedule_type(controller: SessionController, event: AstrMessageEvent):
                choice = event.message_str.strip() if event.message_str else ""
                
                if choice == "5":
                    await event.send(event.plain_result("✅ 调度设置保持不变"))
                    controller.stop()
                    return
                
                schedule_types = {"1": "cron", "2": "interval", "3": "once", "4": "manual"}
                
                if choice not in schedule_types:
                    await event.send(event.plain_result("❌ 请输入有效数字 1-5"))
                    controller.keep(timeout=60, reset_timeout=True)
                    return
                
                new_type = schedule_types[choice]
                
                if new_type == "cron":
                    await event.send(event.plain_result("请输入Cron表达式（如：0 9 * * * 表示每天9点）："))
                elif new_type == "interval":
                    await event.send(event.plain_result("请输入间隔时间（格式：30s, 5m, 2h, 1d）："))
                elif new_type == "once":
                    await event.send(event.plain_result("请输入执行时间（格式：2024-12-25 09:00:00）："))
                else:  # manual
                    task.schedule.type = "manual"
                    task.schedule.config = {"trigger": "manual"}
                    task.updated_at = datetime.now()
                    self._save_tasks()
                    await event.send(event.plain_result("✅ 已设置为手动触发"))
                    controller.stop()
                    return
                
                # 保存选择的类型，等待配置输入
                controller.data = {"type": new_type}
                controller.stop()
            
            await get_schedule_type(event)
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_schedule_config(controller: SessionController, event: AstrMessageEvent):
                if not hasattr(controller, 'data') or not controller.data:
                    await event.send(event.plain_result("❌ 调度类型丢失，请重新开始"))
                    controller.stop()
                    return
                
                schedule_type = controller.data.get("type")
                config_input = event.message_str.strip() if event.message_str else ""
                
                if not config_input:
                    await event.send(event.plain_result("❌ 配置不能为空，请重新输入："))
                    controller.keep(timeout=60, reset_timeout=True)
                    return
                
                try:
                    if schedule_type == "cron":
                        task.schedule.config = {"expression": config_input}
                    elif schedule_type == "interval":
                        # 解析间隔时间
                        if config_input.endswith('s'):
                            seconds = int(config_input[:-1])
                            task.schedule.config = {"seconds": seconds}
                        elif config_input.endswith('m'):
                            minutes = int(config_input[:-1])
                            task.schedule.config = {"seconds": minutes * 60}
                        elif config_input.endswith('h'):
                            hours = int(config_input[:-1])
                            task.schedule.config = {"seconds": hours * 3600}
                        elif config_input.endswith('d'):
                            days = int(config_input[:-1])
                            task.schedule.config = {"seconds": days * 86400}
                        else:
                            await event.send(event.plain_result("❌ 间隔格式错误，请使用如：30s, 5m, 2h, 1d"))
                            controller.keep(timeout=60, reset_timeout=True)
                            return
                    elif schedule_type == "once":
                        task.schedule.config = {"datetime": config_input}
                    
                    task.schedule.type = schedule_type
                    task.updated_at = datetime.now()
                    self._save_tasks()
                    
                    await event.send(event.plain_result(f"""✅ **调度设置更新完成**

新设置：
• 类型：{task.schedule.type}
• 配置：{task.schedule.config}"""))
                    
                except ValueError as e:
                    await event.send(event.plain_result(f"❌ 配置格式错误：{str(e)}"))
                
                controller.stop()
            
            await get_schedule_config(event)
            
        except Exception as e:
            logger.error(f"编辑调度设置失败: {e}")
            await event.send(event.plain_result("😥 编辑调度设置失败"))
    
    async def _edit_actions(self, event: AstrMessageEvent, task: Task):
        """编辑动作配置"""
        try:
            actions_info = "🎯 **编辑动作配置**\n\n当前动作列表：\n"
            
            for i, action in enumerate(task.actions, 1):
                actions_info += f"{i}. {action.type} - {len(action.conditions)}个条件\n"
            
            actions_info += f"""
操作选项：
1️⃣ **添加新动作**
2️⃣ **删除动作** (输入动作序号)
3️⃣ **修改动作** (输入动作序号)
4️⃣ **保持不变**

请选择操作："""
            
            await event.send(event.plain_result(actions_info))
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def handle_action_choice(controller: SessionController, event: AstrMessageEvent):
                choice = event.message_str.strip() if event.message_str else ""
                
                if choice == "1":
                    # 添加新动作
                    action_menu = """请选择动作类型：

1️⃣ **send_message** - 发送消息
2️⃣ **api_call** - API调用
3️⃣ **file_operation** - 文件操作
4️⃣ **command** - 命令执行

请回复数字 1-4："""
                    await event.send(event.plain_result(action_menu))
                    controller.data = {"operation": "add"}
                
                elif choice == "4":
                    await event.send(event.plain_result("✅ 动作配置保持不变"))
                    controller.stop()
                    return
                
                elif choice.isdigit():
                    action_index = int(choice) - 1
                    if 0 <= action_index < len(task.actions):
                        action_detail = f"""动作详情：
• 类型：{task.actions[action_index].type}
• 配置：{task.actions[action_index].config}

请选择操作：
1️⃣ **修改此动作**
2️⃣ **删除此动作**
3️⃣ **取消**

请回复数字 1-3："""
                        await event.send(event.plain_result(action_detail))
                        controller.data = {"operation": "modify", "index": action_index}
                    else:
                        await event.send(event.plain_result("❌ 动作序号无效"))
                        controller.keep(timeout=60, reset_timeout=True)
                        return
                else:
                    await event.send(event.plain_result("❌ 请输入有效选项"))
                    controller.keep(timeout=60, reset_timeout=True)
                    return
                
                controller.stop()
            
            await handle_action_choice(event)
            
            @session_waiter(timeout=120, record_history_chains=False)
            async def handle_action_operation(controller: SessionController, event: AstrMessageEvent):
                if not hasattr(controller, 'data') or not controller.data:
                    await event.send(event.plain_result("❌ 操作信息丢失，请重新开始"))
                    controller.stop()
                    return
                
                operation = controller.data.get("operation")
                
                if operation == "add":
                    # 添加新动作
                    await self._handle_add_action(event, task, controller)
                elif operation == "modify":
                    # 修改现有动作
                    action_index = controller.data.get("index")
                    choice = event.message_str.strip() if event.message_str else ""
                    
                    if choice == "1":
                        # 修改动作
                        await self._handle_modify_action(event, task, action_index, controller)
                    elif choice == "2":
                        # 删除动作
                        if 0 <= action_index < len(task.actions):
                            deleted_action = task.actions.pop(action_index)
                            task.updated_at = datetime.now()
                            self._save_tasks()
                            await event.send(event.plain_result(f"✅ 已删除动作：{deleted_action.type}"))
                        else:
                            await event.send(event.plain_result("❌ 动作索引无效"))
                    elif choice == "3":
                        await event.send(event.plain_result("❌ 操作已取消"))
                    else:
                        await event.send(event.plain_result("❌ 请输入有效数字 1-3"))
                        controller.keep(timeout=60, reset_timeout=True)
                        return
                else:
                    await event.send(event.plain_result("❌ 未知操作"))
                
                controller.stop()
            
            await handle_action_operation(event)
            
        except Exception as e:
            logger.error(f"编辑动作配置失败: {e}")
            await event.send(event.plain_result("😥 编辑动作配置失败"))
    
    async def _edit_advanced_settings(self, event: AstrMessageEvent, task: Task):
        """编辑高级设置"""
        try:
            current_settings = f"""⚙️ **编辑高级设置**

当前设置：
• 重试次数：{task.retry_count}
• 重试延迟：{task.retry_delay}秒
• 失败处理：{task.on_failure}
• 优先级：{task.priority}

请输入新的重试次数（当前：{task.retry_count}，回复 skip 跳过）："""
            
            await event.send(event.plain_result(current_settings))
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_retry_count(controller: SessionController, event: AstrMessageEvent):
                retry_input = event.message_str.strip() if event.message_str else ""
                if retry_input and retry_input.lower() != "skip":
                    try:
                        task.retry_count = int(retry_input)
                    except ValueError:
                        await event.send(event.plain_result("❌ 请输入有效数字"))
                        controller.keep(timeout=60, reset_timeout=True)
                        return
                
                await event.send(event.plain_result(f"请输入新的重试延迟秒数（当前：{task.retry_delay}，回复 skip 跳过）："))
                controller.stop()
            
            await get_retry_count(event)
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_retry_delay(controller: SessionController, event: AstrMessageEvent):
                delay_input = event.message_str.strip() if event.message_str else ""
                if delay_input and delay_input.lower() != "skip":
                    try:
                        task.retry_delay = int(delay_input)
                    except ValueError:
                        await event.send(event.plain_result("❌ 请输入有效数字"))
                        controller.keep(timeout=60, reset_timeout=True)
                        return
                
                failure_menu = f"""请选择失败处理方式（当前：{task.on_failure}）：

1️⃣ **log** - 仅记录日志
2️⃣ **notify** - 发送通知
3️⃣ **disable** - 禁用任务
4️⃣ **skip** - 保持不变

请回复数字 1-4："""
                await event.send(event.plain_result(failure_menu))
                controller.stop()
            
            await get_retry_delay(event)
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_failure_handling(controller: SessionController, event: AstrMessageEvent):
                choice = event.message_str.strip() if event.message_str else ""
                
                failure_options = {"1": "log", "2": "notify", "3": "disable"}
                if choice in failure_options:
                    task.on_failure = failure_options[choice]
                elif choice != "4":
                    await event.send(event.plain_result("❌ 请输入有效数字 1-4"))
                    controller.keep(timeout=60, reset_timeout=True)
                    return
                
                task.updated_at = datetime.now()
                self._save_tasks()
                
                await event.send(event.plain_result(f"""✅ **高级设置更新完成**

新设置：
• 重试次数：{task.retry_count}
• 重试延迟：{task.retry_delay}秒
• 失败处理：{task.on_failure}
• 优先级：{task.priority}"""))
                controller.stop()
            
            await get_failure_handling(event)
            
        except Exception as e:
            logger.error(f"编辑高级设置失败: {e}")
            await event.send(event.plain_result("😥 编辑高级设置失败"))
    
    async def _handle_add_action(self, event: AstrMessageEvent, task: Task, controller: SessionController):
        """处理添加新动作"""
        try:
            choice = event.message_str.strip() if event.message_str else ""
            action_types = {"1": "send_message", "2": "api_call", "3": "file_operation", "4": "command"}
            
            if choice not in action_types:
                await event.send(event.plain_result("❌ 请输入有效数字 1-4"))
                controller.keep(timeout=60, reset_timeout=True)
                return
            
            action_type = action_types[choice]
            
            if action_type == "send_message":
                await self._configure_send_message_action(event, task, controller)
            elif action_type == "api_call":
                await self._configure_api_call_action(event, task, controller)
            elif action_type == "file_operation":
                await self._configure_file_operation_action(event, task, controller)
            elif action_type == "command":
                await self._configure_command_action(event, task, controller)
                
        except Exception as e:
            logger.error(f"添加动作失败: {e}")
            await event.send(event.plain_result("😥 添加动作失败"))
    
    async def _handle_modify_action(self, event: AstrMessageEvent, task: Task, action_index: int, controller: SessionController):
        """处理修改现有动作"""
        try:
            if not (0 <= action_index < len(task.actions)):
                await event.send(event.plain_result("❌ 动作索引无效"))
                return
            
            existing_action = task.actions[action_index]
            action_type = existing_action.type
            
            await event.send(event.plain_result(f"🔧 修改动作：{action_type}"))
            
            if action_type == "send_message":
                await self._configure_send_message_action(event, task, controller, existing_action, action_index)
            elif action_type == "api_call":
                await self._configure_api_call_action(event, task, controller, existing_action, action_index)
            elif action_type == "file_operation":
                await self._configure_file_operation_action(event, task, controller, existing_action, action_index)
            elif action_type == "command":
                await self._configure_command_action(event, task, controller, existing_action, action_index)
                
        except Exception as e:
            logger.error(f"修改动作失败: {e}")
            await event.send(event.plain_result("😥 修改动作失败"))
    
    async def _configure_send_message_action(self, event: AstrMessageEvent, task: Task, controller: SessionController, existing_action=None, action_index=None):
        """配置发送消息动作"""
        try:
            if existing_action:
                current_config = existing_action.config
                action_text = f"""📨 **修改发送消息动作**

当前配置：
• 平台：{current_config.get('platform', 'aiocqhttp')}
• 目标类型：{current_config.get('target_type', 'group')}
• 目标ID：{current_config.get('target_id', '')}
• 消息内容：{current_config.get('message', '')[:50]}...

请输入新的目标类型（group/private/channel，回复 skip 保持不变）："""
            else:
                action_text = """📨 **添加发送消息动作**

请输入目标类型（group/private/channel）："""
            
            await event.send(event.plain_result(action_text))
            
            action_config = existing_action.config.copy() if existing_action else {}
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_target_type(controller: SessionController, event: AstrMessageEvent):
                target_type = event.message_str.strip() if event.message_str else ""
                if target_type and target_type.lower() != "skip":
                    if target_type not in ["group", "private", "channel"]:
                        await event.send(event.plain_result("❌ 目标类型必须是 group、private 或 channel"))
                        controller.keep(timeout=60, reset_timeout=True)
                        return
                    action_config["target_type"] = target_type
                
                current_id = action_config.get('target_id', '')
                await event.send(event.plain_result(f"请输入目标ID（{'当前：' + current_id if current_id else '如群组ID或用户ID'}，回复 skip 跳过）："))
                controller.stop()
            
            await get_target_type(event)
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_target_id(controller: SessionController, event: AstrMessageEvent):
                target_id = event.message_str.strip() if event.message_str else ""
                if target_id and target_id.lower() != "skip":
                    action_config["target_id"] = target_id
                
                current_msg = action_config.get('message', '')
                await event.send(event.plain_result(f"请输入消息内容（{'当前：' + current_msg[:30] + '...' if current_msg else '支持变量如{{date}}、{{time}}等'}，回复 skip 跳过）："))
                controller.stop()
            
            await get_target_id(event)
            
            @session_waiter(timeout=120, record_history_chains=False)
            async def get_message_content(controller: SessionController, event: AstrMessageEvent):
                message_content = event.message_str.strip() if event.message_str else ""
                if message_content and message_content.lower() != "skip":
                    action_config["message"] = message_content
                
                # 设置默认值
                action_config.setdefault("platform", "aiocqhttp")
                action_config.setdefault("target_type", "group")
                
                # 创建或更新动作
                from .models.task import TaskAction
                new_action = TaskAction(type="send_message", config=action_config, conditions=[])
                
                if existing_action and action_index is not None:
                    task.actions[action_index] = new_action
                    operation = "修改"
                else:
                    task.actions.append(new_action)
                    operation = "添加"
                
                task.updated_at = datetime.now()
                self._save_tasks()
                
                await event.send(event.plain_result(f"""✅ **{operation}发送消息动作成功**

配置：
• 平台：{action_config.get('platform')}
• 目标类型：{action_config.get('target_type')}
• 目标ID：{action_config.get('target_id')}
• 消息：{action_config.get('message', '')[:50]}{'...' if len(action_config.get('message', '')) > 50 else ''}"""))
                controller.stop()
            
            await get_message_content(event)
            
        except Exception as e:
            logger.error(f"配置发送消息动作失败: {e}")
            await event.send(event.plain_result("😥 配置发送消息动作失败"))
    
    async def _configure_api_call_action(self, event: AstrMessageEvent, task: Task, controller: SessionController, existing_action=None, action_index=None):
        """配置API调用动作"""
        try:
            if existing_action:
                current_config = existing_action.config
                action_text = f"""🌐 **修改API调用动作**

当前配置：
• 方法：{current_config.get('method', 'GET')}
• URL：{current_config.get('url', '')}
• 超时：{current_config.get('timeout', 30)}秒

请输入新的HTTP方法（GET/POST/PUT/DELETE，回复 skip 保持不变）："""
            else:
                action_text = """🌐 **添加API调用动作**

请输入HTTP方法（GET/POST/PUT/DELETE）："""
            
            await event.send(event.plain_result(action_text))
            
            action_config = existing_action.config.copy() if existing_action else {}
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_method(controller: SessionController, event: AstrMessageEvent):
                method = event.message_str.strip().upper() if event.message_str else ""
                if method and method != "SKIP":
                    if method not in ["GET", "POST", "PUT", "DELETE"]:
                        await event.send(event.plain_result("❌ HTTP方法必须是 GET、POST、PUT 或 DELETE"))
                        controller.keep(timeout=60, reset_timeout=True)
                        return
                    action_config["method"] = method
                
                current_url = action_config.get('url', '')
                await event.send(event.plain_result(f"请输入API URL（{'当前：' + current_url if current_url else '如：https://api.example.com/data'}，回复 skip 跳过）："))
                controller.stop()
            
            await get_method(event)
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_url(controller: SessionController, event: AstrMessageEvent):
                url = event.message_str.strip() if event.message_str else ""
                if url and url.lower() != "skip":
                    action_config["url"] = url
                
                current_timeout = action_config.get('timeout', 30)
                await event.send(event.plain_result(f"请输入超时时间（秒，当前：{current_timeout}，回复 skip 跳过）："))
                controller.stop()
            
            await get_url(event)
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_timeout(controller: SessionController, event: AstrMessageEvent):
                timeout_input = event.message_str.strip() if event.message_str else ""
                if timeout_input and timeout_input.lower() != "skip":
                    try:
                        action_config["timeout"] = int(timeout_input)
                    except ValueError:
                        await event.send(event.plain_result("❌ 超时时间必须是数字"))
                        controller.keep(timeout=60, reset_timeout=True)
                        return
                
                # 询问是否需要处理响应数据
                response_menu = """🔍 **API响应处理配置**

是否需要从API响应中提取数据并发送消息？

1️⃣ **是** - 配置响应数据提取和消息发送
2️⃣ **否** - 仅调用API，不处理响应
3️⃣ **skip** - 保持当前配置

请选择："""
                await event.send(event.plain_result(response_menu))
                controller.stop()
            
            await get_timeout(event)
            
            @session_waiter(timeout=600, record_history_chains=False)
            async def get_response_handling(controller: SessionController, event: AstrMessageEvent):
                choice = event.message_str.strip() if event.message_str else ""
                
                if choice == "1":
                    await self._configure_api_response_handling(event, action_config, task, existing_action, action_index, controller)
                elif choice == "2" or choice.lower() == "skip":
                    await self._finalize_api_action(action_config, task, existing_action, action_index, event)
                else:
                    await event.send(event.plain_result("❌ 请选择 1、2 或 skip"))
                    controller.keep(timeout=60, reset_timeout=True)
                    return
                
                controller.stop()
            
            await get_response_handling(event)
            
        except Exception as e:
            logger.error(f"配置API调用动作失败: {e}")
            await event.send(event.plain_result("😥 配置API调用动作失败"))
    
    async def _configure_file_operation_action(self, event: AstrMessageEvent, task: Task, controller: SessionController, existing_action=None, action_index=None):
        """配置文件操作动作"""
        try:
            if existing_action:
                current_config = existing_action.config
                action_text = f"""📁 **修改文件操作动作**

当前配置：
• 操作类型：{current_config.get('operation', '')}
• 源路径：{current_config.get('source_path', '')}
• 目标路径：{current_config.get('target_path', '')}

请选择新的操作类型（回复 skip 保持不变）："""
            else:
                action_text = """📁 **添加文件操作动作**

请选择操作类型："""
            
            operation_menu = f"""{action_text}

1️⃣ **backup** - 备份文件/目录
2️⃣ **delete** - 删除文件/目录
3️⃣ **move** - 移动文件/目录
4️⃣ **copy** - 复制文件/目录
5️⃣ **cleanup** - 清理过期文件

请回复数字 1-5："""
            
            await event.send(event.plain_result(operation_menu))
            
            action_config = existing_action.config.copy() if existing_action else {}
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_operation(controller: SessionController, event: AstrMessageEvent):
                choice = event.message_str.strip() if event.message_str else ""
                
                if choice != "skip":
                    operations = {"1": "backup", "2": "delete", "3": "move", "4": "copy", "5": "cleanup"}
                    if choice not in operations:
                        await event.send(event.plain_result("❌ 请输入有效数字 1-5"))
                        controller.keep(timeout=60, reset_timeout=True)
                        return
                    action_config["operation"] = operations[choice]
                
                current_source = action_config.get('source_path', '')
                await event.send(event.plain_result(f"请输入源路径（{'当前：' + current_source if current_source else '如：/path/to/source'}，回复 skip 跳过）："))
                controller.stop()
            
            await get_operation(event)
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_source_path(controller: SessionController, event: AstrMessageEvent):
                source_path = event.message_str.strip() if event.message_str else ""
                if source_path and source_path.lower() != "skip":
                    action_config["source_path"] = source_path
                
                operation = action_config.get('operation', '')
                if operation in ['move', 'copy', 'backup']:
                    current_target = action_config.get('target_path', '')
                    await event.send(event.plain_result(f"请输入目标路径（{'当前：' + current_target if current_target else '如：/path/to/target'}，回复 skip 跳过）："))
                else:
                    # 删除和清理操作不需要目标路径
                    await self._finalize_file_operation(action_config, task, existing_action, action_index, event, controller)
                    return
                
                controller.stop()
            
            await get_source_path(event)
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_target_path(controller: SessionController, event: AstrMessageEvent):
                target_path = event.message_str.strip() if event.message_str else ""
                if target_path and target_path.lower() != "skip":
                    action_config["target_path"] = target_path
                
                await self._finalize_file_operation(action_config, task, existing_action, action_index, event, controller)
                controller.stop()
            
            await get_target_path(event)
            
        except Exception as e:
            logger.error(f"配置文件操作动作失败: {e}")
            await event.send(event.plain_result("😥 配置文件操作动作失败"))
    
    async def _finalize_file_operation(self, action_config, task, existing_action, action_index, event, controller):
        """完成文件操作配置"""
        try:
            # 设置默认值
            action_config.setdefault("compress", False)
            
            # 创建或更新动作
            from .models.task import TaskAction
            new_action = TaskAction(type="file_operation", config=action_config, conditions=[])
            
            if existing_action and action_index is not None:
                task.actions[action_index] = new_action
                operation = "修改"
            else:
                task.actions.append(new_action)
                operation = "添加"
            
            task.updated_at = datetime.now()
            self._save_tasks()
            
            await event.send(event.plain_result(f"""✅ **{operation}文件操作动作成功**

配置：
• 操作：{action_config.get('operation')}
• 源路径：{action_config.get('source_path')}
• 目标路径：{action_config.get('target_path', '无')}"""))
            
        except Exception as e:
            logger.error(f"完成文件操作配置失败: {e}")
            await event.send(event.plain_result("😥 完成文件操作配置失败"))
    
    async def _configure_command_action(self, event: AstrMessageEvent, task: Task, controller: SessionController, existing_action=None, action_index=None):
        """配置命令执行动作"""
        try:
            if existing_action:
                current_config = existing_action.config
                action_text = f"""💻 **修改命令执行动作**

当前配置：
• 命令：{current_config.get('command', '')}
• 工作目录：{current_config.get('working_dir', '.')}
• 超时：{current_config.get('timeout', 60)}秒

⚠️ **安全提醒：命令执行有安全风险，请谨慎配置**

请输入新的命令（回复 skip 保持不变）："""
            else:
                action_text = """💻 **添加命令执行动作**

⚠️ **安全提醒：命令执行有安全风险，请谨慎配置**

请输入要执行的命令："""
            
            await event.send(event.plain_result(action_text))
            
            action_config = existing_action.config.copy() if existing_action else {}
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_command(controller: SessionController, event: AstrMessageEvent):
                command = event.message_str.strip() if event.message_str else ""
                if command and command.lower() != "skip":
                    action_config["command"] = command
                
                current_dir = action_config.get('working_dir', '.')
                await event.send(event.plain_result(f"请输入工作目录（当前：{current_dir}，回复 skip 跳过）："))
                controller.stop()
            
            await get_command(event)
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_working_dir(controller: SessionController, event: AstrMessageEvent):
                working_dir = event.message_str.strip() if event.message_str else ""
                if working_dir and working_dir.lower() != "skip":
                    action_config["working_dir"] = working_dir
                
                current_timeout = action_config.get('timeout', 60)
                await event.send(event.plain_result(f"请输入超时时间（秒，当前：{current_timeout}，回复 skip 跳过）："))
                controller.stop()
            
            await get_working_dir(event)
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_command_timeout(controller: SessionController, event: AstrMessageEvent):
                timeout_input = event.message_str.strip() if event.message_str else ""
                if timeout_input and timeout_input.lower() != "skip":
                    try:
                        action_config["timeout"] = int(timeout_input)
                    except ValueError:
                        await event.send(event.plain_result("❌ 超时时间必须是数字"))
                        controller.keep(timeout=60, reset_timeout=True)
                        return
                
                # 设置默认值
                action_config.setdefault("working_dir", ".")
                action_config.setdefault("timeout", 60)
                action_config.setdefault("capture_output", True)
                
                # 创建或更新动作
                from .models.task import TaskAction
                new_action = TaskAction(type="command", config=action_config, conditions=[])
                
                if existing_action and action_index is not None:
                    task.actions[action_index] = new_action
                    operation = "修改"
                else:
                    task.actions.append(new_action)
                    operation = "添加"
                
                task.updated_at = datetime.now()
                self._save_tasks()
                
                await event.send(event.plain_result(f"""✅ **{operation}命令执行动作成功**

配置：
• 命令：{action_config.get('command')}
• 工作目录：{action_config.get('working_dir')}
• 超时：{action_config.get('timeout')}秒

⚠️ **请确保命令安全可靠**"""))
                controller.stop()
            
            await get_command_timeout(event)
            
        except Exception as e:
            logger.error(f"配置命令执行动作失败: {e}")
            await event.send(event.plain_result("😥 配置命令执行动作失败"))
    
    async def _configure_api_response_handling(self, event: AstrMessageEvent, action_config: dict, task: Task, existing_action, action_index, controller: SessionController):
        """配置API响应处理"""
        try:
            response_config_text = """📋 **配置API响应数据提取**

请配置如何处理API响应：

1. **JSON字段提取**：从响应JSON中提取指定字段
2. **消息模板**：定义发送消息的格式

请输入要提取的JSON字段路径（用英文逗号分隔多个字段）：
示例：
• data.name,data.price,status
• items[0].title,items[0].url
• weather.temp,weather.desc

字段路径："""
            
            await event.send(event.plain_result(response_config_text))
            
            @session_waiter(timeout=120, record_history_chains=False)
            async def get_extract_fields(controller: SessionController, event: AstrMessageEvent):
                fields_input = event.message_str.strip() if event.message_str else ""
                if not fields_input:
                    await event.send(event.plain_result("❌ 请输入至少一个字段路径"))
                    controller.keep(timeout=120, reset_timeout=True)
                    return
                
                # 解析字段路径
                field_paths = [field.strip() for field in fields_input.split(',') if field.strip()]
                action_config["extract_fields"] = field_paths
                
                template_help = f"""📝 **配置消息模板**

已配置提取字段：{', '.join(field_paths)}

请输入消息模板，使用 {{字段名}} 来引用提取的数据：

示例：
• 商品：{{name}} 价格：￥{{price}} 状态：{{status}}
• 今日天气：{{temp}}°C，{{desc}}
• 新闻：{{title}} 链接：{{url}}

支持的变量：
• {{字段名}} - API响应字段值
• {{timestamp}} - 当前时间戳
• {{date}} - 当前日期
• {{time}} - 当前时间

消息模板："""
                
                await event.send(event.plain_result(template_help))
                controller.stop()
            
            await get_extract_fields(event)
            
            @session_waiter(timeout=120, record_history_chains=False)
            async def get_message_template(controller: SessionController, event: AstrMessageEvent):
                template = event.message_str.strip() if event.message_str else ""
                if not template:
                    await event.send(event.plain_result("❌ 消息模板不能为空"))
                    controller.keep(timeout=120, reset_timeout=True)
                    return
                
                action_config["message_template"] = template
                
                # 询问发送目标
                target_config = """🎯 **配置消息发送目标**

请配置将提取的数据发送到哪里：

请输入目标类型（group/private/channel）："""
                
                await event.send(event.plain_result(target_config))
                controller.stop()
            
            await get_message_template(event)
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_send_target_type(controller: SessionController, event: AstrMessageEvent):
                target_type = event.message_str.strip() if event.message_str else ""
                if target_type not in ["group", "private", "channel"]:
                    await event.send(event.plain_result("❌ 目标类型必须是 group、private 或 channel"))
                    controller.keep(timeout=60, reset_timeout=True)
                    return
                
                action_config["send_target_type"] = target_type
                
                await event.send(event.plain_result(f"请输入目标ID（{'群组ID' if target_type == 'group' else '用户ID' if target_type == 'private' else '频道ID'}）："))
                controller.stop()
            
            await get_send_target_type(event)
            
            @session_waiter(timeout=60, record_history_chains=False)
            async def get_send_target_id(controller: SessionController, event: AstrMessageEvent):
                target_id = event.message_str.strip() if event.message_str else ""
                if not target_id:
                    await event.send(event.plain_result("❌ 目标ID不能为空"))
                    controller.keep(timeout=60, reset_timeout=True)
                    return
                
                action_config["send_target_id"] = target_id
                action_config["send_platform"] = "aiocqhttp"  # 默认平台
                
                # 完成配置
                await self._finalize_api_action(action_config, task, existing_action, action_index, event)
                controller.stop()
            
            await get_send_target_id(event)
            
        except Exception as e:
            logger.error(f"配置API响应处理失败: {e}")
            await event.send(event.plain_result("😥 配置API响应处理失败"))
    
    async def _finalize_api_action(self, action_config: dict, task: Task, existing_action, action_index, event: AstrMessageEvent):
        """完成API动作配置"""
        try:
            # 设置默认值
            action_config.setdefault("method", "GET")
            action_config.setdefault("timeout", 30)
            action_config.setdefault("expected_status", 200)
            
            # 创建或更新动作
            from .models.task import TaskAction
            new_action = TaskAction(type="api_call", config=action_config, conditions=[])
            
            if existing_action and action_index is not None and task:
                task.actions[action_index] = new_action
                operation = "修改"
                task.updated_at = datetime.now()
                self._save_tasks()
            elif task:
                task.actions.append(new_action)
                operation = "添加"
                task.updated_at = datetime.now()
                self._save_tasks()
            else:
                operation = "配置完成"
            
            # 显示配置摘要
            config_summary = f"""✅ **{operation}API调用动作成功**

基本配置：
• 方法：{action_config.get('method')}
• URL：{action_config.get('url')}
• 超时：{action_config.get('timeout')}秒"""
            
            # 如果配置了响应处理，显示详细信息
            if action_config.get('extract_fields'):
                config_summary += f"""

响应处理配置：
• 提取字段：{', '.join(action_config.get('extract_fields', []))}
• 消息模板：{action_config.get('message_template', '')[:50]}{'...' if len(action_config.get('message_template', '')) > 50 else ''}
• 发送目标：{action_config.get('send_target_type')}:{action_config.get('send_target_id')}"""
            
            await event.send(event.plain_result(config_summary))
            
        except Exception as e:
            logger.error(f"完成API动作配置失败: {e}")
            await event.send(event.plain_result("😥 完成API动作配置失败"))
    
    async def _configure_api_call_action_wizard(self, event: AstrMessageEvent, action_config: dict, controller: SessionController):
        """创建任务向导中的API配置向导"""
        try:
            await event.send(event.plain_result("🌐 **步骤1: 基本API配置**\n\n请输入HTTP方法（GET/POST/PUT/DELETE）："))
            
            @session_waiter(timeout=600, record_history_chains=False)  # 10分钟超时
            async def get_method(controller: SessionController, event: AstrMessageEvent):
                method = event.message_str.strip().upper() if event.message_str else ""
                if method not in ["GET", "POST", "PUT", "DELETE"]:
                    await event.send(event.plain_result("❌ HTTP方法必须是 GET、POST、PUT 或 DELETE"))
                    controller.keep(timeout=600, reset_timeout=True)
                    return
                action_config["method"] = method
                await event.send(event.plain_result("请输入API URL："))
                controller.stop()
            
            await get_method(event)
            
            @session_waiter(timeout=600, record_history_chains=False)  # 10分钟超时
            async def get_url(controller: SessionController, event: AstrMessageEvent):
                url = event.message_str.strip() if event.message_str else ""
                if not url:
                    await event.send(event.plain_result("❌ URL不能为空"))
                    controller.keep(timeout=600, reset_timeout=True)
                    return
                action_config["url"] = url
                await event.send(event.plain_result("请输入超时时间（秒，直接回车默认30秒）："))
                controller.stop()
            
            await get_url(event)
            
            @session_waiter(timeout=600, record_history_chains=False)  # 10分钟超时
            async def get_timeout(controller: SessionController, event: AstrMessageEvent):
                timeout_input = event.message_str.strip() if event.message_str else ""
                if timeout_input:
                    try:
                        action_config["timeout"] = int(timeout_input)
                    except ValueError:
                        action_config["timeout"] = 30
                else:
                    action_config["timeout"] = 30
                
                response_menu = """🔍 **步骤2: 响应处理配置**

是否需要从API响应中提取数据并发送消息？

1️⃣ **是** - 配置数据提取和自动消息发送
2️⃣ **否** - 仅调用API，不处理响应

请选择 1 或 2："""
                await event.send(event.plain_result(response_menu))
                controller.stop()
            
            await get_timeout(event)
            
            @session_waiter(timeout=600, record_history_chains=False)  # 10分钟超时
            async def get_response_choice(controller: SessionController, event: AstrMessageEvent):
                choice = event.message_str.strip() if event.message_str else ""
                if choice == "1":
                    # 配置响应处理
                    await self._configure_wizard_response_handling(event, action_config, controller)
                elif choice == "2":
                    # 完成基本配置
                    action_config.setdefault("expected_status", 200)
                    await event.send(event.plain_result("✅ API配置完成"))
                    controller.stop()
                else:
                    await event.send(event.plain_result("❌ 请选择 1 或 2"))
                    controller.keep(timeout=600, reset_timeout=True)
                    return
                controller.stop()
            
            await get_response_choice(event)
            
        except Exception as e:
            logger.error(f"API配置向导失败: {e}")
            await event.send(event.plain_result("😥 API配置向导失败"))
    
    async def _configure_wizard_response_handling(self, event: AstrMessageEvent, action_config: dict, controller: SessionController):
        """向导模式的响应处理配置"""
        try:
            await event.send(event.plain_result("""📋 **步骤3: 数据提取配置**

请输入要从API响应中提取的字段路径，用逗号分隔：

示例：
• data.name,data.price
• items[0].title,items[0].url
• weather.temp,weather.desc

字段路径："""))
            
            @session_waiter(timeout=600, record_history_chains=False)  # 10分钟超时
            async def get_fields(controller: SessionController, event: AstrMessageEvent):
                fields_input = event.message_str.strip() if event.message_str else ""
                if not fields_input:
                    await event.send(event.plain_result("❌ 字段路径不能为空"))
                    controller.keep(timeout=600, reset_timeout=True)
                    return
                
                field_paths = [field.strip() for field in fields_input.split(',') if field.strip()]
                action_config["extract_fields"] = field_paths
                
                await event.send(event.plain_result(f"""📝 **步骤4: 消息模板**

已配置提取字段：{', '.join(field_paths)}

请输入消息模板，使用 {{字段名}} 引用数据：

示例：
• 商品：{{name}} 价格：￥{{price}}
• 天气：{{temp}}°C，{{desc}}

消息模板："""))
                controller.stop()
            
            await get_fields(event)
            
            @session_waiter(timeout=600, record_history_chains=False)  # 10分钟超时
            async def get_template(controller: SessionController, event: AstrMessageEvent):
                template = event.message_str.strip() if event.message_str else ""
                if not template:
                    await event.send(event.plain_result("❌ 消息模板不能为空"))
                    controller.keep(timeout=600, reset_timeout=True)
                    return
                
                action_config["message_template"] = template
                await event.send(event.plain_result("🎯 **步骤5: 发送目标**\n\n请输入目标类型（group/private）："))
                controller.stop()
            
            await get_template(event)
            
            @session_waiter(timeout=600, record_history_chains=False)  # 10分钟超时
            async def get_target(controller: SessionController, event: AstrMessageEvent):
                target_type = event.message_str.strip() if event.message_str else ""
                if target_type not in ["group", "private"]:
                    await event.send(event.plain_result("❌ 目标类型必须是 group 或 private"))
                    controller.keep(timeout=600, reset_timeout=True)
                    return
                
                action_config["send_target_type"] = target_type
                await event.send(event.plain_result(f"请输入{'群组ID' if target_type == 'group' else '用户ID'}："))
                controller.stop()
            
            await get_target(event)
            
            @session_waiter(timeout=600, record_history_chains=False)  # 10分钟超时
            async def get_target_id(controller: SessionController, event: AstrMessageEvent):
                target_id = event.message_str.strip() if event.message_str else ""
                if not target_id:
                    await event.send(event.plain_result("❌ 目标ID不能为空"))
                    controller.keep(timeout=600, reset_timeout=True)
                    return
                
                action_config["send_target_id"] = target_id
                action_config["send_platform"] = "aiocqhttp"
                action_config.setdefault("expected_status", 200)
                
                await event.send(event.plain_result("✅ **API配置向导完成**\n\n已配置：API调用 + 数据提取 + 自动消息发送"))
                controller.stop()
            
            await get_target_id(event)
            
        except Exception as e:
            logger.error(f"响应处理配置失败: {e}")
            await event.send(event.plain_result("😥 响应处理配置失败"))
    
    async def _show_task_creation_summary(self, event: AstrMessageEvent, task_data: dict, controller: SessionController):
        """显示任务创建摘要并处理确认"""
        try:
            # 生成配置摘要
            action_config = task_data.get("action_config", {})
            action_summary = f"• 动作：{task_data['action_type']}"
            
            if task_data['action_type'] == 'api_call':
                action_summary += f"\n• API: {action_config.get('method', 'GET')} {action_config.get('url', '')}"
                if action_config.get('extract_fields'):
                    action_summary += f"\n• 数据提取：{len(action_config.get('extract_fields', []))}个字段"
                    action_summary += f"\n• 自动发送：{action_config.get('send_target_type', '')}:{action_config.get('send_target_id', '')}"
            
            summary = f"""**步骤 4/4: 确认信息**

📋 **任务摘要：**
• 名称：{task_data['name']}
• 描述：{task_data['description']}
• 调度：{task_data.get('schedule_type', 'manual')}
{action_summary}

是否确认创建此任务？
• 回复 **yes** 确认创建
• 回复 **no** 取消创建"""
            
            await event.send(event.plain_result(summary))
            
            # 等待用户确认
            @session_waiter(timeout=600, record_history_chains=False)
            async def confirm_wizard_creation(controller: SessionController, event: AstrMessageEvent):
                confirmation = event.message_str.strip().lower() if event.message_str else ""
                
                if confirmation == "yes":
                    # 创建任务
                    await self._create_task_from_data(event, task_data)
                elif confirmation == "no":
                    await event.send(event.plain_result("❌ 任务创建已取消"))
                else:
                    await event.send(event.plain_result("❌ 请回复 yes 或 no："))
                    controller.keep(timeout=600, reset_timeout=True)
                    return
                
                controller.stop()
            
            await confirm_wizard_creation(event)
            
        except Exception as e:
            logger.error(f"显示任务摘要失败: {e}")
            await event.send(event.plain_result("😥 显示任务摘要失败"))
    
    async def _create_task_from_data(self, event: AstrMessageEvent, task_data: dict):
        """从任务数据创建任务"""
        try:
            # 构建完整的任务配置
            full_task_config = {
                "id": task_data["id"],
                "name": task_data["name"],
                "description": task_data["description"],
                "enabled": True,
                "schedule": {
                    "type": task_data.get("schedule_type", "manual"),
                    "config": task_data.get("schedule_config", {}),
                    "timezone": "Asia/Shanghai",
                    "enabled": True
                },
                "actions": [
                    {
                        "type": task_data["action_type"],
                        "config": task_data["action_config"],
                        "conditions": []
                    }
                ],
                "group": task_data.get("group", "custom"),
                "priority": task_data.get("priority", 1),
                "retry_count": task_data.get("retry_count", 3),
                "on_failure": task_data.get("on_failure", "log"),
                "created_by": event.get_sender_id() or "unknown",
                "tags": ["可视化创建"]
            }
            
            # 创建任务
            task = Task.from_dict(full_task_config)
            success = self.task_manager.add_task(task)
            
            if success:
                self._save_tasks()
                
                # 生成成功消息
                success_message = f"""✅ **任务创建成功！**

• 任务ID：`{task.id}`
• 任务名称：{task.name}
• 状态：已启用

使用以下命令管理任务：
• `/task info {task.id}` - 查看详情
• `/task run {task.id}` - 手动执行
• `/task disable {task.id}` - 禁用任务"""

                # 如果是API调用且有数据提取，添加特殊说明
                if task_data["action_type"] == "api_call" and task_data["action_config"].get("extract_fields"):
                    success_message += f"""

🎯 **API数据提取已配置：**
• 提取字段：{', '.join(task_data["action_config"]["extract_fields"])}
• 消息模板：{task_data["action_config"]["message_template"][:50]}{'...' if len(task_data["action_config"]["message_template"]) > 50 else ''}
• 发送目标：{task_data["action_config"]["send_target_type"]}:{task_data["action_config"]["send_target_id"]}"""
                
                await event.send(event.plain_result(success_message))
            else:
                await event.send(event.plain_result("❌ 任务创建失败：任务ID已存在"))
                
        except Exception as e:
            logger.error(f"创建任务失败: {e}", exc_info=True)
            await event.send(event.plain_result(f"❌ 任务创建失败：{str(e)}"))
    
    @task.command("delete")
    async def delete_task(self, event: AstrMessageEvent, task_id: str):
        """删除任务 - 安全确认"""
        try:
            task = self.task_manager.get_task(task_id)
            if not task:
                yield event.plain_result(f"❌ 任务不存在: {task_id}")
                return
            
            confirm_text = f"""⚠️ **确认删除任务**

任务信息：
• ID: `{task.id}`
• 名称: {task.name}
• 描述: {task.description}
• 运行次数: {task.run_count}

⚠️ **此操作不可撤销！**

确认删除吗？
• 回复 **DELETE** 确认删除
• 回复其他内容取消操作"""
            
            yield event.plain_result(confirm_text)
            
            @session_waiter(timeout=30, record_history_chains=False)
            async def confirm_delete(controller: SessionController, event: AstrMessageEvent):
                confirmation = event.message_str.strip() if event.message_str else ""
                
                if confirmation == "DELETE":
                    success = self.task_manager.remove_task(task_id)
                    if success:
                        self._save_tasks()
                        await event.send(event.plain_result(f"✅ 任务 `{task_id}` 已删除"))
                    else:
                        await event.send(event.plain_result(f"❌ 删除任务失败"))
                else:
                    await event.send(event.plain_result("❌ 删除操作已取消"))
                
                controller.stop()
            
            await confirm_delete(event)
            
        except TimeoutError:
            yield event.plain_result("⏰ 操作超时，删除已取消")
        except Exception as e:
            logger.error(f"删除任务失败: {e}")
            yield event.plain_result("😥 删除任务失败")
    
    @task.command("help")
    async def show_help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        help_text = """📖 **定时任务插件使用指南**

**任务管理:**
• `/task list [group]` - 列出所有任务
• `/task info <task_id>` - 查看任务详情
• `/task create` - 🆕 可视化创建任务
• `/task edit <task_id>` - 🆕 可视化编辑任务
• `/task delete <task_id>` - 🆕 安全删除任务
• `/task run <task_id>` - 手动执行任务
• `/task enable <task_id>` - 启用任务
• `/task disable <task_id>` - 禁用任务

**调度管理:**
• `/task status` - 查看调度器状态
• `/task help` - 显示此帮助

🎯 **推荐使用 `/task create` 进行可视化任务配置！**

**支持的调度类型:**
• **Cron表达式**: `0 9 * * *` (每天9点)
• **固定间隔**: 每N秒/分钟/小时执行
• **一次性任务**: 指定时间执行一次
• **手动触发**: 只能手动执行

**支持的动作类型:**
• **send_message** - 发送消息
• **api_call** - 调用API接口
• **file_operation** - 文件操作
• **command** - 执行系统命令

**配置文件:** 
高级用户可直接编辑 `data/scheduler/tasks.json`
示例配置请参考 `config/tasks.json`"""
        
        yield event.plain_result(help_text)
    
    def _get_schedule_description(self, schedule: TaskSchedule) -> str:
        """获取调度描述"""
        if schedule.type == "cron":
            expression = schedule.config.get("expression", "")
            return self.cron_parser.describe(expression)
        elif schedule.type == "interval":
            seconds = schedule.config.get("seconds", 0)
            return IntervalParser.describe_interval(seconds)
        elif schedule.type == "once":
            target_time = schedule.config.get("datetime", "")
            return f"一次性任务: {target_time}"
        elif schedule.type == "manual":
            return "手动触发"
        else:
            return "未知调度类型"
    
    async def terminate(self):
        """插件卸载时调用"""
        try:
            await self.scheduler.stop()
            self._save_tasks()
            logger.info("通用定时任务调度插件已安全卸载")
        except Exception as e:
            logger.error(f"插件卸载时错误: {e}")