import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import plotly.express as px
import json
import os
import datetime
import io

# --- 1. ページ基本設定 ---
st.set_page_config(page_title="M-POG Archives", layout="wide")

# ==========================================
# 2. 外部設定ファイルの読み込み
# ==========================================
CONFIG_FILE = "draft_configs.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

ARCHIVE_CONFIG = load_config()
if not ARCHIVE_CONFIG:
    st.error("設定ファイル draft_configs.json が見つかりません。")
    st.stop()

seasons = sorted(list(ARCHIVE_CONFIG.keys()), reverse=True)
selected_season = st.sidebar.selectbox("表示するシーズンを選択", seasons, index=0)

conf = ARCHIVE_CONFIG[selected_season]
SEASON_START = str(conf["start_date"])
SEASON_END = str(conf["end_date"])
TEAM_CONFIG = conf["teams"]
PLAYER_TO_OWNER = {p: owner for owner, c in TEAM_CONFIG.items() for p in c['players']}

# --- スタイル設定 ---
st.markdown("""
<style>
    .pog-table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
    .pog-table th { background-color: #444; color: white !important; padding: 10px; border: 1px solid #333; }
    .pog-table td { border: 1px solid #ddd; padding: 10px; text-align: center; color: #000000 !important; font-weight: bold; }
    .section-label { font-weight: bold; margin: 20px 0 10px 0; font-size: 1.2rem; border-left: 6px solid #444; padding-left: 10px; color: #333; }
</style>
""", unsafe_allow_html=True)

st.title(f"🀄 M-POG {selected_season}")

# ==========================================
# 3. データ処理ロジック
# ==========================================

def load_history_from_csv(file_path):
    if not os.path.exists(file_path): return pd.DataFrame()
    try:
        raw_df = pd.read_csv(file_path, header=None, encoding='cp932')
    except:
        raw_df = pd.read_csv(file_path, header=None, encoding='utf-8')
    
    dates_row = raw_df.iloc[0].tolist()
    match_nums = raw_df.iloc[1].tolist()
    history = []
    
    for i in range(2, len(raw_df)):
        player_name = str(raw_df.iloc[i, 0]).strip()
        if not player_name or player_name == "nan" or player_name not in PLAYER_TO_OWNER:
            continue
        for col in range(1, len(raw_df.columns)):
            val = raw_df.iloc[i, col]
            if pd.isna(val) or str(val).strip() == "": continue
            try:
                score = float(str(val).replace(' ', ''))
                d_val = dates_row[col]
                if pd.isna(d_val) or str(d_val).strip() in ["", "nan"]:
                    for back in range(col, 0, -1):
                        if not pd.isna(dates_row[back]) and str(dates_row[back]).strip() not in ["", "nan"]:
                            d_val = dates_row[back]
                            break
                dt = pd.to_datetime(d_val)
                date_str = dt.strftime('%Y%m%d')
                m_num = int(float(match_nums[col]))
                history.append({
                    "date": date_str, "m_label": f"第{m_num}試合", "match_uid": f"{date_str}_{m_num}",
                    "player": player_name, "point": score, "owner": PLAYER_TO_OWNER[player_name]
                })
            except: continue
    return pd.DataFrame(history)

@st.cache_data(ttl=1800)
def get_web_history(season_start, season_end):
    url = "https://m-league.jp/games/"
    headers = {"User-Agent": "Mozilla/5.0"}
    history = []
    try:
        res = requests.get(url, headers=headers)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, 'html.parser')
        date_match_counter = {}

        for container in soup.find_all(class_="c-modal2"):
            date_match = re.search(r'(\d{8})', container.get('id', ''))
            if not date_match: continue
            date_str = date_match.group(1)
            if not (season_start <= date_str <= season_end): continue
            
            if date_str not in date_match_counter:
                date_match_counter[date_str] = 0

            columns = container.find_all(class_="p-gamesResult__column")
            for col in columns:
                date_match_counter[date_str] += 1
                current_match_num = date_match_counter[date_str]
                items = col.find_all(class_="p-gamesResult__rank-item")
                for item in items:
                    name_el = item.find(class_="p-gamesResult__name")
                    point_el = item.find(class_="p-gamesResult__point")
                    if name_el and point_el:
                        name = name_el.get_text(strip=True)
                        p_raw = point_el.get_text(strip=True).replace('▲', '-').replace('pts', '').replace(' ', '')
                        p_val = "".join(re.findall(r'[0-9.\-]', p_raw))
                        if name in PLAYER_TO_OWNER and p_val:
                            history.append({
                                "date": date_str, 
                                "m_label": f"第{current_match_num}試合", 
                                "match_uid": f"{date_str}_{current_match_num}",
                                "player": name, 
                                "point": float(p_val), 
                                "owner": PLAYER_TO_OWNER[name]
                            })
        return pd.DataFrame(history)
    except Exception as e:
        st.error(f"Webデータ取得中にエラーが発生しました: {e}")
        return pd.DataFrame()

# --- 実行 ---
csv_file = f"history_{selected_season}.csv"
if os.path.exists(csv_file):
    df_history = load_history_from_csv(csv_file)
    data_source = "csv"
else:
    df_history = get_web_history(SEASON_START, SEASON_END)
    data_source = "web"

# ==========================================
# 4. 表示
# ==========================================
if df_history.empty:
    st.warning(f"{selected_season} のデータが見つかりません。")
else:
    total_pts = df_history.groupby('player')['point'].sum()
    pog_summary, player_all = [], []
    for owner, cfg in TEAM_CONFIG.items():
        score = sum([total_pts.get(p, 0) for p in cfg['players']])
        pog_summary.append({"オーナー": owner, "合計": round(score, 1)})
        for p in cfg['players']:
            player_all.append({"選手": p, "オーナー": owner, "ポイント": round(total_pts.get(p, 0), 1)})
    
    df_teams = pd.DataFrame(pog_summary).sort_values("合計", ascending=False)
    df_players = pd.DataFrame(player_all).sort_values("ポイント", ascending=False)

    col1, col2 = st.columns([1, 1.2])
    with col1:
        st.markdown('<div class="section-label">🏆 総合順位</div>', unsafe_allow_html=True)
        html = '<table class="pog-table"><tr><th>順位</th><th>オーナー</th><th>合計</th></tr>'
        for i, row in enumerate(df_teams.itertuples(), 1):
            bg = TEAM_CONFIG[row.オーナー]['bg_color']
            html += f'<tr style="background-color:{bg}"><td>{i}</td><td>{row.オーナー}</td><td>{row.合計:+.1f}</td></tr>'
        st.markdown(html + '</table>', unsafe_allow_html=True)

    with col2:
        latest_date = df_history['date'].max()
        st.markdown(f'<div class="section-label">🀄 最新結果 ({latest_date[4:6]}/{latest_date[6:]})</div>', unsafe_allow_html=True)
        df_latest = df_history[df_history['date'] == latest_date]
        uids = sorted(df_latest['match_uid'].unique(), key=lambda x: (x.split('_')[0], int(x.split('_')[1])))
        for m_uid in uids:
            df_m = df_latest[df_latest['match_uid'] == m_uid].sort_values("point", ascending=False)
            if not df_m.empty:
                st.write(f"**{df_m['m_label'].iloc[0]}**")
                html = '<table class="pog-table"><tr><th>選手</th><th>オーナー</th><th>ポイント</th></tr>'
                for row in df_m.itertuples():
                    bg = TEAM_CONFIG[row.owner]['bg_color']
                    html += f'<tr style="background-color:{bg}"><td>{row.player}</td><td>{row.owner}</td><td>{row.point:+.1f}</td></tr>'
                st.markdown(html + '</table>', unsafe_allow_html=True)

    st.write("---")
    
    # --- ポイント推移グラフの修正 ---
    st.markdown('<div class="section-label">📈 ポイント推移グラフ</div>', unsafe_allow_html=True)
    
    # 1. 試合単位(match_uid)でオーナーごとの合計ポイントを算出
    match_owner_pts = df_history.groupby(['match_uid', 'owner'])['point'].sum().unstack().fillna(0)
    
    # 2. match_uidを日付と試合番号で正しく並び替える
    sorted_uids = sorted(match_owner_pts.index, key=lambda x: (x.split('_')[0], int(x.split('_')[1])))
    match_owner_pts = match_owner_pts.reindex(sorted_uids)
    
    # 3. 累積和(cumsum)を計算
    daily_cum = match_owner_pts.cumsum().reset_index()
    
    # 4. X軸用のラベルを作成（例: 12/30-1, 12/30-2）
    def format_label(uid):
        d, m = uid.split('_')
        return f"{d[4:6]}/{d[6:]}-{m}"
    
    daily_cum['display_label'] = daily_cum['match_uid'].apply(format_label)
    
    # 5. プロット用にデータ整形
    df_plot = daily_cum.melt(id_vars=['match_uid', 'display_label'], var_name='オーナー', value_name='累計pt')
    
    fig_line = px.line(df_plot, x='display_label', y='累計pt', color='オーナー', 
                       color_discrete_map={k: v['color'] for k, v in TEAM_CONFIG.items()}, 
                       markers=True,
                       category_orders={"display_label": daily_cum['display_label'].tolist()}) # 並び順を強制
    
    fig_line.update_layout(xaxis_title="試合 (月/日-試合番号)", yaxis_title="累計ポイント")
    st.plotly_chart(fig_line, use_container_width=True)

    st.markdown('<div class="section-label">👤 個人ランキング</div>', unsafe_allow_html=True)
    html = '<table class="pog-table"><tr><th>Rank</th><th>選手</th><th>オーナー</th><th>ポイント</th></tr>'
    for i, row in enumerate(df_players.itertuples(), 1):
        bg = TEAM_CONFIG[row.オーナー]['bg_color']
        html += f'<tr style="background-color:{bg}"><td>{i}</td><td>{row.選手}</td><td>{row.オーナー}</td><td>{row.ポイント:+.1f}</td></tr>'
    st.markdown(html + '</table>', unsafe_allow_html=True)

# ==========================================
# 5. 管理機能 (サイドバー)
# ==========================================
with st.sidebar:
    st.subheader("⚙️ データ管理")
    if st.button('🔄 最新データに更新'):
        st.cache_data.clear()
        st.rerun()

    if data_source == "csv":
        st.success(f"✅ {selected_season} の保存済みデータ(CSV)を表示中")
    elif not df_history.empty:
        st.warning(f"🌐 公式サイトの最新データを表示中")
        
        pivot_df = df_history.pivot(index='player', columns=['date', 'm_label'], values='point')
        sorted_cols = sorted(pivot_df.columns, key=lambda x: (x[0], int(x[1].replace('第','').replace('試合',''))))
        pivot_df = pivot_df[sorted_cols]
        
        h1 = [""] + [pd.to_datetime(c[0]).strftime('%Y/%m/%d') for c in sorted_cols]
        h2 = [""] + [c[1].replace("第", "").replace("試合", "") for c in sorted_cols]
        
        all_players = sorted(list(PLAYER_TO_OWNER.keys()))
        rows = [h1, h2]
        for p in all_players:
            row = [p]
            for col in sorted_cols:
                val = pivot_df.loc[p, col] if p in pivot_df.index else ""
                row.append(val)
            rows.append(row)
        
        output_df = pd.DataFrame(rows)
        csv_buffer = io.BytesIO()
        output_df.to_csv(csv_buffer, index=False, header=False, encoding='cp932')
        
        st.download_button(
            label="💾 現在の結果をCSVで保存",
            data=csv_buffer.getvalue(),
            file_name=csv_file,
            mime="text/csv",
        )
