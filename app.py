"""
カムカムラボ 無形コンテンツ診断 - LINE連携バックエンド
- /callback  : LINE Webhook（友達追加・メッセージ受信）
- /send_result : 診断ツールからの結果送信エンドポイント
- /line_login_callback : LINEログインのコールバック
"""

import os
import json
import hashlib
import hmac
import base64
import requests
from flask import Flask, request, jsonify, redirect

app = Flask(__name__)

# ============================================================
# 設定（環境変数 or 直接記述）
# ============================================================
MESSAGING_CHANNEL_SECRET = os.environ.get("MESSAGING_CHANNEL_SECRET", "6b945dc28d92f7b4afcb08d7037f744e")
MESSAGING_CHANNEL_ACCESS_TOKEN = os.environ.get("MESSAGING_CHANNEL_ACCESS_TOKEN", "")  # 長期トークンを設定

LOGIN_CHANNEL_ID = os.environ.get("LOGIN_CHANNEL_ID", "2009922414")
LOGIN_CHANNEL_SECRET = os.environ.get("LOGIN_CHANNEL_SECRET", "2a3ce216064d1ed4e435d92ba3e070f9")

# 診断完了後のリダイレクト先（診断ツールのURL）
DIAGNOSIS_TOOL_URL = os.environ.get("DIAGNOSIS_TOOL_URL", "https://sub.cocostyle-school.com/p/W04amWAhgx7Q")

# LINEログインのコールバックURL（本番デプロイ後に設定）
LOGIN_REDIRECT_URI = os.environ.get("LOGIN_REDIRECT_URI", "https://camcamlab-line-backend.onrender.com/line_login_callback")

# ============================================================
# 診断タイプの定義
# ============================================================
RESULT_TYPES = {
    "A": {
        "name": "深掘り伴走タイプ",
        "desc": "あなたは人の話を深く聴き、一緒に考えることが得意なタイプです。お客さんの内側にある答えを引き出す力があります。マンツーマンで寄り添うスタイルが最も力を発揮できます。",
        "services": ["個別コーチング・セッション", "マンツーマン伴走プログラム", "深掘りワークショップ", "個別コンサルティング"]
    },
    "B": {
        "name": "知識発信タイプ",
        "desc": "あなたは知識・経験を体系化して伝えることが得意なタイプです。自分の学びやノウハウをわかりやすくまとめ、多くの人に届けることができます。教材・講座系のコンテンツが向いています。",
        "services": ["動画講座・オンライン講座", "note・電子書籍・PDF教材", "テキストコンテンツ販売", "メルマガ・ブログ発信"]
    },
    "C": {
        "name": "コミュニティ構築タイプ",
        "desc": "あなたは人が集まる場を作り、仲間と共に育つ環境を作ることが得意なタイプです。コミュニティ全体を盛り上げる力があります。",
        "services": ["オンラインサロン・ラボ形式", "グループコンサルティング", "コミュニティ型プログラム", "月額継続型サービス"]
    },
    "D": {
        "name": "ハイブリッドタイプ",
        "desc": "教えることも寄り添うことも両方できる、バランスの取れたタイプです。講座で知識を届けながら、個別サポートで深く関わることで、お客さんに最大の変化をもたらすことができます。",
        "services": ["講座＋個別サポートのセット", "連続プログラム（複数回講座）", "グループ講座＋個別セッション", "ハイブリッド型スクール"]
    },
    "E": {
        "name": "手離れ教材タイプ",
        "desc": "仕組み化・自動化を大切にし、作ったコンテンツを多くの人に届けたいタイプです。一度作れば繰り返し届けられる教材・コンテンツが最も向いています。",
        "services": ["note・PDF教材販売", "録画動画コンテンツ販売", "メルマガ講座（ステップメール）", "デジタルコンテンツ販売"]
    },
    "F": {
        "name": "リアル×オンライン融合タイプ",
        "desc": "対面の熱量とオンラインの広がりを両立したいタイプです。リアルな場での体験とオンラインの利便性を組み合わせることで、唯一無二のサービスを作ることができます。",
        "services": ["ハイブリッド講座（オンライン＋リアル）", "リトリート＋ZOOMフォローアップ", "リアルイベント＋オンラインコミュニティ", "合宿型プログラム"]
    }
}

# ============================================================
# LINE Messaging API ヘルパー
# ============================================================
def send_line_message(user_id: str, messages: list) -> bool:
    """LINE Messaging APIでメッセージを送信する"""
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {MESSAGING_CHANNEL_ACCESS_TOKEN}"
    }
    payload = {
        "to": user_id,
        "messages": messages
    }
    resp = requests.post(url, headers=headers, json=payload)
    return resp.status_code == 200


def build_result_messages(name: str, result_type: str) -> list:
    """診断結果のLINEメッセージを組み立てる"""
    r = RESULT_TYPES.get(result_type, RESULT_TYPES["D"])
    services_text = "\n".join([f"・{s}" for s in r["services"]])

    text1 = (
        f"{name}さん、診断が完了しました！\n\n"
        f"【あなたの診断結果】\n"
        f"✦ {r['name']}\n\n"
        f"{r['desc']}"
    )

    text2 = (
        f"【おすすめのサービス形態】\n"
        f"{services_text}\n\n"
        f"カムカムラボでは、あなたに合ったコンテンツ・サービスの作り方を個別にサポートしています。\n"
        f"気になることがあれば、このLINEからいつでもご相談ください。"
    )

    return [
        {"type": "text", "text": text1},
        {"type": "text", "text": text2}
    ]


# ============================================================
# LINEログイン
# ============================================================
@app.route("/line_login")
def line_login():
    """LINEログインページへリダイレクト"""
    # state（CSRF対策）はシンプルに固定値（本番はランダム生成推奨）
    state = request.args.get("state", "camcamlab_diagnosis")
    params = {
        "response_type": "code",
        "client_id": LOGIN_CHANNEL_ID,
        "redirect_uri": LOGIN_REDIRECT_URI,
        "state": state,
        "scope": "profile openid",
        "nonce": "camcamlab_nonce"
    }
    query = "&".join([f"{k}={v}" for k, v in params.items()])
    return redirect(f"https://access.line.me/oauth2/v2.1/authorize?{query}")


@app.route("/line_login_callback")
def line_login_callback():
    """LINEログインのコールバック処理"""
    code = request.args.get("code")
    state = request.args.get("state", "")

    if not code:
        return "ログインに失敗しました。", 400

    # アクセストークン取得
    token_resp = requests.post(
        "https://api.line.me/oauth2/v2.1/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": LOGIN_REDIRECT_URI,
            "client_id": LOGIN_CHANNEL_ID,
            "client_secret": LOGIN_CHANNEL_SECRET,
        }
    )
    if token_resp.status_code != 200:
        return "トークン取得に失敗しました。", 400

    token_data = token_resp.json()
    access_token = token_data.get("access_token")

    # プロフィール取得（userId）
    profile_resp = requests.get(
        "https://api.line.me/v2/profile",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    if profile_resp.status_code != 200:
        return "プロフィール取得に失敗しました。", 400

    profile = profile_resp.json()
    user_id = profile.get("userId")
    display_name = profile.get("displayName", "")

    # stateに診断結果タイプを埋め込んでいる場合はそこから取得
    # 例: state = "camcamlab_diagnosis_A_田中さん"
    result_type = "D"
    name = display_name
    if state.startswith("camcamlab_"):
        parts = state.split("_")
        if len(parts) >= 3:
            result_type = parts[2]
        if len(parts) >= 4:
            name = parts[3]

    # LINE Messaging APIで診断結果を送信
    messages = build_result_messages(name, result_type)
    send_line_message(user_id, messages)

    # 診断ツールに戻す（結果表示済みのページ）
    return redirect(f"{DIAGNOSIS_TOOL_URL}?result_sent=1")


# ============================================================
# 診断結果送信エンドポイント（フォールバック用）
# ============================================================
@app.route("/send_result", methods=["POST", "OPTIONS"])
def send_result():
    """診断ツールから直接呼ばれるエンドポイント（userId既知の場合）"""
    if request.method == "OPTIONS":
        resp = jsonify({"status": "ok"})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        return resp

    data = request.get_json(force=True)
    user_id = data.get("userId")
    name = data.get("name", "あなた")
    result_type = data.get("resultType", "D")

    if not user_id:
        resp = jsonify({"status": "error", "message": "userId is required"})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp, 400

    messages = build_result_messages(name, result_type)
    success = send_line_message(user_id, messages)

    resp = jsonify({"status": "ok" if success else "error"})
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


# ============================================================
# LINE Webhook（友達追加時のウェルカムメッセージ）
# ============================================================
def verify_signature(body: bytes, signature: str) -> bool:
    hash_val = hmac.new(
        MESSAGING_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256
    ).digest()
    expected = base64.b64encode(hash_val).decode("utf-8")
    return hmac.compare_digest(expected, signature)


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data()

    if not verify_signature(body, signature):
        return "Invalid signature", 400

    events = request.get_json().get("events", [])
    for event in events:
        if event.get("type") == "follow":
            user_id = event["source"]["userId"]
            send_line_message(user_id, [{
                "type": "text",
                "text": (
                    "カムカムラボ公式LINEへようこそ！\n\n"
                    "友達追加ありがとうございます。\n"
                    "無形コンテンツ診断を受けると、あなたに合ったサービス形態の結果がこちらに届きます。\n\n"
                    "何かご質問があれば、いつでもメッセージをどうぞ。"
                )
            }])

    return "OK", 200


# ============================================================
# ヘルスチェック
# ============================================================
@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "camcamlab-line-backend"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
