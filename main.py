import yfinance as yf
import requests
import datetime
import os
import sys
import time

# --- 配置区 ---
WEBHOOK_URL = os.environ.get("WECHAT_WEBHOOK_URL", "")

# 定义我们要监控的标的列表
# 004253 对应国际黄金 GC=F
TARGETS = [
    {
        "name": "纳指100 (QQQ)",
        "symbol": "QQQ",
        "type": "stock",  # 股票/指数类型
        "thresholds": {"low": 0, "deep_low": -10, "high": 20} # 纳指波动大，阈值宽
    },
    {
        "name": "国泰黄金 (004253)",
        "symbol": "GC=F", # 使用COMEX黄金期货作为影子标的
        "type": "gold",   # 黄金类型
        "thresholds": {"low": 2, "deep_low": -5, "high": 15}  # 黄金波动小，阈值窄
    }
]

def get_data_and_calc(target):
    """通用数据获取与计算函数"""
    symbol = target["symbol"]
    print(f"正在获取 {target['name']} ({symbol}) 数据...")
    
    try:
        # 黄金有时候会有数据延迟，多取一点数据保证能算出均线
        df = yf.download(symbol, period="2y", progress=False)
        time.sleep(1) # 防止请求过快被封
    except Exception as e:
        print(f"下载 {symbol} 失败: {e}")
        return None
    
    if df.empty:
        print(f"{symbol} 数据为空")
        return None

    # 提取最新价格
    try:
        current_price = df['Close'].iloc[-1].item()
        last_date = df.index[-1].strftime('%Y-%m-%d')
        
        # 计算 MA200 (黄金和美股常看200日线，也可用250)
        ma200 = df['Close'].rolling(window=200).mean().iloc[-1].item()
        
        # 计算乖离率 Bias = (价格 - 均线) / 均线
        bias = (current_price - ma200) / ma200 * 100
        
        # 计算回撤 (从250日高点跌了多少)
        high_250 = df['Close'].rolling(window=250).max().iloc[-1].item()
        drawdown = (current_price - high_250) / high_250 * 100
        
        return {
            "name": target['name'],
            "date": last_date,
            "price": round(current_price, 2),
            "ma200": round(ma200, 2),
            "bias": round(bias, 2),
            "drawdown": round(drawdown, 2),
            "target_config": target
        }
    except Exception as e:
        print(f"计算指标出错 {symbol}: {e}")
        return None

def generate_advice(data):
    """根据不同标的类型生成策略"""
    t = data['target_config']
    bias = data['bias']
    dd = data['drawdown']
    th = t['thresholds'] # 读取各自的阈值配置
    
    advice = ""
    level = "normal" # 级别：opportunity, normal, risk
    
    # --- 黄金特有策略逻辑 ---
    if t['type'] == 'gold':
        # 黄金看重趋势跟随，回调买入
        if bias < th['deep_low']: # 比如低于年线5%
            advice = "💎 **极度低估**：黄金罕见深跌，建议 **双倍定投**"
            level = "opportunity"
        elif bias < 0: 
            advice = "📀 **跌破年线**：价格低于长期均线，建议 **1.5倍 积累筹码**"
            level = "opportunity"
        elif bias < th['low']: # 比如 0% ~ 2% 之间，贴着年线运行
            advice = "⚖️ **支撑位**：回踩年线支撑，建议 **1.2倍 买入**"
            level = "opportunity"
        elif bias > th['high']:
            advice = "🔥 **短期过热**：偏离年线过大，建议 **暂停买入**"
            level = "risk"
        else:
            advice = "😐 **趋势向上**：温和上涨中，建议 **正常定投**"
            level = "normal"

    # --- 纳指/股票策略逻辑 ---
    else:
        if bias < th['deep_low']: # 低于年线10%
            advice = "💎 **钻石坑**：极度贪婪时刻，建议 **3倍 梭哈级定投**"
            level = "opportunity"
        elif bias < 0:
            advice = "📀 **黄金坑**：年线下方，建议 **2倍 加码定投**"
            level = "opportunity"
        elif dd < -15:
            advice = "📉 **急跌机会**：高点回撤超15%，建议 **1.5倍 捡筹码**"
            level = "opportunity"
        elif bias > th['high']:
            advice = "🚫 **极度过热**：风险极大，建议 **止盈 或 观望**"
            level = "risk"
        else:
            advice = "😐 **正常区间**：建议 **正常定投**"
            level = "normal"
            
    return advice, level

def send_combined_notification(results):
    """发送合并后的消息"""
    if not results:
        return

    # 构造消息头部
    current_date = results[0]['date']
    markdown_content = f"## 🤖 智能定投日报\n**日期**: {current_date}\n\n"
    
    for item in results:
        advice, level = generate_advice(item)
        
        # 颜色标记
        title_color = "info" # 默认绿
        if level == "risk": title_color = "warning" # 红
        if level == "normal": title_color = "comment" # 灰/黑
        
        # 不同的标的显示不同的 Emoji
        icon = "🇺🇸" if item['target_config']['type'] == 'stock' else "🧈"
        
        block = f"""
---
### {icon} <font color="{title_color}">{item['name']}</font>
- **价格**: {item['price']}
- **年线乖离**: {item['bias']}% (MA200)
- **高点回撤**: {item['drawdown']}%
> **策略**: {advice}
"""
        markdown_content += block

    payload = {
        "msgtype": "markdown",
        "markdown": {"content": markdown_content.strip()}
    }
    
    if WEBHOOK_URL:
        try:
            requests.post(WEBHOOK_URL, json=payload)
            print("✅ 消息发送成功")
        except Exception as e:
            print(f"❌ 发送失败: {e}")
    else:
        print("未配置 Webhook，跳过发送")
        print(markdown_content)

if __name__ == "__main__":
    results = []
    for target in TARGETS:
        data = get_data_and_calc(target)
        if data:
            results.append(data)
    
    send_combined_notification(results)
