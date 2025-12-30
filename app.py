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
st.set_page_config(page_title="M-POG Stats Hub", layout="wide")

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

# 全期間の全選手名からオーナーを特定する辞書
ALL_PLAYER_TO_OWNER = {p: owner for s in ARCHIVE_CONFIG.values() for owner, c in s['teams'].items() for p in c['players']}

# --- スタイル設定 ---
st.markdown("""
<style>
    .pog-table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 0.9rem; }
    .pog-table th { background-color: #444; color: white !important; padding: 8px; border: 1px solid #333; }
    .pog-table td { border: 1px solid #ddd; padding: 8px; text-align: center; color: #000; font-weight: bold; }
    .section-label { font-weight: bold; margin: 25px 0 10px 0; font-size: 1.3rem; border-left: 8px solid #444; padding-left: 12px; color: #333; }
</style>
""", unsafe_allow_html=True)

st.title(f"🏆 M-POG Stats Hub")

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
        if not player_name or player_name == "nan": continue
        
        owner = ALL_PLAYER_TO_OWNER.get(player_name, "不明")
        
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
                    "date": date_str, "match_uid": f"{date_str}_{m_num}", "m_label": f"第{m_num}試合",
                    "player": player_name, "point": score, "owner": owner
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
            
            if date_str not in date_match_counter: date_match_counter[date_str] = 0

            columns = container.find_all(class_="p-gamesResult__column")
            for col in columns:
                date_match_counter[date_str] += 1
                curr_m = date_match_counter[date_str]
                items = col.find_all(class_="p-gamesResult__rank-item")
                for item in items:
                    name_el = item.find(class_="p-gamesResult__name")
                    point_el = item.find(class_="p-gamesResult__point")
                    if name_el and point_el:
                        name = name_el.get_text(strip=True)
                        p_raw = point_el.get_text(strip=True).replace('▲', '-').replace('pts', '').replace(' ', '')
                        p_val = "".join(re.findall(r'[0-9.\-]', p_raw))
                        if p_val:
                            history.append({
                                "date": date_str, "match_uid": f"{date_str}_{curr_m}", "m_label": f"第{curr_m}試合",
                                "player": name, "point": float(p_val), "owner": ALL_PLAYER_TO_OWNER.get(name, "不明")
                            })
        return pd.DataFrame(history)
    except: return pd.DataFrame()

# --- データの取得と統合 ---
@st.cache_data
def get_combined_data(selected_season, s_start, s_end):
    all_dfs = []
    # 過去CSVをすべて読み込む
    for s_name in seasons:
        path = f"history_{s_name}.csv"
        if os.path.exists(path):
            all_dfs.append(load_history_from_csv(path))
    
    # 今期の最新Webデータも取得（CSVに未保存の分）
    web_df = get_web_history(s_start, s_end)
    if not web_df.empty:
        all_dfs.append(web_df)
    
    if not all_dfs: return pd.DataFrame()
    
    combined = pd.concat(all_dfs).drop_duplicates(subset=['match_uid', 'player'])
    # 着順判定
    combined['rank'] = combined.groupby('match_uid')['point'].rank(ascending=False, method='min').astype(int)
    return combined

df_all = get_combined_data(selected_season, SEASON_START, SEASON_END)

# ==========================================
# 4. 成績算出ロジック
# ==========================================
def calculate_stats_table(df, group_key):
    stats = df.groupby(group_key).agg(
        通算ポイント=('point', 'sum'),
        試合数=('point', 'count'),
    ).reset_index()
    
    for r in range(1, 5):
        stats[f'{r}着'] = df[df['rank'] == r].groupby(group_key)['rank'].count().reindex(stats[group_key], fill_value=0).values

    stats['平均pt'] = (stats['通算ポイント'] / stats['試合数']).round(2)
    for r in range(1, 5):
        stats[f'{r}着率'] = (stats[f'{r}着'] / stats['試合数'] * 100).round(1).astype(str) + "%"
    
    return stats.sort_values('通算ポイント', ascending=False)

# ==========================================
# 5. メイン画面：タブ構成
# ==========================================
if df_all.empty:
    st.warning("データが読み込めませんでした。")
else:
    # タブを定義
    tab1, tab2, tab3 = st.tabs(["📊 今期成績", "🏆 オーナー通算", "👤 選手通算"])

    # --- TAB1: 今期成績 ---
    with tab1:
        df_current = df_all[df_all['date'].between(SEASON_START, SEASON_END)]
        if df_current.empty:
            st.write("選択されたシーズンのデータはありません。")
        else:
            col1, col2 = st.columns([1, 1.2])
            total_pts = df_current.groupby('player')['point'].sum()
            
            with col1:
                st.markdown('<div class="section-label">🏆 今期総合順位</div>', unsafe_allow_html=True)
                pog_summary = []
                for owner, cfg in TEAM_CONFIG.items():
                    score = sum([total_pts.get(p, 0) for p in cfg['players']])
                    pog_summary.append({"オーナー": owner, "合計": score})
                df_teams = pd.DataFrame(pog_summary).sort_values("合計", ascending=False)
                
                html = '<table class="pog-table"><tr><th>順位</th><th>オーナー</th><th>合計</th></tr>'
                for i, row in enumerate(df_teams.itertuples(), 1):
                    bg = TEAM_CONFIG[row.オーナー]['bg_color']
                    html += f'<tr style="background-color:{bg}"><td>{i}</td><td>{row.オーナー}</td><td>{row.合計:+.1f}</td></tr>'
                st.markdown(html + '</table>', unsafe_allow_html=True)

            with col2:
                ld = df_current['date'].max()
                st.markdown(f'<div class="section-label">🀄 最新結果 ({ld[4:6]}/{ld[6:]})</div>', unsafe_allow_html=True)
                df_l = df_current[df_current['date'] == ld]
                uids = sorted(df_l['match_uid'].unique(), key=lambda x: int(x.split('_')[1]))
                for m_uid in uids:
                    df_m = df_l[df_l['match_uid'] == m_uid].sort_values("point", ascending=False)
                    st.write(f"**{df_m['m_label'].iloc[0]}**")
                    html = '<table class="pog-table"><tr><th>選手</th><th>オーナー</th><th>ポイント</th></tr>'
                    for row in df_m.itertuples():
                        bg = TEAM_CONFIG.get(row.owner, {'bg_color': '#eee'})['bg_color']
                        html += f'<tr style="background-color:{bg}"><td>{row.player}</td><td>{row.owner}</td><td>{row.point:+.1f}</td></tr>'
                    st.markdown(html + '</table>', unsafe_allow_html=True)

            # グラフ表示
            st.markdown('<div class="section-label">📈 今期ポイント推移</div>', unsafe_allow_html=True)
            match_owner_pts = df_current.groupby(['match_uid', 'owner'])['point'].sum().unstack().fillna(0)
            sorted_uids = sorted(match_owner_pts.index, key=lambda x: (x.split('_')[0], int(x.split('_')[1])))
            daily_cum = match_owner_pts.reindex(sorted_uids).cumsum().reset_index()
            daily_cum['label'] = daily_cum['match_uid'].apply(lambda x: f"{x[4:6]}/{x[6:8]}-{x[9:]}")
            df_plot = daily_cum.melt(id_vars=['match_uid', 'label'], var_name='オーナー', value_name='累計pt')
            fig = px.line(df_plot, x='label', y='累計pt', color='オーナー', 
                           color_discrete_map={k: v['color'] for k, v in TEAM_CONFIG.items()}, markers=True)
            st.plotly_chart(fig, use_container_width=True)

    # --- TAB2: オーナー通算 ---
    with tab2:
        st.markdown('<div class="section-label">🏅 オーナー別通算成績</div>', unsafe_allow_html=True)
        owner_stats = calculate_stats_table(df_all, 'owner')
        st.dataframe(owner_stats, use_container_width=True, hide_index=True)

    # --- TAB3: 選手通算 ---
    with tab3:
        st.markdown('<div class="section-label">🀄 選手別通算成績</div>', unsafe_allow_html=True)
        player_stats = calculate_stats_table(df_all, 'player')
        st.dataframe(player_stats, use_container_width=True, hide_index=True)

# ==========================================
# 6. 管理機能
# ==========================================
with st.sidebar:
    st.markdown("---")
    if st.button('🔄 データを最新に更新'):
        st.cache_data.clear()
        st.rerun()
    
    # 今期のCSV保存機能
    if not df_all.empty:
        df_cur = df_all[df_all['date'].between(SEASON_START, SEASON_END)]
        pivot_df = df_cur.pivot(index='player', columns=['date', 'm_label'], values='point')
        # ... (CSV出力ロジックは前回同様)
        st.write("※CSV保存はサイドバーの下部から可能です")
