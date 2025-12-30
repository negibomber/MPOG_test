import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import plotly.express as px
import json
import os
import io

# --- 1. ページ基本設定 ---
st.set_page_config(page_title="M-POG Stats Hub", layout="wide")

# ==========================================
# 2. 設定ファイルの読み込み
# ==========================================
CONFIG_FILE = "draft_configs.json"

@st.cache_data
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

ARCHIVE_CONFIG = load_config()
if not ARCHIVE_CONFIG:
    st.error("設定ファイル draft_configs.json が読み込めません。")
    st.stop()

seasons = sorted(list(ARCHIVE_CONFIG.keys()), reverse=True)
selected_season = st.sidebar.selectbox("表示するシーズンを選択", seasons, index=0)

conf = ARCHIVE_CONFIG[selected_season]
SEASON_START = str(conf["start_date"])
SEASON_END = str(conf["end_date"])
TEAM_CONFIG = conf["teams"]

# 全シーズンの設定から「選手名 -> オーナー名」の対応表を構築
ALL_PLAYER_TO_OWNER = {}
for s_data in ARCHIVE_CONFIG.values():
    for owner_name, team_data in s_data['teams'].items():
        for p_name in team_data['players']:
            ALL_PLAYER_TO_OWNER[p_name] = owner_name

# --- スタイル設定 ---
st.markdown("""
<style>
    .pog-table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 0.9rem; }
    .pog-table th { background-color: #444; color: white !important; padding: 8px; border: 1px solid #333; }
    .pog-table td { border: 1px solid #ddd; padding: 8px; text-align: center; color: #000 !important; font-weight: bold; }
    .section-label { font-weight: bold; margin: 25px 0 10px 0; font-size: 1.3rem; border-left: 8px solid #444; padding-left: 12px; color: #333; }
</style>
""", unsafe_allow_html=True)

st.title(f"🏆 M-POG Stats Hub")

# ==========================================
# 3. データ処理ロジック (徹底したエラー回避)
# ==========================================

def safe_parse_csv(file_path):
    if not os.path.exists(file_path): return pd.DataFrame()
    try:
        # CP932とUTF-8の両方で試行
        try: raw_df = pd.read_csv(file_path, header=None, encoding='cp932')
        except: raw_df = pd.read_csv(file_path, header=None, encoding='utf-8')
        
        if len(raw_df) < 3: return pd.DataFrame()
        
        dates_row = raw_df.iloc[0].tolist()
        match_nums = raw_df.iloc[1].tolist()
        history = []
        
        for i in range(2, len(raw_df)):
            p_name = str(raw_df.iloc[i, 0]).strip()
            if not p_name or p_name == "nan": continue
            
            for col in range(1, len(raw_df.columns)):
                val = raw_df.iloc[i, col]
                if pd.isna(val) or str(val).strip() == "": continue
                try:
                    score = float(str(val).replace(' ', ''))
                    # 日付の補完処理
                    d_val = dates_row[col]
                    if pd.isna(d_val) or str(d_val).strip() in ["", "nan"]:
                        for back in range(col, 0, -1):
                            if not pd.isna(dates_row[back]) and str(dates_row[back]).strip() not in ["", "nan"]:
                                d_val = dates_row[back]
                                break
                    dt_str = pd.to_datetime(d_val).strftime('%Y%m%d')
                    m_num = int(float(str(match_nums[col]).strip()))
                    history.append({
                        "date": dt_str, "match_uid": f"{dt_str}_{m_num}", "m_label": f"第{m_num}試合",
                        "player": p_name, "point": score, "owner": ALL_PLAYER_TO_OWNER.get(p_name, "不明")
                    })
                except: continue
        return pd.DataFrame(history)
    except Exception as e:
        st.error(f"CSV読み込みエラー ({file_path}): {e}")
        return pd.DataFrame()

@st.cache_data(ttl=1800)
def fetch_web_history(s_start, s_end):
    url = "https://m-league.jp/games/"
    headers = {"User-Agent": "Mozilla/5.0"}
    history = []
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, 'html.parser')
        counter = {}
        for container in soup.find_all(class_="c-modal2"):
            mid = container.get('id', '')
            date_match = re.search(r'(\d{8})', mid)
            if not date_match: continue
            date_str = date_match.group(1)
            if not (s_start <= date_str <= s_end): continue
            
            counter[date_str] = counter.get(date_str, 0)
            columns = container.find_all(class_="p-gamesResult__column")
            for col in columns:
                counter[date_str] += 1
                m_num = counter[date_str]
                for item in col.find_all(class_="p-gamesResult__rank-item"):
                    n_el = item.find(class_="p-gamesResult__name")
                    p_el = item.find(class_="p-gamesResult__point")
                    if n_el and p_el:
                        name = n_el.get_text(strip=True)
                        p_val = "".join(re.findall(r'[0-9.\-]', p_el.get_text(strip=True).replace('▲', '-')))
                        if p_val:
                            history.append({
                                "date": date_str, "match_uid": f"{date_str}_{m_num}", "m_label": f"第{m_num}試合",
                                "player": name, "point": float(p_val), "owner": ALL_PLAYER_TO_OWNER.get(name, "不明")
                            })
        return pd.DataFrame(history)
    except: return pd.DataFrame()

# --- マスターデータの作成 ---
all_dfs = []
for s_name in seasons:
    df_temp = safe_parse_csv(f"history_{s_name}.csv")
    if not df_temp.empty: all_dfs.append(df_temp)

df_web = fetch_web_history(SEASON_START, SEASON_END)
if not df_web.empty: all_dfs.append(df_web)

if not all_dfs:
    st.error("有効なデータが1件もありません。CSVファイル名や中身を確認してください。")
    st.stop()

# 統合と着順判定
df_master = pd.concat(all_dfs).drop_duplicates(subset=['match_uid', 'player'])
df_master['rank'] = df_master.groupby('match_uid')['point'].rank(ascending=False, method='min').fillna(4).astype(int)

# ==========================================
# 4. メイン表示 (タブ構成)
# ==========================================

# ここでタブを定義
tabs = st.tabs(["📊 今期成績", "🏆 オーナー通算", "👤 選手通算"])

# --- TAB 1: 今期成績 ---
with tabs[0]:
    df_cur = df_master[df_master['date'].between(SEASON_START, SEASON_END)]
    if df_cur.empty:
        st.info("選択されたシーズンのデータはありません。")
    else:
        col1, col2 = st.columns([1, 1.2])
        pts = df_cur.groupby('player')['point'].sum()
        
        with col1:
            st.markdown('<div class="section-label">🏆 総合順位</div>', unsafe_allow_html=True)
            summary = [{"オーナー": o, "合計": sum(pts.get(p, 0) for p in c['players'])} for o, c in TEAM_CONFIG.items()]
            df_s = pd.DataFrame(summary).sort_values("合計", ascending=False)
            html = '<table class="pog-table"><tr><th>順位</th><th>オーナー</th><th>合計</th></tr>'
            for i, r in enumerate(df_s.itertuples(), 1):
                bg = TEAM_CONFIG[r.オーナー]['bg_color']
                html += f'<tr style="background-color:{bg}"><td>{i}</td><td>{r.オーナー}</td><td>{r.合計:+.1f}</td></tr>'
            st.markdown(html + '</table>', unsafe_allow_html=True)
        
        with col2:
            ld = df_cur['date'].max()
            st.markdown(f'<div class="section-label">🀄 最新結果 ({ld[4:6]}/{ld[6:]})</div>', unsafe_allow_html=True)
            df_l = df_cur[df_cur['date'] == ld]
            for uid in sorted(df_l['match_uid'].unique()):
                df_m = df_l[df_l['match_uid'] == uid].sort_values("point", ascending=False)
                st.write(f"**{df_m['m_label'].iloc[0]}**")
                html = '<table class="pog-table"><tr><th>選手</th><th>点数</th></tr>'
                for row in df_m.itertuples():
                    bg = TEAM_CONFIG.get(row.owner, {'bg_color':'#eee'})['bg_color']
                    html += f'<tr style="background-color:{bg}"><td>{row.player}</td><td>{row.point:+.1f}</td></tr>'
                st.markdown(html + '</table>', unsafe_allow_html=True)

# --- TAB 2: オーナー通算 ---
with tabs[1]:
    st.markdown('<div class="section-label">🏅 オーナー別通算成績</div>', unsafe_allow_html=True)
    o_stats = df_master.groupby('owner').agg(
        通算ポイント=('point', 'sum'),
        試合数=('point', 'count')
    ).reset_index()
    for r in range(1, 5):
        o_stats[f'{r}着'] = df_master[df_master['rank'] == r].groupby('owner')['rank'].count().reindex(o_stats['owner'], fill_value=0).values
    o_stats['平均pt'] = (o_stats['通算ポイント'] / o_stats['試合数']).round(2)
    for r in range(1, 5):
        o_stats[f'{r}着率'] = (o_stats[f'{r}着'] / o_stats['試合数'] * 100).round(1).astype(str) + "%"
    st.dataframe(o_stats.sort_values('通算ポイント', ascending=False), use_container_width=True, hide_index=True)

# --- TAB 3: 選手通算 ---
with tabs[2]:
    st.markdown('<div class="section-label">🀄 選手別通算成績</div>', unsafe_allow_html=True)
    p_stats = df_master.groupby('player').agg(
        通算ポイント=('point', 'sum'),
        試合数=('point', 'count'),
        オーナー=('owner', 'first')
    ).reset_index()
    for r in range(1, 5):
        p_stats[f'{r}着'] = df_master[df_master['rank'] == r].groupby('player')['rank'].count().reindex(p_stats['player'], fill_value=0).values
    p_stats['平均pt'] = (p_stats['通算ポイント'] / p_stats['試合数']).round(2)
    for r in range(1, 5):
        p_stats[f'{r}着率'] = (p_stats[f'{r}着'] / p_stats['試合数'] * 100).round(1).astype(str) + "%"
    st.dataframe(p_stats.sort_values('通算ポイント', ascending=False), use_container_width=True, hide_index=True)

# --- デバッグ情報 (もしタブが出ない場合はここを確認) ---
with st.sidebar:
    st.markdown("---")
    st.write("🔧 デバッグ情報")
    st.write(f"読込データ数: {len(df_master)} 件")
    if st.button('🔄 データを最新に更新'):
        st.cache_data.clear()
        st.rerun()
