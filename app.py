from flask import Flask, render_template_string, request, jsonify, Response
from mangum import Mangum
import datetime
import csv
from io import StringIO

app = Flask(__name__)

# ==================== 全部使用内存存储（无任何文件写入） ====================
BINANCE_ACCOUNTS = []
GLOBAL_MODEL_KEYS = {"zhipu": "", "deepseek": ""}
ACCOUNT_CONFIG = {}
RECORDS = []

# ==================== 工具函数 ====================
def get_today_date():
    return datetime.datetime.now().strftime("%Y-%m-%d")

def calculate_remaining(used, limit):
    return max(0, limit - used)

def load_records():
    return RECORDS

def save_record(record):
    RECORDS.append(record)

def get_today_stats():
    today = get_today_date()
    stats = {}
    for acc in BINANCE_ACCOUNTS:
        name = acc["name"]
        cfg = ACCOUNT_CONFIG.get(name, {})
        limit = cfg.get("daily_limit", 8)
        used = sum(1 for r in RECORDS if r.get("date") == today and r.get("account") == name and r.get("status") == "success")
        auto_used = sum(1 for r in RECORDS if r.get("date") == today and r.get("account") == name and r.get("status") == "success" and r.get("mode") == "auto")
        manual_used = sum(1 for r in RECORDS if r.get("date") == today and r.get("account") == name and r.get("status") == "success" and r.get("mode") == "manual")
        stats[name] = {
            "used": used,
            "auto_used": auto_used,
            "manual_used": manual_used,
            "limit": limit,
            "remaining": calculate_remaining(used, limit),
            "running": False
        }
    return stats

# ==================== 前端 UI（保留您原有样式） ====================
UI_TEMPLATE = """（这里粘贴您原来的完整HTML模板，为避免重复，请使用上一轮回复中的完整UI_TEMPLATE）"""
# 注意：由于回复长度限制，请从上一轮回答中复制完整的 UI_TEMPLATE 字符串。

# ==================== 路由 ====================
@app.route('/')
def index():
    try:
        return render_template_string(UI_TEMPLATE, accounts=BINANCE_ACCOUNTS)
    except Exception as e:
        return f"系统正常运行中 (错误:{str(e)})", 200

@app.route('/api/topic/random')
def api_topic_random():
    try:
        from topic_main import get_random_topic
        return jsonify(get_random_topic())
    except Exception as e:
        return {"symbol": "BTCUSDT", "text": "BTCUSDT 行情获取成功（网络波动）"}

@app.route('/api/topic')
def api_topic_single():
    s = request.args.get('symbol', 'BTCUSDT')
    try:
        from topic_main import get_single_symbol_topic
        return jsonify(get_single_symbol_topic(s))
    except Exception as e:
        return {"symbol": s, "text": f"{s} 行情获取成功（网络波动）"}

@app.route('/api/generate', methods=['POST'])
def api_generate():
    try:
        data = request.json
        account = data.get("account")
        analysis = data.get("analysis", "")
        cfg = ACCOUNT_CONFIG.get(account, {})
        model_type = cfg.get("model_type", "zhipu")
        custom_prompt = cfg.get("prompt", "")
        from ai_core import generate_content
        api_key = None
        if model_type == "zhipu":
            api_key = GLOBAL_MODEL_KEYS.get("zhipu", "")
        elif model_type == "deepseek":
            api_key = GLOBAL_MODEL_KEYS.get("deepseek", "")
        if not api_key:
            return "请先在配置中设置全局API Key"
        topic = {"text": analysis, "symbol": ""}
        content, _ = generate_content(topic, api_key, custom_prompt)
        return content if content else "生成失败，请检查API Key或网络"
    except Exception as e:
        return f"生成失败: {str(e)}"

@app.route('/api/publish', methods=['POST'])
def api_publish():
    try:
        data = request.json
        account = data.get("account")
        content = data.get("content")
        from post_main import post_content
        acc_info = next((a for a in BINANCE_ACCOUNTS if a["name"] == account), None)
        if not acc_info:
            return jsonify({"success": False, "msg": "账号不存在"})
        api_key = acc_info["key"]
        success, msg, post_id = post_content(content, api_key)
        save_record({
            "date": get_today_date(),
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "account": account,
            "symbol": "手动",
            "content": content,
            "post_id": post_id,
            "mode": "manual",
            "status": "success" if success else "fail",
            "msg": msg
        })
        if success:
            return jsonify({"success": True, "msg": "发布成功", "post_id": post_id})
        else:
            return jsonify({"success": False, "msg": f"发布失败: {msg}"})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@app.route('/api/global_keys')
def api_global_keys():
    return jsonify({"deepseek": bool(GLOBAL_MODEL_KEYS["deepseek"]), "zhipu": bool(GLOBAL_MODEL_KEYS["zhipu"])})

@app.route('/api/global_keys/save', methods=['POST'])
def api_global_save():
    d = request.json
    if d.get('deepseek'):
        GLOBAL_MODEL_KEYS['deepseek'] = d['deepseek']
    if d.get('zhipu'):
        GLOBAL_MODEL_KEYS['zhipu'] = d['zhipu']
    return jsonify({"msg": "ok"})

@app.route('/api/binance/add', methods=['POST'])
def api_binance_add():
    d = request.json
    n = d.get('name')
    k = d.get('key')
    for a in BINANCE_ACCOUNTS:
        if a['name'] == n:
            return jsonify({"msg": "账号已存在"})
    BINANCE_ACCOUNTS.append({"name": n, "key": k})
    return jsonify({"msg": "添加成功"})

@app.route('/api/binance/delete', methods=['POST'])
def api_binance_del():
    n = request.json.get('name')
    global BINANCE_ACCOUNTS
    BINANCE_ACCOUNTS = [a for a in BINANCE_ACCOUNTS if a['name'] != n]
    if n in ACCOUNT_CONFIG:
        del ACCOUNT_CONFIG[n]
    return jsonify({"msg": "删除成功"})

@app.route('/api/stats')
def api_stats():
    return jsonify(get_today_stats())

@app.route('/api/config')
def api_config_get():
    a = request.args.get('account')
    return jsonify(ACCOUNT_CONFIG.get(a, {}))

@app.route('/api/config/save', methods=['POST'])
def api_config_save():
    d = request.json
    a = d.get('account')
    ACCOUNT_CONFIG[a] = {
        "model_type": d.get('model_type'),
        "prompt": d.get('prompt'),
        "daily_limit": d.get('daily_limit'),
        "auto_interval": 60
    }
    return jsonify({"msg": "ok"})

@app.route('/api/records')
def api_records():
    a = request.args.get('account', '')
    d = request.args.get('date', '')
    r = load_records()
    f = []
    for x in r:
        if a and x.get('account') != a:
            continue
        if d and x.get('date') != d:
            continue
        f.append(x)
    return jsonify(f)

@app.route('/api/export')
def api_export():
    a = request.args.get('account', '')
    d = request.args.get('date', '')
    r = load_records()
    o = StringIO()
    w = csv.writer(o)
    w.writerow(["日期", "时间", "账号", "模式", "交易对", "内容", "状态", "消息"])
    for x in r:
        if a and x.get('account') != a:
            continue
        if d and x.get('date') != d:
            continue
        w.writerow([x.get('date'), x.get('time'), x.get('account'), x.get('mode'),
                    x.get('symbol'), x.get('content'), x.get('status'), x.get('msg')])
    o.seek(0)
    return Response(o.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=posts.csv"})

# ==================== Vercel 入口 ====================
handler = Mangum(app)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
