"""变量模板替换工具"""
import re
import json
from datetime import datetime
from typing import Dict, Any, Union
import uuid
import random
import string


class VariableReplacer:
    """变量替换器"""
    
    def __init__(self):
        self.system_variables = {
            "timestamp": lambda: str(int(datetime.now().timestamp())),
            "date": lambda: datetime.now().strftime("%Y-%m-%d"),
            "time": lambda: datetime.now().strftime("%H:%M:%S"),
            "datetime": lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "weekday": lambda: ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][datetime.now().weekday()],
            "random_id": lambda: str(uuid.uuid4())[:8],
            "random_string": lambda: ''.join(random.choices(string.ascii_letters + string.digits, k=8)),
            "year": lambda: str(datetime.now().year),
            "month": lambda: str(datetime.now().month),
            "day": lambda: str(datetime.now().day),
            "hour": lambda: str(datetime.now().hour),
            "minute": lambda: str(datetime.now().minute)
        }
        
        self.custom_variables = {}
    
    def replace_variables(self, data: Union[str, Dict, list], context: Dict[str, Any] = None) -> Union[str, Dict, list]:
        """递归替换数据中的变量"""
        if context is None:
            context = {}
        
        if isinstance(data, str):
            return self._replace_string_variables(data, context)
        elif isinstance(data, dict):
            return {key: self.replace_variables(value, context) for key, value in data.items()}
        elif isinstance(data, list):
            return [self.replace_variables(item, context) for item in data]
        else:
            return data
    
    def _replace_string_variables(self, text: str, context: Dict[str, Any]) -> str:
        """替换字符串中的变量"""
        if not text:
            return text
        
        # 匹配 {{variable}} 格式的变量
        pattern = r'\{\{([^}]+)\}\}'
        
        def replace_match(match):
            variable_name = match.group(1).strip()
            return self._get_variable_value(variable_name, context)
        
        return re.sub(pattern, replace_match, text)
    
    def _get_variable_value(self, variable_name: str, context: Dict[str, Any]) -> str:
        """获取变量值"""
        # 优先级：context > custom_variables > system_variables
        
        # 1. 检查上下文变量
        if variable_name in context:
            value = context[variable_name]
            return str(value) if value is not None else ""
        
        # 2. 检查自定义变量
        if variable_name in self.custom_variables:
            value = self.custom_variables[variable_name]
            if callable(value):
                try:
                    return str(value())
                except Exception:
                    return ""
            return str(value) if value is not None else ""
        
        # 3. 检查系统变量
        if variable_name in self.system_variables:
            try:
                return str(self.system_variables[variable_name]())
            except Exception:
                return ""
        
        # 4. 检查嵌套变量（如 user.name）
        if '.' in variable_name:
            parts = variable_name.split('.')
            value = context
            try:
                for part in parts:
                    if isinstance(value, dict):
                        value = value.get(part)
                    else:
                        value = getattr(value, part, None)
                    if value is None:
                        break
                return str(value) if value is not None else ""
            except (AttributeError, KeyError, TypeError):
                pass
        
        # 5. 变量不存在，返回原始文本
        return "{{" + variable_name + "}}"
    
    def set_custom_variable(self, name: str, value: Any):
        """设置自定义变量"""
        self.custom_variables[name] = value
    
    def set_custom_variables(self, variables: Dict[str, Any]):
        """批量设置自定义变量"""
        self.custom_variables.update(variables)
    
    def remove_custom_variable(self, name: str):
        """删除自定义变量"""
        self.custom_variables.pop(name, None)
    
    def clear_custom_variables(self):
        """清空自定义变量"""
        self.custom_variables.clear()
    
    def get_available_variables(self) -> Dict[str, str]:
        """获取所有可用变量及其描述"""
        variables = {}
        
        # 系统变量
        system_descriptions = {
            "timestamp": "当前时间戳",
            "date": "当前日期 (YYYY-MM-DD)",
            "time": "当前时间 (HH:MM:SS)", 
            "datetime": "当前日期时间",
            "weekday": "星期几",
            "random_id": "随机ID (8位)",
            "random_string": "随机字符串 (8位)",
            "year": "当前年份",
            "month": "当前月份",
            "day": "当前日期",
            "hour": "当前小时",
            "minute": "当前分钟"
        }
        
        for var in self.system_variables:
            variables[f"{{{{{var}}}}}"] = system_descriptions.get(var, "系统变量")
        
        # 自定义变量
        for var in self.custom_variables:
            variables[f"{{{{{var}}}}}"] = "自定义变量"
        
        return variables
    
    def preview_replacement(self, text: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """预览变量替换结果"""
        if context is None:
            context = {}
        
        original = text
        replaced = self.replace_variables(text, context)
        
        # 找出所有变量
        pattern = r'\{\{([^}]+)\}\}'
        variables_found = re.findall(pattern, original)
        
        variable_values = {}
        for var in variables_found:
            var = var.strip()
            value = self._get_variable_value(var, context)
            variable_values[f"{{{{{var}}}}}"] = value
        
        return {
            "original": original,
            "replaced": replaced,
            "variables": variable_values,
            "has_unresolved": "{{" in replaced and "}}" in replaced
        }
    
    def validate_template(self, template: str) -> Dict[str, Any]:
        """验证模板格式"""
        errors = []
        warnings = []
        
        # 检查括号匹配
        if template.count("{{") != template.count("}}"):
            errors.append("变量括号不匹配")
        
        # 检查嵌套括号
        if "{{" in template and "}}" in template:
            pattern = r'\{\{([^}]+)\}\}'
            matches = re.findall(pattern, template)
            
            for match in matches:
                var_name = match.strip()
                if not var_name:
                    errors.append("空变量名")
                elif "{{" in var_name or "}}" in var_name:
                    errors.append(f"变量名包含非法字符: {var_name}")
                elif var_name not in self.system_variables and var_name not in self.custom_variables:
                    warnings.append(f"未知变量: {var_name}")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }


class ConditionEvaluator:
    """条件评估器"""
    
    def __init__(self, variable_replacer: VariableReplacer):
        self.variable_replacer = variable_replacer
    
    def evaluate_conditions(self, conditions: list, context: Dict[str, Any]) -> bool:
        """评估条件列表（所有条件都必须为真）"""
        if not conditions:
            return True
        
        for condition in conditions:
            if not self.evaluate_condition(condition, context):
                return False
        
        return True
    
    def evaluate_condition(self, condition: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """评估单个条件"""
        condition_type = condition.get("type", "")
        config = condition.get("config", {})
        
        try:
            if condition_type == "previous_action_success":
                return context.get("previous_action_success", False)
            
            elif condition_type == "previous_action_failed":
                return not context.get("previous_action_success", True)
            
            elif condition_type == "time_range":
                return self._evaluate_time_range(config)
            
            elif condition_type == "weekday":
                return self._evaluate_weekday(config)
            
            elif condition_type == "variable_equals":
                return self._evaluate_variable_equals(config, context)
            
            elif condition_type == "variable_contains":
                return self._evaluate_variable_contains(config, context)
            
            elif condition_type == "variable_greater_than":
                return self._evaluate_variable_comparison(config, context, "gt")
            
            elif condition_type == "variable_less_than":
                return self._evaluate_variable_comparison(config, context, "lt")
            
            else:
                # 未知条件类型，默认为真
                return True
                
        except Exception as e:
            # 条件评估出错，默认为假
            return False
    
    def _evaluate_time_range(self, config: Dict[str, Any]) -> bool:
        """评估时间范围条件"""
        start_time = config.get("start_time", "00:00")
        end_time = config.get("end_time", "23:59")
        
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        
        return start_time <= current_time <= end_time
    
    def _evaluate_weekday(self, config: Dict[str, Any]) -> bool:
        """评估星期条件"""
        weekdays = config.get("weekdays", [])
        if not weekdays:
            return True
        
        # 周一=1, 周二=2, ..., 周日=7
        current_weekday = datetime.now().weekday() + 1
        return current_weekday in weekdays
    
    def _evaluate_variable_equals(self, config: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """评估变量相等条件"""
        variable = config.get("variable", "")
        expected_value = config.get("value", "")
        
        # 替换变量
        variable_template = "{{" + variable + "}}"
        actual_value = self.variable_replacer.replace_variables(variable_template, context)
        
        # 移除模板标记（如果变量不存在）
        if actual_value.startswith("{{") and actual_value.endswith("}}"):
            actual_value = ""
        
        return str(actual_value) == str(expected_value)
    
    def _evaluate_variable_contains(self, config: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """评估变量包含条件"""
        variable = config.get("variable", "")
        search_value = config.get("value", "")
        
        variable_template = "{{" + variable + "}}"
        actual_value = self.variable_replacer.replace_variables(variable_template, context)
        
        if actual_value.startswith("{{") and actual_value.endswith("}}"):
            actual_value = ""
        
        return str(search_value) in str(actual_value)
    
    def _evaluate_variable_comparison(self, config: Dict[str, Any], context: Dict[str, Any], operator: str) -> bool:
        """评估变量比较条件"""
        variable = config.get("variable", "")
        compare_value = config.get("value", 0)
        
        variable_template = "{{" + variable + "}}"
        actual_value = self.variable_replacer.replace_variables(variable_template, context)
        
        if actual_value.startswith("{{") and actual_value.endswith("}}"):
            actual_value = "0"
        
        try:
            actual_num = float(actual_value)
            compare_num = float(compare_value)
            
            if operator == "gt":
                return actual_num > compare_num
            elif operator == "lt":
                return actual_num < compare_num
            else:
                return False
        except (ValueError, TypeError):
            return False