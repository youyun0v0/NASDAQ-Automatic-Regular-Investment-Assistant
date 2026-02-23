import yfinance as yf
import requests
import datetime
import os
import sys
import time
import math

# --- 配置区 ---
WEBHOOK_URL = os.environ.get("WECHAT_WEBHOOK_URL", "")

# --- 投资标的配置 (策略矩阵) ---
# 注意：backup_symbol 是为了防止主代码获取失败或数据不足
TARGETS = [
    # 1. 美股成长 (进攻)
    {
        "name": "纳指100 (QQQ)",
        "symbol": "QQQ",
        "backup_symbol": None, # 美股数据通常很稳，不需要备胎
        "type": "stock_us",  
        "thresholds": {"low": 0, "deep_low": -15, "high": 20},
        "desc": "🇺🇸 科技成长"
    },
    # 2. 全球避险 (防守)
    {
        "name": "国泰黄金 (004253)",
        "symbol": "GC=F", 
        "backup_symbol": "GLD", # 备用：SPDR黄金ETF
        "type": "gold",   
        "thresholds": {"low": 2, "deep_low": -5, "high": 15},
        "desc": "🧈 全球硬通货"
    },
    # 3. A股基本盘 (稳健)
    {
        "name": "沪深300 (A股大盘)", 
        "symbol": "000300.SS",  
        "backup_symbol": "ASHR", # 备用：Xtrackers Harvest CSI 300 ETF
        "type": "stock_cn_value", 
        "thresholds": {"low": -5, "deep_low": -15, "high": 10},
        "desc": "🇨🇳 核心蓝筹"
    },
    # 4. A股高弹性 (激进)
    {
        "name": "创业板指 (399006)", 
        "symbol": "399006.SZ",  
        "backup_symbol": "CNXT", # 备用：VanEck ChiNext ETF (非常关键的修复)
        "type": "stock_cn_growth", 
        "thresholds": {"low": -10, "deep_low": -25, "high": 25},
        "desc": "⚡ 新兴成长"
    }
]

def fetch_data(symbol):
    """尝试获取数据，确保长度足够计算年线"""
    try:
        # 获取过去 2 年数据，保证有足够的历史来算 MA250
        df = yf.download(symbol, period="2y", progress=False)
        # 检查数据有效性：至少需要 250 行才能算出今天的 MA250
        if df.empty or len(df) < 250:
            return None
        return df
    except:
        return None

def get_data_and_calc(target):
    """智能数据获取：主代码失败则自动切备用"""
    symbol = target["symbol"]
    name = target["name"]
    print(f"正在获取 {name} ({symbol})...")
    
    # 1. 尝试主代码
    df = fetch_data(symbol)
    
    # 2. 如果失败，尝试备用代码
    if df is None and target.get("backup_symbol"):
        backup = target["backup_symbol"]
        print(f"⚠️ {symbol} 数据异常，切换备用源: {backup}")
        df = fetch_data(backup)
        symbol = backup # 更新当前使用的代码以便记录
    
    if df is None:
        print(f"❌ {name} 所有数据源均不可用，跳过。")
        return None

    try:
        # 提取数据 (.item() 确保转换为 Python 原生 float)
        current_price = df['Close'].iloc[-1].item()
        last_date = df.index[-1].strftime('%Y-%m-%d')
        
        # 计算 MA250 (年线)
        ma250 = df['Close'].rolling(window=250).mean().iloc[-1].item()
        
        # 二次检查：如果算出来是 NaN (说明中间有断档)，则视为失败
        if math.isnan(ma250):
            print(f"❌ {name} 数据长度不足以计算年线(NaN)，跳过。")
            return None

        # 计算乖离率 Bias
        bias = (current_price - ma250) / ma250 * 100
        
        # 计算回撤 (250日高点)
        high_250 = df['Close'].rolling(window=250).max().iloc[-1].item()
        drawdown = (current_price - high_250) / high_250 * 100
        
        return {
            "name": name,
            "used_symbol": symbol,
            "date": last_date,
            "price": round(current_price, 2),
            "ma250": round(ma250, 2),
            "bias": round(bias, 2),
            "drawdown": round(drawdown, 2),
            "target_config": target
        }
    except Exception as e:
        print(f"❌ 计算指标出错 {name}: {e}")
        return None

def generate_advice(data):
    """生成具体的投资建议"""
    t = data['target_config']
    bias = data['bias']
    dd = data['drawdown']
    th = t['thresholds']
    
    advice = ""
    level = "normal"
    
    # --- 1. 黄金策略 ---
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

    # --- 2. A股蓝筹 ---
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

    # --- 3. A股成长 (创业板) ---
    elif t['type'] == 'stock_cn_growth':
        if bias < th['deep_low']: 
            advice = "⚡ **血流成河**：崩盘式下跌，建议 **4.0倍 极限抄底**"
            level = "opportunity"
        elif bias < th['low']:    
            advice = "📉 **击穿防线**：跌破年线10%，建议 **2.0倍 越跌越买**"
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

    # --- 4. 美股成长 ---
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

def get_strategy_summary_text():
    """生成策略汇总文本"""
    summary = "\n--- \n### 📖 策略说明书 (Strategy Guide)\n"
    summary += "| 标的 | 加仓线(Bias) | 抄底线(Bias) | 止盈线(Bias) |\n"
    summary += "| :--- | :--- | :--- | :--- |\n"
    
    for t in TARGETS:
        th = t['thresholds']
        # 格式化输出
        name_short = t['name'].split("(")[0]
        line = f"| {name_short} | < {th['low']}% | < {th['deep_low']}% | > {th['high']}% |\n"
        summary += line
    
    summary += "\n> **注**: Bias(乖离率) = (当前价 - 年线) / 年线"
    return summary

def send_combined_notification(results):
    if not results: return
    current_date = results[0]['date']
    
    # 1. 标题和日期
    markdown_content = f"## 🤖 全球定投日报\n**日期**: {current_date}\n\n"
    
    # 2. 遍历生成每个标的的卡片
    for item in results:
        advice, level = generate_advice(item)
        
        # 颜色处理
        title_color = "warning" if level == "risk" else "info"
        if level == "normal": title_color = "comment" # 灰色
        
        # 图标区分
        t_type = item['target_config']['type']
        if 'us' in t_type: icon = "🇺🇸"
        elif 'gold' in t_type: icon = "🧈"
        elif 'growth' in t_type: icon = "⚡"
        else: icon = "🇨🇳"
        
        block = f"""
---
### {icon} <font color="{title_color}">{item['name']}</font>
- **当前价格**: {item['price']}
- **年线乖离**: {item['bias']}%
- **高点回撤**: {item['drawdown']}%
> **策略**: {advice}
"""
        markdown_content += block

    # 3. 在最下方附加策略说明书
    markdown_content += get_strategy_summary_text()

    payload = {"msgtype": "markdown", "markdown": {"content": markdown_content.strip()}}
    
    if WEBHOOK_URL:
        try:
            requests.post(WEBHOOK_URL, json=payload)
            print("✅ 消息发送成功")
        except Exception as e:
            print(f"❌ 发送失败: {e}")
    else:
        print("本地测试 - 消息内容预览:")
        print(markdown_content)

if __name__ == "__main__":
    results = []
    print("🚀 启动自动定投分析...")
    for target in TARGETS:
        data = get_data_and_calc(target)
        if data:
            results.append(data)
        else:
            print(f"⚠️ 跳过 {target['name']} (数据获取失败)")
    
    send_combined_notification(results)
    print("🏁 运行结束")
