import yfinance as yf
import requests
import datetime
import os
import sys
import time

# --- 配置区 ---
WEBHOOK_URL = os.environ.get("WECHAT_WEBHOOK_URL", "")

# --- 投资标的配置 (四大金刚) ---
TARGETS = [
    # 1. 美股成长 (进攻)
    {
        "name": "纳指100 (QQQ)",
        "symbol": "QQQ",
        "type": "stock_us",  
        "thresholds": {"low": 0, "deep_low": -15, "high": 20} 
    },
    # 2. 全球避险 (防守)
    {
        "name": "国泰黄金 (004253)",
        "symbol": "GC=F", 
        "type": "gold",   
        "thresholds": {"low": 2, "deep_low": -5, "high": 15}  
    },
    # 3. A股基本盘 (稳健) - 适合 002834/001051
    {
        "name": "沪深300 (A股大盘)", 
        "symbol": "000300.SS",  
        "type": "stock_cn_value", 
        "thresholds": {"low": -5, "deep_low": -15, "high": 10}
    },
    # 4. A股高弹性 (激进) - 新增创业板
    {
        "name": "创业板指 (399006)", 
        "symbol": "399006.SZ",  
        "type": "stock_cn_growth", # 新类型：A股成长
        "thresholds": {
            "low": -10,         # 波动大，跌破年线10%才算便宜
            "deep_low": -25,    # 跌破25%是历史级大底 (如2018/2022底)
            "high": 25          # 涨超年线25%必须止盈，防止过山车
        }
    }
]

def get_data_and_calc(target):
    symbol = target["symbol"]
    print(f"正在获取 {target['name']} ({symbol}) 数据...")
    
    try:
        # A股数据获取可能不稳定，增加重试机制
        df = yf.download(symbol, period="2y", progress=False)
        
        # 针对 A 股数据为空的备用方案 (备胎列表)
        if df.empty:
            print(f"{symbol} 数据为空，尝试备用源...")
            if symbol == "000300.SS":
                df = yf.download("ASHR", period="2y", progress=False) # 沪深300 ETF
            elif symbol == "399006.SZ":
                df = yf.download("CNXT", period="2y", progress=False) # 创业板 ETF (美股)
                
    except Exception as e:
        print(f"下载 {symbol} 失败: {e}")
        return None
    
    if df.empty:
        print(f"无法获取 {symbol} 数据，跳过。")
        return None

    try:
        current_price = df['Close'].iloc[-1].item()
        last_date = df.index[-1].strftime('%Y-%m-%d')
        
        # 计算 MA250 (年线)
        ma250 = df['Close'].rolling(window=250).mean().iloc[-1].item()
        bias = (current_price - ma250) / ma250 * 100
        
        # 计算回撤
        high_250 = df['Close'].rolling(window=250).max().iloc[-1].item()
        drawdown = (current_price - high_250) / high_250 * 100
        
        return {
            "name": target['name'],
            "date": last_date,
            "price": round(current_price, 2),
            "ma250": round(ma250, 2),
            "bias": round(bias, 2),
            "drawdown": round(drawdown, 2),
            "target_config": target
        }
    except Exception as e:
        print(f"计算指标出错 {symbol}: {e}")
        return None

def generate_advice(data):
    t = data['target_config']
    bias = data['bias']
    dd = data['drawdown']
    th = t['thresholds']
    
    advice = ""
    level = "normal"
    
    # --- 1. 黄金策略 ---
    if t['type'] == 'gold':
        if bias < th['deep_low']: 
            advice = "💎 **极度低估**：罕见深跌，建议 **2.0倍 囤货**"
            level = "opportunity"
        elif bias < 0: 
            advice = "📀 **跌破年线**：低于成本，建议 **1.5倍 买入**"
            level = "opportunity"
        elif bias < th['low']:
            advice = "⚖️ **关键支撑**：回踩年线，建议 **1.2倍 上车**"
            level = "opportunity"
        elif bias > th['high']:
            advice = "🔥 **短期过热**：建议 **暂停买入**"
            level = "risk"
        else:
            advice = "😐 **趋势向上**：建议 **正常定投**"

    # --- 2. A股蓝筹 (沪深300) ---
    elif t['type'] == 'stock_cn_value':
        if bias < th['deep_low']: 
            advice = "🇨🇳 **遍地黄金**：A股极度低估，建议 **3.0倍 大额买入**"
            level = "opportunity"
        elif bias < th['low']:    
            advice = "💰 **低估区间**：市场便宜，建议 **1.5倍 耐心定投**"
            level = "opportunity"
        elif bias > th['high']:   
            advice = "🚀 **情绪高涨**：建议 **止盈 或 暂停**"
            level = "risk"
        elif bias > 0:
            advice = "😐 **右侧浮盈**：建议 **正常定投**"
            level = "normal"
        else:
            advice = "🐢 **磨底震荡**：建议 **1.0倍 坚持**"
            level = "normal"

    # --- 3. A股成长 (创业板) - 新增逻辑 ---
    elif t['type'] == 'stock_cn_growth':
        # 创业板特性：深蹲起跳，波动极大
        if bias < th['deep_low']: # < -25%
            advice = "⚡ **血流成河**：创业板崩盘式下跌，建议 **4.0倍 极限抄底**"
            level = "opportunity"
        elif bias < th['low']:    # < -10%
            advice = "📉 **击穿防线**：跌破年线10%，建议 **2.0倍 越跌越买**"
            level = "opportunity"
        elif dd < -30:            # 高点回撤超过30%
            advice = "🎢 **深幅回撤**：较高点打7折，建议 **1.5倍 捡带血筹码**"
            level = "opportunity"
        elif bias > th['high']:   # > 25%
            advice = "💣 **极度泡沫**：偏离年线过大，建议 **清仓止盈 走人**"
            level = "risk"
        else:
            advice = "🎲 **高波震荡**：看不清方向，建议 **少投 或 观望**"
            level = "normal"

    # --- 4. 美股成长 (纳指) ---
    else: 
        if bias < th['deep_low']: 
            advice = "💎 **钻石坑**：极度贪婪时刻，建议 **3倍 梭哈**"
            level = "opportunity"
        elif bias < 0:
            advice = "📀 **黄金坑**：年线下方，建议 **2倍 加码**"
            level = "opportunity"
        elif dd < -15:
            advice = "📉 **急跌机会**：回撤超15%，建议 **1.5倍 捡筹码**"
            level = "opportunity"
        elif bias > th['high']:
            advice = "🚫 **极度过热**：建议 **止盈 或 观望**"
            level = "risk"
        else:
            advice = "😐 **正常区间**：建议 **正常定投**"
            
    return advice, level

def send_combined_notification(results):
    if not results: return
    current_date = results[0]['date']
    markdown_content = f"## 🤖 全球定投日报\n**日期**: {current_date}\n\n"
    
    for item in results:
        advice, level = generate_advice(item)
        title_color = "warning" if level == "risk" else "info"
        if level == "normal": title_color = "comment"
        
        # 图标区分
        t_type = item['target_config']['type']
        if 'us' in t_type: icon = "🇺🇸"
        elif 'gold' in t_type: icon = "🧈"
        elif 'growth' in t_type: icon = "⚡" # 创业板用闪电
        else: icon = "🇨🇳"
        
        block = f"""
---
### {icon} <font color="{title_color}">{item['name']}</font>
- **年线乖离**: {item['bias']}%
- **高点回撤**: {item['drawdown']}%
> **策略**: {advice}
"""
        markdown_content += block

    payload = {"msgtype": "markdown", "markdown": {"content": markdown_content.strip()}}
    
    if WEBHOOK_URL:
        try:
            requests.post(WEBHOOK_URL, json=payload)
            print("✅ 消息发送成功")
        except Exception as e:
            print(f"❌ 发送失败: {e}")

if __name__ == "__main__":
    results = []
    for target in TARGETS:
        data = get_data_and_calc(target)
        if data:
            results.append(data)
    
    send_combined_notification(results)
