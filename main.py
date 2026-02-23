import yfinance as yf
import requests
import datetime
from scipy import stats
import os

# 配置区
# 你的企业微信机器人 Webhook 地址
# 如果在 GitHub Actions 运行，建议从环境变量读取，本地运行可直接填入
WEBHOOK_URL = os.environ.get("WECHAT_WEBHOOK_URL", "你的Webhook地址填在这里")

# 标的：纳斯达克100 ETF (QQQ) 代替指数，数据更全
TICKER = "QQQ" 
# 回溯年限（计算百分位用）
YEARS = 5 

def get_market_data_advanced():
    # 获取过去 2 年数据 (计算年线需要至少250天，计算回撤需要看近期高点)
    df = yf.download(TICKER, period="2y", progress=False)
    
    current_price = df['Close'].iloc[-1].item()
    
    # 1. 计算年线偏离度 (Bias)
    ma250 = df['Close'].rolling(window=250).mean().iloc[-1].item()
    bias = (current_price - ma250) / ma250 * 100
    
    # 2. 计算距离 250 天内最高价的回撤幅度 (Drawdown)
    # 这一步是为了看“现在买比最高点便宜了多少”
    high_250 = df['Close'].rolling(window=250).max().iloc[-1].item()
    drawdown = (current_price - high_250) / high_250 * 100
    
    return {
        "date": df.index[-1].strftime('%Y-%m-%d'),
        "price": round(current_price, 2),
        "ma250": round(ma250, 2),
        "bias": round(bias, 2),       # 比如 15.5%
        "drawdown": round(drawdown, 2) # 比如 -5.2%
    }

def get_strategy_advanced(data):
    bias = data['bias']
    dd = data['drawdown']
    
    # 纳斯达克定投 黄金策略矩阵
    # 逻辑：只要跌破年线，或者从高点回撤够深，就加码
    
    advice = ""
    factor = 0.0
    color = "info"
    
    if bias < -10:
        advice = "💎 **钻石坑位**：低于年线10%以上，建议 **2.0倍 - 3.0倍 梭哈级定投**"
        factor = 2.5
        color = "info" # 绿色
    elif bias < 0:
        advice = "📀 **黄金坑位**：价格在年线下方，建议 **1.5倍 - 2.0倍 加倍定投**"
        factor = 1.8
        color = "info"
    elif dd < -15:
         # 即使在年线上方，如果短期回撤超过15%，也是好机会（牛市回头草）
        advice = "📉 **急跌机会**：较高点回撤超15%，建议 **1.5倍 捡筹码**"
        factor = 1.5
        color = "info"
    elif 0 <= bias < 15:
        advice = "😐 **正常区间**：趋势向上但未过热，建议 **1.0倍 正常定投**"
        factor = 1.0
        color = "warning"
    elif bias >= 15 and bias < 25:
        advice = "🔥 **略微过热**：偏离年线超15%，建议 **0.5倍 减少定投**"
        factor = 0.5
        color = "warning"
    else: # bias >= 25
        advice = "🚫 **极度过热**：偏离年线超25%，风险极大，建议 **暂停买入 或 止盈**"
        factor = 0.0
        color = "warning" # 红色
        
    return advice, color, factor
def send_wechat_notification(data, advice):
    """发送 Markdown 消息到企业微信"""
    
    markdown_content = f"""
## 🤖 纳斯达克定投助手
**日期**: {data['date']}
**标的**: {TICKER} (纳指100 ETF)

---
### 📊 市场数据
- **当前价格**: ${data['price']}
- **{YEARS}年内百分位**: <font color=\"comment\">{data['percentile']}%</font>
- **年线(MA250)**: ${data['ma250']}
- **年线偏离度**: {data['bias']}%

---
### 💡 投资建议
{advice}
    """
    
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": markdown_content.strip()
        }
    }
    
    resp = requests.post(WEBHOOK_URL, json=payload)
    print("消息发送结果:", resp.text)

if __name__ == "__main__":
    try:
        market_data = get_market_data()
        advice_text, _ = get_strategy(market_data)
        send_wechat_notification(market_data, advice_text)
    except Exception as e:
        print(f"运行出错: {e}")
        # 也可以加一个错误通知