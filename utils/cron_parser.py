"""Cron表达式解析器"""
import re
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
import calendar


class CronParser:
    """Cron表达式解析器 - 支持标准的5字段格式: 分 时 日 月 周"""
    
    # 预定义的特殊表达式
    SPECIAL_EXPRESSIONS = {
        "@yearly": "0 0 1 1 *",
        "@annually": "0 0 1 1 *", 
        "@monthly": "0 0 1 * *",
        "@weekly": "0 0 * * 0",
        "@daily": "0 0 * * *",
        "@midnight": "0 0 * * *",
        "@hourly": "0 * * * *"
    }
    
    def __init__(self):
        self.minute_pattern = r'^(\*|[0-5]?\d(-[0-5]?\d)?|\*/\d+|(\d+,)*\d+)$'
        self.hour_pattern = r'^(\*|[01]?\d|2[0-3](-[01]?\d|2[0-3])?|\*/\d+|(\d+,)*\d+)$'
        self.day_pattern = r'^(\*|[1-9]|[12]\d|3[01](-[1-9]|[12]\d|3[01])?|\*/\d+|(\d+,)*\d+)$'
        self.month_pattern = r'^(\*|[1-9]|1[0-2](-[1-9]|1[0-2])?|\*/\d+|(\d+,)*\d+)$'
        self.weekday_pattern = r'^(\*|[0-6](-[0-6])?|\*/\d+|(\d+,)*\d+)$'
    
    def parse(self, cron_expression: str) -> bool:
        """验证Cron表达式是否合法"""
        try:
            cron_expression = cron_expression.strip()
            
            # 处理特殊表达式
            if cron_expression in self.SPECIAL_EXPRESSIONS:
                cron_expression = self.SPECIAL_EXPRESSIONS[cron_expression]
            
            fields = cron_expression.split()
            if len(fields) != 5:
                return False
            
            minute, hour, day, month, weekday = fields
            
            patterns = [
                self.minute_pattern,
                self.hour_pattern, 
                self.day_pattern,
                self.month_pattern,
                self.weekday_pattern
            ]
            
            for field, pattern in zip(fields, patterns):
                if not re.match(pattern, field):
                    return False
            
            return True
        except Exception:
            return False
    
    def get_next_run_time(self, cron_expression: str, from_time: Optional[datetime] = None) -> Optional[datetime]:
        """计算下次运行时间"""
        if not self.parse(cron_expression):
            return None
        
        if from_time is None:
            from_time = datetime.now()
        
        # 处理特殊表达式
        if cron_expression in self.SPECIAL_EXPRESSIONS:
            cron_expression = self.SPECIAL_EXPRESSIONS[cron_expression]
        
        try:
            minute, hour, day, month, weekday = cron_expression.split()
            
            # 从下一分钟开始计算
            next_time = from_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
            
            # 最多向前查找一年
            max_iterations = 366 * 24 * 60
            iterations = 0
            
            while iterations < max_iterations:
                if self._matches_cron(next_time, minute, hour, day, month, weekday):
                    return next_time
                
                next_time += timedelta(minutes=1)
                iterations += 1
            
            return None
        except Exception:
            return None
    
    def _matches_cron(self, dt: datetime, minute: str, hour: str, day: str, month: str, weekday: str) -> bool:
        """检查时间是否匹配Cron表达式"""
        try:
            # 检查分钟
            if not self._matches_field(dt.minute, minute, 0, 59):
                return False
            
            # 检查小时
            if not self._matches_field(dt.hour, hour, 0, 23):
                return False
            
            # 检查月份
            if not self._matches_field(dt.month, month, 1, 12):
                return False
            
            # 检查日期和星期 (两者是OR关系)
            day_match = self._matches_field(dt.day, day, 1, 31)
            # weekday: 0=周日, 1=周一, ..., 6=周六
            weekday_match = self._matches_field(dt.weekday() + 1 if dt.weekday() != 6 else 0, weekday, 0, 6)
            
            # 如果日期和星期都不是通配符，则只要其中一个匹配即可
            if day != "*" and weekday != "*":
                return day_match or weekday_match
            else:
                return day_match and weekday_match
            
        except Exception:
            return False
    
    def _matches_field(self, value: int, pattern: str, min_val: int, max_val: int) -> bool:
        """检查字段是否匹配"""
        if pattern == "*":
            return True
        
        try:
            # 处理逗号分隔的值
            if "," in pattern:
                values = [int(v.strip()) for v in pattern.split(",")]
                return value in values
            
            # 处理步长 */n
            if pattern.startswith("*/"):
                step = int(pattern[2:])
                return value % step == 0
            
            # 处理范围 n-m
            if "-" in pattern:
                start, end = map(int, pattern.split("-"))
                return start <= value <= end
            
            # 处理单个值
            return value == int(pattern)
            
        except (ValueError, IndexError):
            return False
    
    def describe(self, cron_expression: str) -> str:
        """将Cron表达式转换为可读描述"""
        if not self.parse(cron_expression):
            return "无效的Cron表达式"
        
        # 处理特殊表达式
        special_descriptions = {
            "@yearly": "每年执行一次 (1月1日 00:00)",
            "@annually": "每年执行一次 (1月1日 00:00)",
            "@monthly": "每月执行一次 (每月1日 00:00)",
            "@weekly": "每周执行一次 (周日 00:00)",
            "@daily": "每日执行一次 (00:00)",
            "@midnight": "每日执行一次 (00:00)",
            "@hourly": "每小时执行一次"
        }
        
        if cron_expression in special_descriptions:
            return special_descriptions[cron_expression]
        
        try:
            minute, hour, day, month, weekday = cron_expression.split()
            
            parts = []
            
            # 分钟
            if minute == "*":
                parts.append("每分钟")
            elif minute.startswith("*/"):
                step = minute[2:]
                parts.append(f"每{step}分钟")
            else:
                parts.append(f"第{minute}分钟")
            
            # 小时
            if hour == "*":
                if minute != "*":
                    parts.append("每小时")
            elif hour.startswith("*/"):
                step = hour[2:]
                parts.append(f"每{step}小时")
            else:
                parts.append(f"{hour}点")
            
            # 日期
            if day == "*":
                if hour != "*" or minute != "*":
                    parts.append("每天")
            elif day.startswith("*/"):
                step = day[2:]
                parts.append(f"每{step}天")
            else:
                parts.append(f"每月{day}日")
            
            # 月份
            if month != "*":
                if month.startswith("*/"):
                    step = month[2:]
                    parts.append(f"每{step}个月")
                else:
                    parts.append(f"{month}月")
            
            # 星期
            if weekday != "*":
                weekday_names = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
                if weekday.startswith("*/"):
                    step = weekday[2:]
                    parts.append(f"每{step}周")
                elif weekday in ["0", "1", "2", "3", "4", "5", "6"]:
                    parts.append(weekday_names[int(weekday)])
            
            return " ".join(parts) if parts else "每分钟执行"
            
        except Exception:
            return "Cron表达式描述解析失败"


class IntervalParser:
    """间隔时间解析器"""
    
    @staticmethod
    def parse_interval(interval_str: str) -> Optional[int]:
        """解析间隔时间字符串，返回秒数"""
        try:
            # 支持格式: 30s, 5m, 2h, 1d
            pattern = r'^(\d+)([smhd])$'
            match = re.match(pattern, interval_str.lower().strip())
            
            if not match:
                return None
            
            value, unit = match.groups()
            value = int(value)
            
            multipliers = {
                's': 1,          # 秒
                'm': 60,         # 分钟
                'h': 3600,       # 小时
                'd': 86400       # 天
            }
            
            return value * multipliers.get(unit, 1)
            
        except (ValueError, AttributeError):
            return None
    
    @staticmethod
    def describe_interval(seconds: int) -> str:
        """将秒数转换为可读描述"""
        if seconds < 60:
            return f"{seconds}秒"
        elif seconds < 3600:
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            if remaining_seconds == 0:
                return f"{minutes}分钟"
            else:
                return f"{minutes}分钟{remaining_seconds}秒"
        elif seconds < 86400:
            hours = seconds // 3600
            remaining_minutes = (seconds % 3600) // 60
            if remaining_minutes == 0:
                return f"{hours}小时"
            else:
                return f"{hours}小时{remaining_minutes}分钟"
        else:
            days = seconds // 86400
            remaining_hours = (seconds % 86400) // 3600
            if remaining_hours == 0:
                return f"{days}天"
            else:
                return f"{days}天{remaining_hours}小时"


# 自然语言时间解析器
class NaturalTimeParser:
    """自然语言时间解析器"""
    
    # 周日映射字典
    WEEKDAY_MAP = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '日': 0}
    
    TIME_PATTERNS = {
        r'每天(\d{1,2})点(\d{1,2})分?': lambda m: f"{m.group(2)} {m.group(1)} * * *",
        r'每天(\d{1,2})点': lambda m: f"0 {m.group(1)} * * *",
        r'每小时': lambda m: "0 * * * *",
        r'每(\d+)分钟': lambda m: f"*/{m.group(1)} * * * *",
        r'每周([一二三四五六日])(\d{1,2})点': lambda m: f"0 {m.group(2)} * * {NaturalTimeParser.WEEKDAY_MAP[m.group(1)]}",
        r'每月(\d{1,2})日(\d{1,2})点': lambda m: f"0 {m.group(2)} {m.group(1)} * *",
    }
    
    @classmethod
    def parse(cls, natural_text: str) -> Optional[str]:
        """将自然语言转换为Cron表达式"""
        text = natural_text.strip()
        
        for pattern, converter in cls.TIME_PATTERNS.items():
            match = re.search(pattern, text)
            if match:
                try:
                    return converter(match)
                except (IndexError, ValueError):
                    continue
        
        return None