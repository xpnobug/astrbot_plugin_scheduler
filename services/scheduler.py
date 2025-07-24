"""核心调度器服务"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from ..models.task import Task, TaskManager, TaskResult
from ..utils.cron_parser import CronParser, IntervalParser
from astrbot.api import logger


class TaskScheduler:
    """任务调度器"""
    
    def __init__(self, task_manager: TaskManager, executor_callback: Callable, check_interval: int = 30):
        self.task_manager = task_manager
        self.executor_callback = executor_callback
        self.check_interval = check_interval
        self.cron_parser = CronParser()
        self.interval_parser = IntervalParser()
        
        self.running = False
        self.scheduler_task: Optional[asyncio.Task] = None
        self.task_futures: Dict[str, asyncio.Task] = {}
        
    async def start(self):
        """启动调度器"""
        if self.running:
            return
        
        self.running = True
        self.scheduler_task = asyncio.create_task(self._schedule_loop())
        logger.info("任务调度器已启动")
    
    async def stop(self):
        """停止调度器"""
        self.running = False
        
        if self.scheduler_task:
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                pass
        
        # 取消所有运行中的任务
        for task_id, future in self.task_futures.items():
            if not future.done():
                future.cancel()
                logger.info(f"取消任务: {task_id}")
        
        self.task_futures.clear()
        logger.info("任务调度器已停止")
    
    async def _schedule_loop(self):
        """主调度循环"""
        while self.running:
            try:
                await self._check_and_run_tasks()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"调度器错误: {e}", exc_info=True)
                await asyncio.sleep(60)  # 错误时等待更长时间
    
    async def _check_and_run_tasks(self):
        """检查并运行到期的任务"""
        now = datetime.now()
        ready_tasks = []
        
        for task in self.task_manager.list_tasks(enabled_only=True):
            try:
                if self._should_run_task(task, now):
                    ready_tasks.append(task)
            except Exception as e:
                logger.error(f"检查任务 {task.id} 时出错: {e}")
        
        # 按优先级排序
        ready_tasks.sort(key=lambda t: t.priority, reverse=True)
        
        # 执行任务
        for task in ready_tasks:
            if task.id not in self.task_futures or self.task_futures[task.id].done():
                self.task_futures[task.id] = asyncio.create_task(
                    self._execute_task_with_retry(task)
                )
    
    def _should_run_task(self, task: Task, now: datetime) -> bool:
        """判断任务是否应该运行"""
        if not task.enabled or not task.schedule.enabled:
            return False
        
        # 检查依赖任务
        if not self._check_dependencies(task):
            return False
        
        schedule_type = task.schedule.type
        config = task.schedule.config
        
        if schedule_type == "cron":
            return self._should_run_cron_task(task, now, config.get("expression", ""))
        elif schedule_type == "interval":
            return self._should_run_interval_task(task, now, config.get("seconds", 0))
        elif schedule_type == "once":
            return self._should_run_once_task(task, now, config.get("datetime", ""))
        elif schedule_type == "manual":
            return False  # 手动任务不自动执行
        
        return False
    
    def _should_run_cron_task(self, task: Task, now: datetime, cron_expression: str) -> bool:
        """检查Cron任务是否应该运行"""
        if not self.cron_parser.parse(cron_expression):
            return False
        
        # 如果从未运行过，计算下次运行时间
        if task.next_run is None:
            task.next_run = self.cron_parser.get_next_run_time(cron_expression, now)
            return False
        
        # 检查是否到了运行时间
        if now >= task.next_run:
            # 更新下次运行时间
            task.next_run = self.cron_parser.get_next_run_time(cron_expression, now)
            return True
        
        return False
    
    def _should_run_interval_task(self, task: Task, now: datetime, interval_seconds: int) -> bool:
        """检查间隔任务是否应该运行"""
        if interval_seconds <= 0:
            return False
        
        # 如果从未运行过，记录首次检查时间，等待一个完整间隔周期
        if task.last_run is None:
            task.last_run = now  # 记录首次检查时间，作为下一次运行的基准
            return False  # 第一次不立即运行
        
        # 检查是否过了间隔时间
        next_run = task.last_run + timedelta(seconds=interval_seconds)
        return now >= next_run
    
    def _should_run_once_task(self, task: Task, now: datetime, target_datetime: str) -> bool:
        """检查一次性任务是否应该运行"""
        try:
            target_time = datetime.fromisoformat(target_datetime)
            # 一次性任务只运行一次
            if task.last_run is None and now >= target_time:
                return True
        except ValueError:
            logger.error(f"无效的日期时间格式: {target_datetime}")
        
        return False
    
    def _check_dependencies(self, task: Task) -> bool:
        """检查任务依赖"""
        if not task.dependencies:
            return True
        
        for dep_id in task.dependencies:
            dep_task = self.task_manager.get_task(dep_id)
            if not dep_task:
                logger.warning(f"依赖任务不存在: {dep_id}")
                return False
            
            # 检查依赖任务是否成功执行过
            if dep_task.success_count == 0:
                return False
        
        return True
    
    async def _execute_task_with_retry(self, task: Task):
        """执行任务（带重试机制）"""
        retry_count = 0
        max_retries = task.retry_count
        
        while retry_count <= max_retries:
            try:
                start_time = datetime.now()
                
                # 执行任务
                result = await self.executor_callback(task)
                
                duration = (datetime.now() - start_time).total_seconds()
                
                # 创建执行结果
                task_result = TaskResult(
                    success=result.get("success", False),
                    message=result.get("message", ""),
                    timestamp=start_time,
                    duration=duration,
                    error=result.get("error")
                )
                
                # 更新任务状态
                self.task_manager.update_task_status(task.id, task_result)
                
                if task_result.success:
                    logger.info(f"任务执行成功: {task.name} (耗时: {duration:.2f}s)")
                    return
                else:
                    logger.warning(f"任务执行失败: {task.name} - {task_result.message}")
                    
            except Exception as e:
                error_msg = f"任务执行异常: {str(e)}"
                logger.error(f"任务 {task.name} 执行异常: {e}", exc_info=True)
                
                # 记录失败结果
                task_result = TaskResult(
                    success=False,
                    message=error_msg,
                    timestamp=datetime.now(),
                    error=str(e)
                )
                self.task_manager.update_task_status(task.id, task_result)
            
            retry_count += 1
            if retry_count <= max_retries:
                delay = task.retry_delay * retry_count  # 递增延迟
                logger.info(f"任务 {task.name} 将在 {delay} 秒后重试 ({retry_count}/{max_retries})")
                await asyncio.sleep(delay)
        
        # 所有重试都失败了
        logger.error(f"任务 {task.name} 执行失败，已达到最大重试次数")
        await self._handle_task_failure(task)
    
    async def _handle_task_failure(self, task: Task):
        """处理任务失败"""
        if task.on_failure == "disable":
            task.enabled = False
            logger.info(f"任务 {task.name} 因失败被禁用")
        elif task.on_failure == "notify":
            # 发送失败通知
            await self._send_failure_notification(task)
    
    async def _send_failure_notification(self, task: Task):
        """发送失败通知"""
        try:
            notification_message = f"⚠️ 任务执行失败\n任务名称: {task.name}\n失败次数: {task.fail_count}\n最后错误: 请查看日志"
            logger.warning(notification_message)
            
            # 实际发送消息到管理员
            if hasattr(self, 'executor_callback') and self.executor_callback:
                await self.executor_callback({
                    "type": "send_message",
                    "config": {
                        "message": notification_message,
                        "target_type": "user",
                        "target_id": getattr(self, 'admin_id', None) or "admin"
                    }
                })
        except Exception as e:
            logger.error(f"发送失败通知时出错: {e}")
    
    async def run_task_manually(self, task_id: str) -> bool:
        """手动运行任务"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return False
        
        if task_id in self.task_futures and not self.task_futures[task_id].done():
            logger.warning(f"任务 {task.name} 正在运行中")
            return False
        
        self.task_futures[task_id] = asyncio.create_task(
            self._execute_task_with_retry(task)
        )
        return True
    
    def get_task_status(self, task_id: str) -> Optional[str]:
        """获取任务运行状态"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return None
        
        if not task.enabled:
            return "已禁用"
        
        if task_id in self.task_futures:
            future = self.task_futures[task_id]
            if not future.done():
                return "运行中"
            elif future.cancelled():
                return "已取消"
            elif future.exception():
                return "执行失败"
            else:
                return "执行完成"
        
        return "等待中"
    
    def get_scheduler_stats(self) -> Dict:
        """获取调度器统计信息"""
        running_tasks = len([f for f in self.task_futures.values() if not f.done()])
        completed_tasks = len([f for f in self.task_futures.values() if f.done() and not f.exception()])
        failed_tasks = len([f for f in self.task_futures.values() if f.done() and f.exception()])
        
        return {
            "running": self.running,
            "total_tasks": len(self.task_manager.tasks),
            "running_tasks": running_tasks,
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
            "scheduler_uptime": "运行中" if self.running else "已停止"
        }