import yfinance as yf
import requests
import datetime
import os
import sys
import math

# --- 配置区 ---
WEBHOOK_URL = os.environ.get("WECHAT_WEBHOOK_URL", "")

# --- 投资标的配置 ---
TARGETS = [
    {
        "name": "纳指100 (QQQ)",
        "symbol": "QQQ",
        "backup_symbol": None,
        "type": "stock_us",
        "currency": "$",
        "thresholds": {"low": 0, "deep_low": -15, "high": 20},
    },
    {
        "name": "国泰黄金 (004253)",
        "symbol": "GC=F", 
        "backup_symbol": "GLD", 
        "type": "gold",
        "currency": "$",
        "thresholds": {"low": 2, "deep_low": -5, "high": 15},
    },
    {
        "name": "沪深300 (A股大盘)", 
        "symbol": "000300.SS",  
        "backup_symbol": "ASHR", 
        "type": "stock_cn_value", 
        "currency": "¥",
        "thresholds": {"low": -5, "deep_low": -15, "high": 10},
    },
    {
        "name": "创业板指 (399006)", 
        "symbol": "399006.SZ",  
        "backup_symbol": "CNXT", 
        "type": "stock_cn_growth", 
        "currency": "¥",
        "thresholds": {"low": -10, "deep_low": -25, "high": 25},
    }
]

def fetch_data(symbol):
    """尝试获取数据 (使用更稳定的 Ticker API)"""
    try:
        # 使用 Ticker 对象获取历史数据，比 download 更稳定
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="2y")
        
        if df is None or df.empty:
            print(f"  -> 获取到的 {symbol} 数据为空")
            return None
            
        # 检查是否包含 Close 列
        if 'Close' not in df.columns:
            print(f"  -> {symbol} 返回的数据缺少 'Close' 列。当前列名: {list(df.columns)}")
            return None
            
        # 清理 NaN 数据
        df = df.dropna(subset=['Close'])
        
        # 检查数据长度是否足够计算 250 日均线
        if len(df) < 250:
            print(f"  -> {symbol} 数据长度不足 250 天 (仅 {len(df)} 天)")
            return None
            
        return df
    except Exception as e:
        print(f"  -> 获取 {symbol} 发生异常: {e}")
        return None

def get_data_and_calc(target):
    """智能数据获取与计算"""
    symbol = target["symbol"]
    name = target["name"]
    print(f"正在获取 {name} ({symbol})...")
    
    # 主备切换逻辑
    df = fetch_data(symbol)
    if df is None and target.get("backup_symbol"):
        backup = target["backup_symbol"]
        print(f"⚠️ 切换备用源: {backup}")
        df = fetch_data(backup)
        symbol = backup
    
    if df is None:
        print(f"❌ {name} 数据获取彻底失败")
        return None

    try:
        # 获取最新价和昨日收盘价 (使用原生 float 类型)
        current_price = float(df['Close'].iloc[-1])
        prev_price = float(df['Close'].iloc[-2])
        last_date = df.index[-1].strftime('%Y-%m-%d')
        
        # 计算涨跌幅
        daily_change = (current_price - prev_price) / prev_price * 100
        
        # 计算 MA250
        ma250 = float(df['Close'].rolling(window=250).mean().iloc[-1])
        if math.isnan(ma250): 
            print(f"  -> {name} 计算出的 MA250 为 NaN")
            return None 

        # 计算指标
        bias = (current_price - ma250) / ma250 * 100
        high_250 = float(df['Close'].rolling(window=250).max().iloc[-1])
        drawdown = (current_price - high_250) / high_250 * 100
        
        return {
            "name": name,
            "date": last_date,
            "price": round(current_price, 2),
            "daily_change": round(daily_change, 2), 
            "bias": round(bias, 2),
            "drawdown": round(drawdown, 2),
            "target_config": target
        }
    except Exception as e:
        print(f"❌ 计算指标出错 {name}: {e}")
        return None

def generate_advice(data):
    """生成具体的策略建议"""
    t = data['target_config']
    bias = data['bias']
    dd = data['drawdown']
    th = t['thresholds']
    
    advice = ""
    level = "normal"
    
    if t['type'] == 'gold':
        if bias < th['deep_low']: 
            advice = "💎 **极度低估**：罕见机会，建议 **2.0倍 囤货**"
            level = "opportunity"
        elif bias < 0: 
            advice = "📀 **跌破年线**：低于成本，建议 **1.5倍 买入**"
            level = "opportunity"
        elif bias < th['low']:
            advice = "⚖️ **支撑位**：回踩年线，建议 **1.2倍 上车**"
            level = "opportunity"
        elif bias > th['high']:
            advice = "🔥 **短期过热**：建议 **暂停买入**"
            level = "risk"
        else:
            advice = "😐 **趋势向上**：建议 **正常定投**"

    elif t['type'] == 'stock_cn_value':
        if bias < th['deep_low']: 
            advice = "🇨🇳 **遍地黄金**：极度低估，建议 **3.0倍 大额买入**"
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

    elif t['type'] == 'stock_cn_growth':
        if bias < th['deep_low']: 
            advice = "⚡ **血流成河**：崩盘下跌，建议 **4.0倍 极限抄底**"
            level = "opportunity"
        elif bias < th['low']:    
            advice = "📉 **击穿防线**：跌破年线，建议 **2.0倍 越跌越买**"
            level = "opportunity"
        elif dd < -30:            
            advice = "🎢 **深幅回撤**：回撤超30%，建议 **1.5倍 捡带血筹码**"
            level = "opportunity"
        elif bias > th['high']:   
            advice = "💣 **极度泡沫**：建议 **清仓止盈 走人**"
            level = "risk"
        else:
            advice = "🎲 **高波震荡**：看不清方向，建议 **少投 或 观望**"
            level = "normal"

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

def get_pretty_strategy_text():
    """生成美观的策略列表"""
    text = "\n\n---\n### 📖 策略说明书\n"
    for t in TARGETS:
        name_short = t['name'].split("(")[0]
        th = t['thresholds']
        t_type = t['type']
        
        if 'us' in t_type: icon = "🇺🇸"
        elif 'gold' in t_type: icon = "🧈"
        elif 'growth' in t_type: icon = "⚡"
        else: icon = "🇨🇳"
        
        text += f"**{icon} {name_short}**\n"
        
        if 'growth' in t_type:
            text += f"- ⚡ **血流成河**: 偏离 < {th['deep_low']}% (4倍抄底)\n"
            text += f"- 💣 **极度泡沫**: 偏离 > {th['high']}% (清仓走人)\n"
        elif 'gold' in t_type:
            text += f"- 💎 **极度低估**: 偏离 < {th['deep_low']}% (2倍囤货)\n"
            text += f"- 🔥 **短期过热**: 偏离 > {th['high']}% (暂停买入)\n"
        elif 'value' in t_type:
            text += f"- 🇨🇳 **遍地黄金**: 偏离 < {th['deep_low']}% (3倍大额)\n"
            text += f"- 🚀 **情绪高涨**: 偏离 > {th['high']}% (止盈/暂停)\n"
        else:
            text += f"- 💎 **钻石坑位**: 偏离 < {th['deep_low']}% (3倍梭哈)\n"
            text += f"- 🚫 **极度过热**: 偏离 > {th['high']}% (止盈/观望)\n"
        text += "\n"
        
    text += "> <font color=\"comment\">注：偏离指当前价与年线(MA250)的距离</font>"
    return text

def send_combined_notification(results):
    if not results: 
        print("没有可发送的数据！")
        return
    
    bjt_time = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')
    markdown_content = f"## 🤖 全球定投日报\n**时间**: {bjt_time}\n\n"
    
    for item in results:
        advice, level = generate_advice(item)
        title_color = "warning" if level == "risk" else "info"
        if level == "normal": title_color = "comment"
        
        t = item['target_config']
        t_type = t['type']
        currency = t.get('currency', '')
        
        if 'us' in t_type: icon = "🇺🇸"
        elif 'gold' in t_type: icon = "🧈"
        elif 'growth' in t_type: icon = "⚡"
        else: icon = "🇨🇳"
        
        change = item['daily_change']
        if change > 0: change_str = f"+{change}% 📈"
        elif change < 0: change_str = f"{change}% 📉"
        else: change_str = "0.00% ➖"
        
        block = f"""
---
### {icon} <font color="{title_color}">{item['name']}</font>
- **当前价格**: {currency}{item['price']} ({change_str})
- **年线乖离**: {item['bias']}%
- **高点回撤**: {item['drawdown']}%
> **策略**: {advice}
"""
        markdown_content += block

    markdown_content += get_pretty_strategy_text()
    payload = {"msgtype": "markdown", "markdown": {"content": markdown_content.strip()}}
    
    if WEBHOOK_URL:
        try:
            requests.post(WEBHOOK_URL, json=payload)
            print("✅ 消息发送成功")
        except Exception as e:
            print(f"❌ 发送失败: {e}")
    else:
        print(markdown_content)

if __name__ == "__main__":
    results = []
    print("🚀 启动分析...")
    for target in TARGETS:
        data = get_data_and_calc(target)
        if data: results.append(data)
    
    send_combined_notification(results)
    print("🏁 结束")
