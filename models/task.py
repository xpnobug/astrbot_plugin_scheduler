"""任务数据模型"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime
import uuid
import asyncio
from collections import deque


@dataclass
class TaskAction:
    """任务动作配置"""
    type: str  # 动作类型: send_message, api_call, file_operation, command
    config: Dict[str, Any]  # 动作配置参数
    conditions: List[Dict[str, Any]] = field(default_factory=list)  # 执行条件


@dataclass
class TaskSchedule:
    """任务调度配置"""
    type: str  # 调度类型: cron, interval, once, manual
    config: Dict[str, Any]  # 调度配置
    timezone: str = "Asia/Shanghai"  # 时区
    enabled: bool = True  # 是否启用


@dataclass
class TaskResult:
    """任务执行结果"""
    success: bool
    message: str
    timestamp: datetime
    duration: float = 0.0
    error: Optional[str] = None


@dataclass
class Task:
    """通用任务模型"""
    id: str
    name: str
    description: str
    schedule: TaskSchedule
    actions: List[TaskAction]
    
    # 运行时状态
    enabled: bool = True
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    success_count: int = 0
    fail_count: int = 0
    
    # 依赖和分组
    dependencies: List[str] = field(default_factory=list)  # 依赖的任务ID
    group: str = "default"  # 任务分组
    priority: int = 0  # 优先级(数字越大优先级越高)
    
    # 错误处理
    retry_count: int = 3  # 重试次数
    retry_delay: int = 60  # 重试延迟(秒)
    on_failure: str = "log"  # 失败处理: log, notify, disable
    
    # 元数据
    created_by: str = "system"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    tags: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "schedule": {
                "type": self.schedule.type,
                "config": self.schedule.config,
                "timezone": self.schedule.timezone,
                "enabled": self.schedule.enabled
            },
            "actions": [
                {
                    "type": action.type,
                    "config": action.config,
                    "conditions": action.conditions
                }
                for action in self.actions
            ],
            "enabled": self.enabled,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "run_count": self.run_count,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "dependencies": self.dependencies,
            "group": self.group,
            "priority": self.priority,
            "retry_count": self.retry_count,
            "retry_delay": self.retry_delay,
            "on_failure": self.on_failure,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tags": self.tags
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        """从字典创建任务"""
        schedule_data = data["schedule"]
        schedule = TaskSchedule(
            type=schedule_data["type"],
            config=schedule_data["config"],
            timezone=schedule_data.get("timezone", "Asia/Shanghai"),
            enabled=schedule_data.get("enabled", True)
        )
        
        actions = [
            TaskAction(
                type=action_data["type"],
                config=action_data["config"],
                conditions=action_data.get("conditions", [])
            )
            for action_data in data["actions"]
        ]
        
        return cls(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            schedule=schedule,
            actions=actions,
            enabled=data.get("enabled", True),
            last_run=datetime.fromisoformat(data["last_run"]) if data.get("last_run") else None,
            next_run=datetime.fromisoformat(data["next_run"]) if data.get("next_run") else None,
            run_count=data.get("run_count", 0),
            success_count=data.get("success_count", 0),
            fail_count=data.get("fail_count", 0),
            dependencies=data.get("dependencies", []),
            group=data.get("group", "default"),
            priority=data.get("priority", 0),
            retry_count=data.get("retry_count", 3),
            retry_delay=data.get("retry_delay", 60),
            on_failure=data.get("on_failure", "log"),
            created_by=data.get("created_by", "system"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
            tags=data.get("tags", [])
        )


class TaskManager:
    """任务管理器"""
    
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self.task_history: List[TaskResult] = []
    
    def add_task(self, task: Task) -> bool:
        """添加任务"""
        if task.id in self.tasks:
            return False
        self.tasks[task.id] = task
        return True
    
    def remove_task(self, task_id: str) -> bool:
        """删除任务"""
        if task_id in self.tasks:
            del self.tasks[task_id]
            return True
        return False
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self.tasks.get(task_id)
    
    def list_tasks(self, group: Optional[str] = None, enabled_only: bool = False) -> List[Task]:
        """列出任务"""
        tasks = list(self.tasks.values())
        
        if group:
            tasks = [t for t in tasks if t.group == group]
        
        if enabled_only:
            tasks = [t for t in tasks if t.enabled and t.schedule.enabled]
        
        # 按优先级排序
        tasks.sort(key=lambda t: t.priority, reverse=True)
        return tasks
    
    def update_task_status(self, task_id: str, result: TaskResult):
        """更新任务状态"""
        task = self.get_task(task_id)
        if not task:
            return
        
        task.last_run = result.timestamp
        task.run_count += 1
        
        if result.success:
            task.success_count += 1
        else:
            task.fail_count += 1
        
        task.updated_at = datetime.now()
        
        # 保存执行历史
        self.task_history.append(result)
        
        # 限制历史记录数量
        if len(self.task_history) > 1000:
            self.task_history = self.task_history[-1000:]
    
    def get_task_statistics(self) -> Dict[str, Any]:
        """获取任务统计信息"""
        total_tasks = len(self.tasks)
        enabled_tasks = len([t for t in self.tasks.values() if t.enabled])
        running_tasks = len([t for t in self.tasks.values() if t.enabled and t.schedule.enabled])
        
        return {
            "total_tasks": total_tasks,
            "enabled_tasks": enabled_tasks,
            "running_tasks": running_tasks,
            "total_executions": sum(t.run_count for t in self.tasks.values()),
            "success_rate": self._calculate_success_rate(),
            "groups": list(set(t.group for t in self.tasks.values())),
            "recent_failures": len([h for h in self.task_history[-50:] if not h.success])
        }
    
    def _calculate_success_rate(self) -> float:
        """计算成功率"""
        total_runs = sum(t.run_count for t in self.tasks.values())
        if total_runs == 0:
            return 100.0
        
        total_success = sum(t.success_count for t in self.tasks.values())
        return round((total_success / total_runs) * 100, 2)