"""任务执行器"""
import asyncio
import json
import subprocess
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
import aiohttp
from astrbot.api import logger


class ActionExecutor:
    """动作执行器"""
    
    def __init__(self, context, variable_replacer, enable_file_operations=True, enable_command_execution=False):
        self.context = context
        self.variable_replacer = variable_replacer
        self.execution_context = {}  # 存储执行上下文变量
        self.enable_file_operations = enable_file_operations
        self.enable_command_execution = enable_command_execution
    
    async def execute_action(self, action, task_context: Dict[str, Any] = None) -> Dict[str, Any]:
        """执行单个动作"""
        action_type = action.type
        config = action.config.copy()
        
        # 替换配置中的变量
        config = self.variable_replacer.replace_variables(config, task_context or {})
        
        try:
            if action_type == "send_message":
                return await self._execute_send_message(config)
            elif action_type == "api_call":
                return await self._execute_api_call(config)
            elif action_type == "file_operation":
                if not self.enable_file_operations:
                    return {
                        "success": False,
                        "message": "文件操作已被禁用",
                        "error": "File operations disabled by configuration"
                    }
                return await self._execute_file_operation(config)
            elif action_type == "command":
                if not self.enable_command_execution:
                    return {
                        "success": False,
                        "message": "命令执行已被禁用",
                        "error": "Command execution disabled by configuration"
                    }
                return await self._execute_command(config)
            else:
                return {
                    "success": False,
                    "message": f"未知的动作类型: {action_type}",
                    "error": f"Unsupported action type: {action_type}"
                }
        except Exception as e:
            logger.error(f"执行动作 {action_type} 时出错: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"动作执行异常: {str(e)}",
                "error": str(e)
            }
    
    async def _execute_send_message(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """执行发送消息动作"""
        try:
            target_type = config.get("target_type")  # "group", "private", "channel" 等
            target_id = str(config.get("target_id"))  # 确保target_id是字符串
            message = config.get("message", "")
            platform_name = config.get("platform", "aiocqhttp")  # 默认平台
            
            if not target_type or not target_id or not message:
                return {
                    "success": False,
                    "message": "缺少必要参数: target_type, target_id, message"
                }
            
            # 获取平台管理器
            platform_manager = getattr(self.context, 'platform_manager', None)
            if not platform_manager:
                return {
                    "success": False,
                    "message": "无法获取平台管理器，消息发送功能不可用"
                }
            
            # 构建消息链
            from astrbot.core.message.message_event_result import MessageChain
            from astrbot.core.message.components import Plain
            from astrbot.core.platform.astr_message_event import MessageSesion
            from astrbot.core.platform.message_type import MessageType
            
            # 创建消息链
            message_chain = MessageChain()
            message_chain.message(message)
            
            # 确定消息类型和session_id格式
            if target_type.lower() == "group":
                message_type = MessageType.GROUP_MESSAGE
                # 群组消息需要特殊的session_id格式（用户ID_群组ID）
                # 这里使用一个占位符用户ID，实际发送时aiocqhttp会从session_id中提取群组ID
                session_id = f"scheduler_{target_id}"
            elif target_type.lower() == "private":
                message_type = MessageType.FRIEND_MESSAGE
                session_id = target_id
            elif target_type.lower() == "channel":
                message_type = MessageType.GUILD_MESSAGE
                session_id = target_id
            else:
                return {
                    "success": False,
                    "message": f"不支持的消息类型: {target_type}"
                }
            
            # 创建会话对象
            session = MessageSesion(
                platform_name=platform_name,
                message_type=message_type,
                session_id=session_id
            )
            
            # 查找对应的平台实例
            target_platform = None
            for platform_inst in platform_manager.platform_insts:
                if platform_inst.meta().name == platform_name:
                    target_platform = platform_inst
                    break
            
            if not target_platform:
                return {
                    "success": False,
                    "message": f"未找到平台: {platform_name}"
                }
            
            # 发送消息
            await target_platform.send_by_session(session, message_chain)
            
            logger.info(f"✅ 已发送消息到 {platform_name}:{target_type}:{target_id}")
            
            # 更新执行上下文
            self.execution_context.update({
                "sent_message": message,
                "target_platform": platform_name,
                "target_type": target_type,
                "target_id": target_id
            })
            
            return {
                "success": True,
                "message": f"消息已发送到 {platform_name}:{target_type}:{target_id}",
                "data": {
                    "platform": platform_name,
                    "target_type": target_type,
                    "target_id": target_id,
                    "message_length": len(message),
                    "session": str(session)
                }
            }
            
        except Exception as e:
            logger.error(f"发送消息失败: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"发送消息失败: {str(e)}",
                "error": str(e)
            }
    
    async def _execute_api_call(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """执行API调用动作"""
        try:
            method = config.get("method", "GET").upper()
            url = config.get("url")
            headers = config.get("headers", {})
            data = config.get("data")
            timeout = config.get("timeout", 30)
            expected_status = config.get("expected_status", 200)
            
            if not url:
                return {
                    "success": False,
                    "message": "缺少必要参数: url"
                }
            
            start_time = datetime.now()
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data if data and method in ["POST", "PUT", "PATCH"] else None
                ) as response:
                    response_time = (datetime.now() - start_time).total_seconds() * 1000
                    response_text = await response.text()
                    
                    # 尝试解析JSON响应
                    try:
                        response_data = await response.json()
                    except:
                        response_data = response_text
                    
                    success = response.status == expected_status
                    
                    # 更新执行上下文
                    self.execution_context.update({
                        "api_url": url,
                        "status_code": response.status,
                        "response_time": int(response_time),
                        "response_data": response_data
                    })
                    
                    result = {
                        "success": success,
                        "message": f"API调用{'成功' if success else '失败'} - 状态码: {response.status}",
                        "data": {
                            "url": url,
                            "method": method,
                            "status_code": response.status,
                            "response_time": response_time,
                            "response_size": len(response_text)
                        }
                    }
                    
                    # 处理响应数据提取和消息发送
                    logger.info(f"🔍 检查是否需要处理响应数据:")
                    logger.info(f"   success: {success}")
                    logger.info(f"   extract_fields: {config.get('extract_fields')}")
                    logger.info(f"   message_template: {config.get('message_template')}")
                    
                    if success and config.get("extract_fields") and config.get("message_template"):
                        logger.info("✅ 开始处理API响应数据...")
                        await self._handle_api_response_processing(config, response_data, result)
                    else:
                        logger.info("⏭️ 跳过响应数据处理")
                    
                    return result
                    
        except asyncio.TimeoutError:
            return {
                "success": False,
                "message": f"API调用超时 ({timeout}秒)",
                "error": "Request timeout"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"API调用失败: {str(e)}",
                "error": str(e)
            }
    
    async def _execute_file_operation(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """执行文件操作动作"""
        try:
            operation = config.get("operation")
            source_path = config.get("source_path")
            target_path = config.get("target_path")
            compress = config.get("compress", False)
            
            if not operation:
                return {
                    "success": False,
                    "message": "缺少必要参数: operation"
                }
            
            if operation == "backup":
                return await self._backup_files(source_path, target_path, compress)
            elif operation == "delete":
                return await self._delete_files(source_path)
            elif operation == "move":
                return await self._move_files(source_path, target_path)
            elif operation == "copy":
                return await self._copy_files(source_path, target_path)
            elif operation == "cleanup":
                return await self._cleanup_files(source_path, config)
            else:
                return {
                    "success": False,
                    "message": f"不支持的文件操作: {operation}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "message": f"文件操作失败: {str(e)}",
                "error": str(e)
            }
    
    async def _backup_files(self, source_path: str, target_path: str, compress: bool) -> Dict[str, Any]:
        """备份文件"""
        try:
            source = Path(source_path)
            target = Path(target_path)
            
            if not source.exists():
                return {
                    "success": False,
                    "message": f"源路径不存在: {source_path}"
                }
            
            # 确保目标目录存在
            target.parent.mkdir(parents=True, exist_ok=True)
            
            if compress:
                # 创建压缩包
                with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    if source.is_file():
                        zipf.write(source, source.name)
                    else:
                        for file_path in source.rglob('*'):
                            if file_path.is_file():
                                zipf.write(file_path, file_path.relative_to(source))
                
                backup_size = target.stat().st_size
            else:
                # 直接复制
                if source.is_file():
                    shutil.copy2(source, target)
                else:
                    shutil.copytree(source, target, dirs_exist_ok=True)
                
                backup_size = sum(f.stat().st_size for f in target.rglob('*') if f.is_file())
            
            # 更新执行上下文
            self.execution_context.update({
                "backup_file": str(target),
                "backup_size": self._format_size(backup_size)
            })
            
            return {
                "success": True,
                "message": f"备份完成: {target}",
                "data": {
                    "source": source_path,
                    "target": str(target),
                    "size": backup_size,
                    "compressed": compress
                }
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"备份失败: {str(e)}",
                "error": str(e)
            }
    
    async def _delete_files(self, path: str) -> Dict[str, Any]:
        """删除文件"""
        try:
            target = Path(path)
            if not target.exists():
                return {
                    "success": False,
                    "message": f"文件不存在: {path}"
                }
            
            if target.is_file():
                target.unlink()
                return {
                    "success": True,
                    "message": f"文件已删除: {path}"
                }
            else:
                shutil.rmtree(target)
                return {
                    "success": True,
                    "message": f"目录已删除: {path}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "message": f"删除失败: {str(e)}",
                "error": str(e)
            }
    
    async def _move_files(self, source_path: str, target_path: str) -> Dict[str, Any]:
        """移动文件"""
        try:
            source = Path(source_path)
            target = Path(target_path)
            
            if not source.exists():
                return {
                    "success": False,
                    "message": f"源文件不存在: {source_path}"
                }
            
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(source, target)
            
            return {
                "success": True,
                "message": f"文件已移动: {source_path} -> {target_path}"
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"移动失败: {str(e)}",
                "error": str(e)
            }
    
    async def _copy_files(self, source_path: str, target_path: str) -> Dict[str, Any]:
        """复制文件"""
        try:
            source = Path(source_path)
            target = Path(target_path)
            
            if not source.exists():
                return {
                    "success": False,
                    "message": f"源文件不存在: {source_path}"
                }
            
            target.parent.mkdir(parents=True, exist_ok=True)
            
            if source.is_file():
                shutil.copy2(source, target)
            else:
                shutil.copytree(source, target, dirs_exist_ok=True)
            
            return {
                "success": True,
                "message": f"文件已复制: {source_path} -> {target_path}"
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"复制失败: {str(e)}",
                "error": str(e)
            }
    
    async def _cleanup_files(self, path: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """清理文件"""
        try:
            target = Path(path)
            if not target.exists():
                return {
                    "success": False,
                    "message": f"路径不存在: {path}"
                }
            
            # 清理逻辑（例如：删除超过N天的文件）
            days_old = config.get("days_old", 7)
            pattern = config.get("pattern", "*")
            
            deleted_count = 0
            cutoff_time = datetime.now().timestamp() - (days_old * 24 * 3600)
            
            for file_path in target.glob(pattern):
                if file_path.is_file() and file_path.stat().st_mtime < cutoff_time:
                    file_path.unlink()
                    deleted_count += 1
            
            return {
                "success": True,
                "message": f"清理完成，删除了 {deleted_count} 个文件",
                "data": {
                    "deleted_count": deleted_count,
                    "days_old": days_old
                }
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"清理失败: {str(e)}",
                "error": str(e)
            }
    
    async def _execute_command(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """执行系统命令"""
        try:
            command = config.get("command")
            working_dir = config.get("working_dir", ".")
            timeout = config.get("timeout", 60)
            capture_output = config.get("capture_output", True)
            
            if not command:
                return {
                    "success": False,
                    "message": "缺少必要参数: command"
                }
            
            # 安全检查
            if not self._is_safe_command(command):
                return {
                    "success": False,
                    "message": "不安全的命令被拒绝执行",
                    "error": "Command rejected for security reasons"
                }
            
            # 创建安全的执行环境
            safe_env = {
                'PATH': '/usr/local/bin:/usr/bin:/bin',  # 限制PATH
                'HOME': '/tmp',  # 设置安全的HOME目录
                'USER': 'scheduler',  # 设置用户名
                'SHELL': '/bin/sh',  # 限制shell
                'LC_ALL': 'C',  # 设置locale
            }
            
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=working_dir,
                stdout=subprocess.PIPE if capture_output else None,
                stderr=subprocess.PIPE if capture_output else None,
                env=safe_env,  # 使用安全环境变量
                preexec_fn=None,  # 禁用预执行函数
                shell=True,  # 使用shell但环境受限
                limit=1024*1024  # 限制输出大小为1MB
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), 
                    timeout=timeout
                )
                
                success = process.returncode == 0
                
                return {
                    "success": success,
                    "message": f"命令{'执行成功' if success else '执行失败'} (退出码: {process.returncode})",
                    "data": {
                        "command": command,
                        "return_code": process.returncode,
                        "stdout": stdout.decode() if stdout else "",
                        "stderr": stderr.decode() if stderr else ""
                    }
                }
                
            except asyncio.TimeoutError:
                process.kill()
                return {
                    "success": False,
                    "message": f"命令执行超时 ({timeout}秒)",
                    "error": "Command timeout"
                }
                
        except Exception as e:
            return {
                "success": False,
                "message": f"命令执行失败: {str(e)}",
                "error": str(e)
            }
    
    def _is_safe_command(self, command: str) -> bool:
        """检查命令是否安全 - 使用白名单机制"""
        import shlex
        
        try:
            # 解析命令行参数
            cmd_parts = shlex.split(command)
            if not cmd_parts:
                return False
            
            base_cmd = cmd_parts[0]
            
            # 安全命令白名单
            SAFE_COMMANDS = {
                # 基本信息查看
                'echo', 'printf', 'cat', 'head', 'tail', 'less', 'more',
                'ls', 'dir', 'pwd', 'whoami', 'id', 'date', 'uptime',
                'hostname', 'uname', 'df', 'du', 'free', 'ps',
                
                # 文件操作（只读）
                'find', 'locate', 'which', 'whereis', 'file', 'stat',
                'wc', 'sort', 'uniq', 'cut', 'awk', 'sed', 'grep',
                
                # 网络工具（安全的）
                'ping', 'nslookup', 'dig', 'curl', 'wget',
                
                # 系统监控
                'top', 'htop', 'iostat', 'vmstat', 'netstat',
                
                # 压缩解压（只读操作）
                'gzip', 'gunzip', 'zip', 'unzip', 'tar'
            }
            
            # 检查基础命令是否在白名单中
            if base_cmd not in SAFE_COMMANDS:
                logger.warning(f"⚠️ 命令 '{base_cmd}' 不在安全白名单中")
                return False
            
            # 额外的参数安全检查
            command_full = ' '.join(cmd_parts)
            
            # 危险参数模式
            dangerous_patterns = [
                '--delete', '--remove', '--force', '-f',
                '--recursive', '-r', '-rf', '-R',
                '>', '>>', '|', '&', ';', '&&', '||',
                '$(', '`', 'sudo', 'su', 'chmod', 'chown',
                '/etc/', '/bin/', '/sbin/', '/usr/bin/',
                '/proc/', '/sys/', '/dev/'
            ]
            
            for pattern in dangerous_patterns:
                if pattern in command_full:
                    logger.warning(f"⚠️ 命令包含危险参数: {pattern}")
                    return False
            
            # 路径安全检查 - 只允许相对路径和特定安全目录
            safe_paths = {
                '/tmp/', '/var/tmp/', './data/', './logs/', './backup/'
            }
            
            # 检查是否包含绝对路径但不在安全目录中
            for part in cmd_parts[1:]:  # 跳过命令本身
                if part.startswith('/') and not any(part.startswith(safe) for safe in safe_paths):
                    logger.warning(f"⚠️ 不安全的绝对路径: {part}")
                    return False
            
            logger.info(f"✅ 命令安全检查通过: {base_cmd}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 命令安全检查失败: {e}")
            return False
    
    def _format_size(self, size_bytes: int) -> str:
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f}{unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f}PB"
    
    def get_execution_context(self) -> Dict[str, Any]:
        """获取执行上下文"""
        return self.execution_context.copy()
    
    def clear_execution_context(self):
        """清空执行上下文"""
        self.execution_context.clear()
    
    async def _handle_api_response_processing(self, config: Dict[str, Any], response_data: Any, result: Dict[str, Any]):
        """处理API响应数据提取和消息发送"""
        try:
            extract_fields = config.get("extract_fields", [])
            message_template = config.get("message_template", "")
            
            # 调试输出：打印API响应数据
            logger.info(f"🔍 API响应数据调试:")
            logger.info(f"   response_data 类型: {type(response_data)}")
            logger.info(f"   response_data 内容: {response_data}")
            logger.info(f"   extract_fields: {extract_fields}")
            logger.info(f"   message_template: {message_template}")
            
            if not extract_fields or not message_template:
                logger.warning("❌ 缺少提取字段或消息模板配置")
                return
            
            # 提取字段数据
            extracted_data = {}
            
            for field_path in extract_fields:
                try:
                    value = self._extract_field_value(response_data, field_path)
                    # 获取字段名（取路径的最后一部分）
                    field_name = field_path.split('.')[-1].split('[')[0]
                    extracted_data[field_name] = str(value) if value is not None else ""
                    logger.info(f"   ✅ 提取字段 {field_path} -> {field_name}: {value}")
                except Exception as e:
                    logger.warning(f"   ❌ 提取字段 {field_path} 失败: {e}")
                    field_name = field_path.split('.')[-1].split('[')[0]
                    extracted_data[field_name] = ""
            
            # 添加时间变量
            from datetime import datetime
            now = datetime.now()
            extracted_data.update({
                "timestamp": str(int(now.timestamp())),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S")
            })
            
            # 替换消息模板
            formatted_message = message_template
            logger.info(f"   💬 消息模板处理:")
            logger.info(f"   原始模板: {message_template}")
            logger.info(f"   提取数据: {extracted_data}")
            
            # 逐个替换并记录过程
            for key, value in extracted_data.items():
                placeholder = f"{{{key}}}"
                if placeholder in formatted_message:
                    formatted_message = formatted_message.replace(placeholder, str(value))
                    logger.info(f"     ✅ 替换 {placeholder} -> {value}")
                else:
                    logger.warning(f"     ⚠️ 模板中未找到占位符 {placeholder}")
            
            logger.info(f"   最终消息: {formatted_message}")
            
            # 检查消息是否为空或仅包含空白字符
            if not formatted_message or not formatted_message.strip():
                logger.error("   ❌ 最终消息为空！可能的原因：")
                logger.error("     1. 消息模板本身为空")
                logger.error("     2. 所有占位符都没有找到对应数据")
                logger.error("     3. 提取的数据全部为空值")
            
            # 发送消息
            send_config = {
                "platform": config.get("send_platform", "aiocqhttp"),
                "target_type": config.get("send_target_type", "group"),
                "target_id": config.get("send_target_id", ""),
                "message": formatted_message
            }
            
            logger.info(f"   📤 发送配置: {send_config}")
            
            # 调用发送消息功能
            send_result = await self._execute_send_message(send_config)
            
            # 更新结果信息
            if send_result.get("success"):
                result["message"] += f" | 已发送提取数据到 {send_config['target_type']}:{send_config['target_id']}"
                result["data"]["extracted_fields"] = len(extracted_data)
                result["data"]["sent_message"] = formatted_message[:100] + "..." if len(formatted_message) > 100 else formatted_message
            else:
                result["message"] += f" | 发送消息失败: {send_result.get('message', '')}"
                
        except Exception as e:
            logger.error(f"处理API响应数据失败: {e}")
            result["message"] += f" | 响应处理失败: {str(e)}"
    
    def _extract_field_value(self, data: Any, field_path: str) -> Any:
        """从数据中提取指定路径的字段值"""
        try:
            # 处理嵌套字段路径，如 data.name 或 items[0].title
            current = data
            
            # 分割路径
            parts = field_path.replace('[', '.').replace(']', '').split('.')
            
            logger.info(f"      🔎 解析字段路径 '{field_path}' -> 分割为: {parts}")
            logger.info(f"      📊 初始数据类型: {type(current)}")
            
            for i, part in enumerate(parts):
                if not part:  # 跳过空字符串
                    continue
                
                logger.info(f"      第{i+1}步: 处理路径片段 '{part}', 当前数据类型: {type(current)}")
                    
                if part.isdigit():
                    # 数组索引
                    index = int(part)
                    if isinstance(current, (list, tuple)) and 0 <= index < len(current):
                        current = current[index]
                        logger.info(f"        ✅ 数组索引 [{index}] 成功，获取到: {current}")
                    else:
                        logger.warning(f"        ❌ 数组索引 [{index}] 失败，数据类型: {type(current)}, 长度: {len(current) if hasattr(current, '__len__') else '无'}")
                        return None
                else:
                    # 对象属性
                    if isinstance(current, dict):
                        if part in current:
                            current = current.get(part)
                            logger.info(f"        ✅ 字典键 '{part}' 成功，获取到: {current}")
                        else:
                            logger.warning(f"        ❌ 字典键 '{part}' 不存在，可用键: {list(current.keys())}")
                            return None
                    else:
                        logger.warning(f"        ❌ 期望字典但得到 {type(current)}")
                        return None
                
                if current is None:
                    logger.warning(f"        ⚠️ 路径 '{part}' 返回 None")
                    return None
            
            logger.info(f"      🎯 最终提取结果: {current} (类型: {type(current)})")
            return current
            
        except Exception as e:
            logger.error(f"提取字段值失败 {field_path}: {e}", exc_info=True)
            return None