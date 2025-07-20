"""配置验证器 - 提供JSON Schema验证和安全检查"""
import json
import re
from typing import Dict, List, Any, Optional, Tuple
from astrbot.api import logger


class ConfigValidator:
    """配置验证器"""
    
    def __init__(self):
        self.task_schema = self._get_task_schema()
        self.action_schemas = self._get_action_schemas()
    
    def validate_tasks_config(self, config_json: str) -> Tuple[bool, str, Optional[Dict]]:
        """验证任务配置JSON
        
        Returns:
            (is_valid, error_message, parsed_config)
        """
        try:
            # 1. JSON语法验证
            try:
                config_data = json.loads(config_json)
            except json.JSONDecodeError as e:
                return False, f"JSON格式错误: {str(e)}", None
            
            # 2. 基本结构验证
            if not isinstance(config_data, dict):
                return False, "配置必须是一个JSON对象", None
                
            if "tasks" not in config_data:
                return False, "配置中缺少 'tasks' 字段", None
                
            if not isinstance(config_data["tasks"], list):
                return False, "'tasks' 字段必须是数组", None
            
            # 3. 任务数量限制
            if len(config_data["tasks"]) > 50:
                return False, "任务数量不能超过50个", None
            
            # 4. 逐个验证任务
            for i, task_data in enumerate(config_data["tasks"]):
                is_valid, error = self._validate_single_task(task_data, i)
                if not is_valid:
                    return False, error, None
            
            # 5. 安全检查
            security_check, security_error = self._security_check(config_data)
            if not security_check:
                return False, f"安全检查失败: {security_error}", None
            
            logger.info(f"✅ 配置验证通过，包含 {len(config_data['tasks'])} 个任务")
            return True, "配置验证通过", config_data
            
        except Exception as e:
            logger.error(f"配置验证异常: {e}")
            return False, f"配置验证异常: {str(e)}", None
    
    def _validate_single_task(self, task_data: Dict[str, Any], index: int) -> Tuple[bool, str]:
        """验证单个任务配置"""
        try:
            # 必需字段检查
            required_fields = ["id", "name", "description", "schedule", "actions"]
            for field in required_fields:
                if field not in task_data:
                    return False, f"任务 {index}: 缺少必需字段 '{field}'"
            
            # 字段类型检查
            if not isinstance(task_data["id"], str) or not task_data["id"].strip():
                return False, f"任务 {index}: 'id' 必须是非空字符串"
                
            if not isinstance(task_data["name"], str) or not task_data["name"].strip():
                return False, f"任务 {index}: 'name' 必须是非空字符串"
                
            if not isinstance(task_data["actions"], list) or len(task_data["actions"]) == 0:
                return False, f"任务 {index}: 'actions' 必须是非空数组"
            
            # ID长度和格式检查
            if len(task_data["id"]) > 100:
                return False, f"任务 {index}: ID长度不能超过100个字符"
                
            if not re.match(r'^[a-zA-Z0-9_-]+$', task_data["id"]):
                return False, f"任务 {index}: ID只能包含字母、数字、下划线和连字符"
            
            # 验证调度配置
            is_valid, error = self._validate_schedule(task_data["schedule"], index)
            if not is_valid:
                return False, error
            
            # 验证动作配置
            for j, action in enumerate(task_data["actions"]):
                is_valid, error = self._validate_action(action, index, j)
                if not is_valid:
                    return False, error
            
            return True, ""
            
        except Exception as e:
            return False, f"任务 {index} 验证异常: {str(e)}"
    
    def _validate_schedule(self, schedule_data: Dict[str, Any], task_index: int) -> Tuple[bool, str]:
        """验证调度配置"""
        try:
            if not isinstance(schedule_data, dict):
                return False, f"任务 {task_index}: schedule 必须是对象"
            
            if "type" not in schedule_data:
                return False, f"任务 {task_index}: schedule 缺少 'type' 字段"
            
            schedule_type = schedule_data["type"]
            allowed_types = ["cron", "interval", "once", "manual"]
            
            if schedule_type not in allowed_types:
                return False, f"任务 {task_index}: schedule.type 必须是 {allowed_types} 之一"
            
            if "config" not in schedule_data:
                return False, f"任务 {task_index}: schedule 缺少 'config' 字段"
            
            config = schedule_data["config"]
            
            # 根据类型验证具体配置
            if schedule_type == "cron":
                if not isinstance(config, dict) or "expression" not in config:
                    return False, f"任务 {task_index}: cron schedule 需要 expression 字段"
                
                # 验证cron表达式格式
                cron_expr = config["expression"]
                if not self._validate_cron_expression(cron_expr):
                    return False, f"任务 {task_index}: 无效的cron表达式 '{cron_expr}'"
            
            elif schedule_type == "interval":
                if not isinstance(config, dict):
                    return False, f"任务 {task_index}: interval schedule config 必须是对象"
                
                # 检查间隔类型
                valid_keys = ["seconds", "minutes", "hours", "days"]
                if not any(key in config for key in valid_keys):
                    return False, f"任务 {task_index}: interval schedule 需要指定时间间隔"
                
                # 验证间隔值
                for key in valid_keys:
                    if key in config:
                        value = config[key]
                        if not isinstance(value, (int, float)) or value <= 0:
                            return False, f"任务 {task_index}: {key} 必须是大于0的数字"
                        
                        # 设置合理的上限
                        if key == "seconds" and value > 86400:  # 不超过1天
                            return False, f"任务 {task_index}: seconds 不能超过86400"
                        elif key == "minutes" and value > 1440:  # 不超过1天
                            return False, f"任务 {task_index}: minutes 不能超过1440"
                        elif key == "hours" and value > 24:  # 不超过24小时
                            return False, f"任务 {task_index}: hours 不能超过24"
                        elif key == "days" and value > 365:  # 不超过1年
                            return False, f"任务 {task_index}: days 不能超过365"
            
            return True, ""
            
        except Exception as e:
            return False, f"任务 {task_index} schedule 验证异常: {str(e)}"
    
    def _validate_action(self, action_data: Dict[str, Any], task_index: int, action_index: int) -> Tuple[bool, str]:
        """验证动作配置"""
        try:
            if not isinstance(action_data, dict):
                return False, f"任务 {task_index} 动作 {action_index}: action 必须是对象"
            
            if "type" not in action_data:
                return False, f"任务 {task_index} 动作 {action_index}: 缺少 'type' 字段"
            
            action_type = action_data["type"]
            allowed_types = ["send_message", "api_call", "file_operation", "command"]
            
            if action_type not in allowed_types:
                return False, f"任务 {task_index} 动作 {action_index}: type 必须是 {allowed_types} 之一"
            
            if "config" not in action_data:
                return False, f"任务 {task_index} 动作 {action_index}: 缺少 'config' 字段"
            
            config = action_data["config"]
            
            # 根据动作类型进行具体验证
            if action_type == "send_message":
                return self._validate_send_message_action(config, task_index, action_index)
            elif action_type == "api_call":
                return self._validate_api_call_action(config, task_index, action_index)
            elif action_type == "file_operation":
                return self._validate_file_operation_action(config, task_index, action_index)
            elif action_type == "command":
                return self._validate_command_action(config, task_index, action_index)
            
            return True, ""
            
        except Exception as e:
            return False, f"任务 {task_index} 动作 {action_index} 验证异常: {str(e)}"
    
    def _validate_send_message_action(self, config: Dict[str, Any], task_index: int, action_index: int) -> Tuple[bool, str]:
        """验证发送消息动作"""
        required_fields = ["target_type", "target_id", "message"]
        for field in required_fields:
            if field not in config:
                return False, f"任务 {task_index} 动作 {action_index}: send_message 缺少 '{field}' 字段"
        
        # 验证目标类型
        if config["target_type"] not in ["group", "private", "channel"]:
            return False, f"任务 {task_index} 动作 {action_index}: target_type 必须是 group、private 或 channel"
        
        # 验证消息长度
        if len(config["message"]) > 4000:
            return False, f"任务 {task_index} 动作 {action_index}: 消息长度不能超过4000个字符"
        
        return True, ""
    
    def _validate_api_call_action(self, config: Dict[str, Any], task_index: int, action_index: int) -> Tuple[bool, str]:
        """验证API调用动作"""
        required_fields = ["method", "url"]
        for field in required_fields:
            if field not in config:
                return False, f"任务 {task_index} 动作 {action_index}: api_call 缺少 '{field}' 字段"
        
        # 验证HTTP方法
        if config["method"].upper() not in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
            return False, f"任务 {task_index} 动作 {action_index}: 不支持的HTTP方法 '{config['method']}'"
        
        # 验证URL格式
        url = config["url"]
        if not self._validate_url(url):
            return False, f"任务 {task_index} 动作 {action_index}: 无效的URL格式 '{url}'"
        
        # 验证超时设置
        if "timeout" in config:
            timeout = config["timeout"]
            if not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > 300:
                return False, f"任务 {task_index} 动作 {action_index}: timeout 必须是1-300之间的数字"
        
        # 验证图片相关配置
        if "image_fields" in config:
            image_fields = config["image_fields"]
            if not isinstance(image_fields, list):
                return False, f"任务 {task_index} 动作 {action_index}: image_fields 必须是数组"
            
            for field_path in image_fields:
                if not isinstance(field_path, str) or not field_path.strip():
                    return False, f"任务 {task_index} 动作 {action_index}: image_fields 中的字段路径必须是非空字符串"
        
        if "image_message_template" in config:
            template = config["image_message_template"]
            if not isinstance(template, str):
                return False, f"任务 {task_index} 动作 {action_index}: image_message_template 必须是字符串"
        
        if "send_as_image" in config:
            send_as_image = config["send_as_image"]
            if not isinstance(send_as_image, bool):
                return False, f"任务 {task_index} 动作 {action_index}: send_as_image 必须是布尔值"
        
        if "image_download_timeout" in config:
            timeout = config["image_download_timeout"]
            if not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > 120:
                return False, f"任务 {task_index} 动作 {action_index}: image_download_timeout 必须是1-120之间的数字"
        
        if "response_is_image" in config:
            response_is_image = config["response_is_image"]
            if not isinstance(response_is_image, bool):
                return False, f"任务 {task_index} 动作 {action_index}: response_is_image 必须是布尔值"
        
        return True, ""
    
    def _validate_file_operation_action(self, config: Dict[str, Any], task_index: int, action_index: int) -> Tuple[bool, str]:
        """验证文件操作动作"""
        if "operation" not in config:
            return False, f"任务 {task_index} 动作 {action_index}: file_operation 缺少 'operation' 字段"
        
        operation = config["operation"]
        allowed_operations = ["backup", "delete", "move", "copy", "cleanup"]
        
        if operation not in allowed_operations:
            return False, f"任务 {task_index} 动作 {action_index}: operation 必须是 {allowed_operations} 之一"
        
        # 验证路径安全性
        if "source_path" in config:
            if not self._validate_file_path(config["source_path"]):
                return False, f"任务 {task_index} 动作 {action_index}: 不安全的source_path"
        
        if "target_path" in config:
            if not self._validate_file_path(config["target_path"]):
                return False, f"任务 {task_index} 动作 {action_index}: 不安全的target_path"
        
        return True, ""
    
    def _validate_command_action(self, config: Dict[str, Any], task_index: int, action_index: int) -> Tuple[bool, str]:
        """验证命令执行动作"""
        if "command" not in config:
            return False, f"任务 {task_index} 动作 {action_index}: command 缺少 'command' 字段"
        
        command = config["command"]
        
        # 长度限制
        if len(command) > 1000:
            return False, f"任务 {task_index} 动作 {action_index}: 命令长度不能超过1000个字符"
        
        # 基本安全检查 - 简化版本，避免循环导入
        dangerous_patterns = [
            'rm -rf', 'shutdown', 'reboot', 'mkfs', 'dd if=', 'chmod 777',
            'chown root', 'sudo su', 'passwd', '&&', '||', ';', '|',
            '$(', '`', '/etc/', '/bin/', '/sbin/', '/proc/', '/sys/'
        ]
        
        command_lower = command.lower()
        for pattern in dangerous_patterns:
            if pattern in command_lower:
                return False, f"任务 {task_index} 动作 {action_index}: 命令包含危险模式 '{pattern}'"
        
        return True, ""
    
    def _security_check(self, config_data: Dict[str, Any]) -> Tuple[bool, str]:
        """整体安全检查"""
        try:
            # 1. 检查任务数量是否合理
            task_count = len(config_data.get("tasks", []))
            if task_count > 50:
                return False, "任务数量过多，最多允许50个"
            
            # 2. 检查是否有过于频繁的调度
            for task in config_data.get("tasks", []):
                schedule = task.get("schedule", {})
                if schedule.get("type") == "interval":
                    config = schedule.get("config", {})
                    if "seconds" in config and config["seconds"] < 10:
                        return False, f"任务 '{task.get('name')}' 调度间隔过短，最少10秒"
            
            # 3. 检查敏感操作
            sensitive_count = 0
            for task in config_data.get("tasks", []):
                for action in task.get("actions", []):
                    if action.get("type") in ["command", "file_operation"]:
                        sensitive_count += 1
            
            if sensitive_count > 10:
                return False, "敏感操作(命令执行/文件操作)过多，最多允许10个"
            
            # 4. 检查资源使用
            api_call_count = 0
            for task in config_data.get("tasks", []):
                for action in task.get("actions", []):
                    if action.get("type") == "api_call":
                        api_call_count += 1
            
            if api_call_count > 20:
                return False, "API调用动作过多，最多允许20个"
            
            return True, ""
            
        except Exception as e:
            return False, f"安全检查异常: {str(e)}"
    
    def _validate_cron_expression(self, expression: str) -> bool:
        """验证cron表达式格式"""
        try:
            parts = expression.strip().split()
            if len(parts) != 5:
                return False
            
            # 基本格式检查
            for part in parts:
                if not re.match(r'^[\d,\-\*/]+$', part) and part != '*':
                    return False
            
            return True
        except:
            return False
    
    def _validate_url(self, url: str) -> bool:
        """验证URL格式和安全性"""
        try:
            import urllib.parse
            
            parsed = urllib.parse.urlparse(url)
            
            # 必须有scheme和netloc
            if not parsed.scheme or not parsed.netloc:
                return False
            
            # 只允许http和https
            if parsed.scheme not in ["http", "https"]:
                return False
            
            # 禁止本地地址
            if parsed.netloc in ["localhost", "127.0.0.1", "0.0.0.0"]:
                return False
            
            # 禁止内网地址
            if parsed.netloc.startswith("192.168.") or parsed.netloc.startswith("10."):
                return False
            
            return True
        except:
            return False
    
    def _validate_file_path(self, path: str) -> bool:
        """验证文件路径安全性"""
        try:
            # 禁止绝对路径（除了特定安全目录）
            safe_absolute_paths = ["/tmp/", "/var/tmp/"]
            
            if path.startswith("/"):
                if not any(path.startswith(safe) for safe in safe_absolute_paths):
                    return False
            
            # 禁止路径遍历
            if ".." in path or "~" in path:
                return False
            
            # 禁止系统关键目录
            dangerous_paths = ["/etc", "/bin", "/sbin", "/usr/bin", "/proc", "/sys", "/dev"]
            for dangerous in dangerous_paths:
                if path.startswith(dangerous):
                    return False
            
            return True
        except:
            return False
    
    def _get_task_schema(self) -> Dict[str, Any]:
        """获取任务JSON Schema"""
        return {
            "type": "object",
            "required": ["id", "name", "description", "schedule", "actions"],
            "properties": {
                "id": {"type": "string", "maxLength": 100},
                "name": {"type": "string", "maxLength": 200},
                "description": {"type": "string", "maxLength": 500},
                "enabled": {"type": "boolean", "default": True},
                "schedule": {"type": "object"},
                "actions": {"type": "array", "minItems": 1, "maxItems": 10}
            }
        }
    
    def _get_action_schemas(self) -> Dict[str, Dict[str, Any]]:
        """获取动作类型的JSON Schema"""
        return {
            "send_message": {
                "type": "object",
                "required": ["target_type", "target_id", "message"],
                "properties": {
                    "target_type": {"enum": ["group", "private", "channel"]},
                    "target_id": {"type": "string"},
                    "message": {"type": "string", "maxLength": 4000}
                }
            },
            "api_call": {
                "type": "object", 
                "required": ["method", "url"],
                "properties": {
                    "method": {"enum": ["GET", "POST", "PUT", "DELETE", "PATCH"]},
                    "url": {"type": "string", "format": "uri"},
                    "timeout": {"type": "number", "minimum": 1, "maximum": 300}
                }
            }
        }