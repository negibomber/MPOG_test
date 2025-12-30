import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import plotly.express as px
import json
import os
import datetime

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

# 年度リストを新しい順に並べる
seasons = sorted(list(ARCHIVE_CONFIG.keys()), reverse=True)
selected_season = st.sidebar.selectbox("表示するシーズンを選択", seasons, index=0)

# 選択された年度の設定
conf = ARCHIVE_CONFIG[selected_season]
SEASON_START = str(conf["start_date"])
SEASON_END = str(conf["end_date"])
TEAM_CONFIG = conf["teams"]
PLAYER_TO_OWNER = {p: owner for owner, c in TEAM_CONFIG.items() for p in c['players']}

# 今日の日付
today_str = datetime.datetime.now().strftime('%Y%m%d')

# --- スタイル設定 (CSS) ---
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
        
        # 同じ日付の試合をカウントするための辞書
        date_match_counter = {}

        # モーダル（c-modal2）を順に取得
        # HTMLの並び順通り（通常は古い順または特定の順序）に処理される
        for container in soup.find_all(class_="c-modal2"):
            date_match = re.search(r'(\d{8})', container.get('id', ''))
            if not date_match: continue
            date_str = date_match.group(1)
            
            # シーズン期間外ならスキップ
            if not (season_start <= date_str <= season_end): continue
            
            # 日付ごとの試合数カウンターを初期化
            if date_str not in date_match_counter:
                date_match_counter[date_str] = 0

            # 回戦ブロック(p-gamesResult__column)を取得
            columns = container.find_all(class_="p-gamesResult__column")
            for col in columns:
                # この日付の通し番号をカウントアップ
                date_match_counter[date_str] += 1
                current_match_num = date_match_counter[date_str]
                
                # ブロック内の選手アイテムを取得
                items = col.find_all(class_="p-gamesResult__rank-item")
                for item in items:
                    name_el = item.find(class_="p-gamesResult__name")
                    point_el = item.find(class_="p-gamesResult__point")
                    
                    if name_el and point_el:
                        name = name_el.get_text(strip=True)
                        p_raw = point_el.get_text(strip=True).replace('▲', '-').replace('pts', '').replace(' ', '')
                        p_val = "".join(re.findall(r'[0-9.\-]', p_raw))
                        
                        # POG登録選手かつ数値が取れている場合のみ保存
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

# --- データの取得実行 ---
csv_file = f"history_{selected_season}.csv"
if os.path.exists(csv_file):
    df_history = load_history_from_csv(csv_file)
    data_source = "csv"
else:
    df_history = get_web_history(SEASON_START, SEASON_END)
    data_source = "web"

# ==========================================
# 4. メイン画面表示
# ==========================================
if df_history.empty:
    st.warning(f"{selected_season} のデータが見つかりません。")
else:
    # ポイント集計
    total_pts = df_history.groupby('player')['point'].sum()
    pog_summary, player_all = [], []
    for owner, cfg in TEAM_CONFIG.items():
        score = sum([total_pts.get(p, 0) for p in cfg['players']])
        pog_summary.append({"オーナー": owner, "合計": round(score, 1)})
        for p in cfg['players']:
            player_all.append({"選手": p, "オーナー": owner, "ポイント": round(total_pts.get(p, 0), 1)})
    
    df_teams = pd.DataFrame(pog_summary).sort_values("合計", ascending=False)
    df_players = pd.DataFrame(player_all).sort_values("ポイント", ascending=False)

    # 総合順位と最新結果
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
        
        # 試合UID（日付_連番）でソートして、試合ごとにテーブルを表示
        uids = sorted(df_latest['match_uid'].unique(), key=lambda x: int(x.split('_')[1]))
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
    
    # 累計グラフ
    st.markdown('<div class="section-label">📈 ポイント推移グラフ</div>', unsafe_allow_html=True)
    # グラフ用データ作成（日付と試合番号を考慮してソート）
    df_history_sorted = df_history.sort_values(['date', 'match_uid'])
    daily = df_history_sorted.groupby(['date', 'match_uid', 'owner'])['point'].sum().unstack().fillna(0).cumsum().reset_index()
    daily['date_label'] = daily['date'].str[4:6] + "/" + daily['date'].str[6:]
    
    df_plot = daily.melt(id_vars=['date', 'match_uid', 'date_label'], var_name='オーナー', value_name='累計pt')
    fig_line = px.line(df_plot, x='date_label', y='累計pt', color='オーナー', 
                       color_discrete_map={k: v['color'] for k, v in TEAM_CONFIG.items()}, markers=True)
    st.plotly_chart(fig_line, use_container_width=True)

    # 個人ランキング
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
        
        # 保存用CSVの生成
        pivot_df = df_history.pivot(index='player', columns=['date', 'm_label'], values='point')
        # 列名を(date, match_num)でソート
        sorted_cols = sorted(pivot_df.columns, key=lambda x: (x[0], int(x[1].replace('第','').replace('試合',''))))
        
        dates_row = [""] + [pd.to_datetime(c[0]).strftime('%Y/%m/%d') for c in sorted_cols]
        match_row = [""] + [c[1].replace("第", "").replace("試合", "") for c in sorted_cols]
        output_csv = ",".join(dates_row) + "\n" + ",".join(match_row) + "\n"
        
        all_players_sorted = sorted(list(PLAYER_TO_OWNER.keys()))
        for p in all_players_sorted:
            row_vals = [p]
            for col in sorted_cols:
                val = pivot_df.loc[p, col] if p in pivot_df.index else ""
                row_vals.append(str(val) if pd.notna(val) else "")
            output_csv += ",".join(row_vals) + "\n"
        
        st.download_button(
            label="💾 現在の結果をCSVで保存",
            data=output_csv.encode('cp932'),
            file_name=csv_file,
            mime="text/csv",
        )
