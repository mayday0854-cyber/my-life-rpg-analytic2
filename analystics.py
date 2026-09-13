import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from notion_client import Client
import requests  
NOTION_TOKEN = "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"
DATABASE_ID = "3dacb4ee98008001b171e36b829303b7"

notion = Client(auth=NOTION_TOKEN)

# --- 2. Notionからデータ取得する関数 ---
@st.cache_data(ttl=60)
def fetch_notion_data():
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",  # 最新の安定版APIバージョン
        "Content-Type": "application/json"
    }
    
    results = []
    has_more = True
    next_cursor = None
    
    while has_more:
        payload = {}
        if next_cursor:
            payload["start_cursor"] = next_cursor
            
        response = requests.post(url, json=payload, headers=headers)
        
        # エラーが起きたら詳細を表示
        if response.status_code != 200:
            raise Exception(f"Notion API Error: {response.status_code} - {response.text}")
            
        data = response.json()
        results.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor", None)
        
    rows = []
    for page in results:
        props = page.get("properties", {})
        
        # データの安全な抽出（空欄・エラー対策）
        date_obj = props.get("日付", {}).get("date")
        date = date_obj.get("start") if date_obj else None
        
        select_obj = props.get("カテゴリ", {}).get("select")
        category = select_obj.get("name") if select_obj else "その他"
        
        amount = props.get("量", {}).get("number", 0)
        if amount is None:  # 量が空欄の場合の対策
            amount = 0
        
        if date:
            rows.append({"日付": date, "カテゴリ": category, "量": amount})
            
    if not rows:
        raise Exception("Notionから有効なデータが1件も取得できませんでした。日付プロパティなどが入っているか確認してください。")
        
    df = pd.DataFrame(rows)
    df["日付"] = pd.to_datetime(df["日付"])
    return df

# --- 画面構築 ---
st.set_page_config(page_title="リアル人生RPGアナリティクス", layout="wide")
st.title("⚔️ リアル人生RPG ダッシュボード")

try:
    df_raw = fetch_notion_data()
    
    # 1. データを「日付 × カテゴリ」の形にピボット
    df_pivot = df_raw.pivot_table(
        index="日付", 
        columns="カテゴリ", 
        values="量", 
        aggfunc="sum"
    ).fillna(0)
    
    # 日付の抜け漏れ（ログを付けなかった日）を補完するために日付軸を綺麗に整形
    all_days = pd.date_range(start=df_pivot.index.min(), end=df_pivot.index.max(), freq='D')
    df_pivot = df_pivot.reindex(all_days, fill_value=0).sort_index()

    # 2. 【アップデート】傾斜配分による基本XPの計算（「ゲーム」を追加）
    # ※ Notionのセレクトボックスの文字列と完全に一致させてください
    weights = {
        "読書": 1.0,
        "筋トレ": 1.5,
        "勉強": 2.0,
        "仕事": 0.5,
        "ゲーム": 0.1  # ご要望の倍率0.1を追加
    }
    
    df_pivot["基本XP"] = 0.0
    for category, weight in weights.items():
        if category in df_pivot.columns:
            df_pivot["基本XP"] += df_pivot[category] * weight

    # 3. 継続日数（ストリーク）と1%複利バフの計算
    streak_counts = []
    multipliers = []
    
    current_streak = 0
    current_multiplier = 1.0
    
    for base_xp in df_pivot["基本XP"]:
        if base_xp > 0:
            current_streak += 1
            current_multiplier = current_multiplier * 1.01
        else:
            current_streak = 0
            current_multiplier = 1.0
            
        streak_counts.append(current_streak)
        multipliers.append(current_multiplier)
        
    df_pivot["継続日数"] = streak_counts
    df_pivot["経験値倍率"] = multipliers

    # 4. 最終獲得XPと【アップデート】総経験値（累計XP）の計算
    df_pivot["最終獲得XP"] = df_pivot["基本XP"] * df_pivot["経験値倍率"]
    df_pivot["総経験値"] = df_pivot["最終獲得XP"].cumsum()

    # --- UI表示（ステータス画面風） ---
    latest = df_pivot.iloc[-1]
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(label="現在の継続ストリーク", value=f"{int(latest['継続日数'])} 日連続")
    with col2:
        st.metric(label="現在の経験値バフ倍率", value=f"x{latest['経験値倍率']:.2f}", delta=f"+{((latest['経験値倍率']-1)*100):.1f}%")
    with col3:
        # 総経験値を最上部に目立つように表示
        st.metric(label="現在の総経験値 (Total XP)", value=f"{int(latest['総経験値'])} XP")

    # --- グラフ描画（2つのタブで切り替え可能に） ---
    tab1, tab2 = st.tabs(["📊 日別の獲得XPと倍率", "👑 総経験値（累計）の可視化"])
    
    with tab1:
        # 日別の獲得XP（棒）と倍率（線）の複合グラフ
        fig1 = go.Figure()
        fig1.add_trace(go.Bar(x=df_pivot.index, y=df_pivot["最終獲得XP"], name="その日の獲得XP", marker_color="royalblue"))
        fig1.add_trace(go.Scatter(x=df_pivot.index, y=df_pivot["経験値倍率"], name="バフ倍率 (右軸)", yaxis="y2", line=dict(color="orange", width=3)))
        fig1.update_layout(
            title="日別の獲得XPとバフ倍率の推移",
            yaxis=dict(title="獲得XP"),
            yaxis2=dict(title="倍率", overlaying="y", side="right"),
            legend=dict(x=0.01, y=0.99)
        )
        st.plotly_chart(fig1, use_container_width=True)

    with tab2:
        # 【新機能】総経験値の可視化（右肩上がりの成長が見えるエリアチャート）
        fig2 = px.area(
            df_pivot.reset_index(), 
            x="index", 
            y="総経験値", 
            title="総経験値（累計XP）の成長曲線",
            labels={"index": "日付", "総経験値": "総経験値 (XP)"},
            color_discrete_sequence=["#2ca02c"] # 成長をイメージするグリーン
        )
        fig2.update_traces(line=dict(width=2), fillcolor="rgba(44, 160, 44, 0.2)") # 塗りつぶしを透明に
        st.plotly_chart(fig2, use_container_width=True)

    # データの確認用
    st.subheader("📋 ログ履歴（直近10日分）")
    # 表示する項目にゲームが追加されているか確認できるよう、存在する列だけ動的に表示
    display_cols = [c for c in weights.keys() if c in df_pivot.columns] + ["最終獲得XP", "総経験値"]
    st.dataframe(df_pivot[display_cols].tail(10))

except Exception as e:
    st.error(f"エラーが発生しました: {e}")