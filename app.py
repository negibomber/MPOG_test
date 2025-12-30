import streamlit as st
import pandas as pd
import json
import os
import re
import plotly.express as px
import requests
from bs4 import BeautifulSoup

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

# 選手とオーナーの紐付け（全期間）
ALL_PLAYER_TO_OWNER = {}
if ARCHIVE_CONFIG:
    for s_data in ARCHIVE_CONFIG.values():
        for owner_name, team_data in s_data.get('teams', {}).items():
            for p_name in team_data.get('players', []):
                ALL_PLAYER_TO_OWNER[p_name] = owner_name

# --- サイドバー：シーズン選択 ---
seasons = sorted(list(ARCHIVE_CONFIG.keys()), reverse=True) if ARCHIVE_CONFIG else ["No Data"]
selected_season = st.sidebar.selectbox("表示するシーズンを選択", seasons, index=0)

# スタイル
st.markdown("""
<style>
    .pog-table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 0.9rem; }
    .pog-table th { background-color: #444; color: white !important; padding: 8px; border: 1px solid #333; }
    .pog-table td { border: 1px solid #ddd; padding: 8px; text-align: center; color: #000 !important; font-weight: bold; }
    .section-label { font-weight: bold; margin: 20px 0 10px 0; font-size: 1.2rem; border-left: 6px solid #444; padding-left: 10px; color: #333; }
</style>
""", unsafe_allow_html=True)

st.title(f"🏆 M-POG Stats Hub")

# ==========================================
# 3. データ読み込み（エラーでも空のDFを返す）
# ==========================================

def get_master_data():
    all_rows = []
    # フォルダ内の全ての history_*.csv を読み込む
    csv_files = [f for f in os.listdir('.') if f.startswith('history_') and f.endswith('.csv')]
    
    for f_path in csv_files:
        try:
            try: df = pd.read_csv(f_path, header=None, encoding='cp932')
            except: df = pd.read_csv(f_path, header=None, encoding='utf-8')
            
            if len(df) < 3: continue
            dates = df.iloc[0].tolist()
            nums = df.iloc[1].tolist()
            
            for i in range(2, len(df)):
                p_name = str(df.iloc[i, 0]).strip()
                if not p_name or p_name == "nan": continue
                for col in range(1, len(df.columns)):
                    val = df.iloc[i, col]
                    if pd.isna(val) or str(val).strip() == "": continue
                    try:
                        score = float(str(val).replace('▲', '-').replace(' ', ''))
                        d_val = dates[col]
                        if pd.isna(d_val) or str(d_val) == "":
                            for b in range(col, 0, -1):
                                if not pd.isna(dates[b]) and str(dates[b]) != "":
                                    d_val = dates[b]
                                    break
                        d_str = pd.to_datetime(d_val).strftime('%Y%m%d')
                        m_num = int(float(str(nums[col])))
                        
                        all_rows.append({
                            "season": f_path.replace("history_","").replace(".csv",""),
                            "date": d_str,
                            "match_uid": f"{d_str}_{m_num}",
                            "player": p_name,
                            "point": score,
                            "owner": ALL_PLAYER_TO_OWNER.get(p_name, "不明")
                        })
                    except: continue
        except: continue
    
    if not all_rows: return pd.DataFrame()
    res = pd.DataFrame(all_rows).drop_duplicates(subset=['match_uid', 'player'])
    res['rank'] = res.groupby('match_uid')['point'].rank(ascending=False, method='min').fillna(4).astype(int)
    return res

df_master = get_master_data()

# ==========================================
# 4. タブの表示（データの有無に関わらず実行）
# ==========================================

# タブの作成（この行が実行されれば必ず表示されます）
tab1, tab2, tab3 = st.tabs(["📊 今期成績", "🏆 オーナー通算", "👤 選手通算"])

# --- TAB 1: 今期成績 ---
with tab1:
    if df_master.empty:
        st.warning("データが読み込めませんでした。history_*.csv が配置されているか確認してください。")
    else:
        st.subheader(f"{selected_season} シーズンスコア")
        # 選択中のシーズンのデータを抽出
        df_cur = df_master[df_master['season'] == selected_season]
        if df_cur.empty:
            st.info("このシーズンの記録はありません。")
        else:
            # 簡易集計
            cur_pts = df_cur.groupby('owner')['point'].sum().sort_values(ascending=False).reset_index()
            st.table(cur_pts)

# --- TAB 2: オーナー通算 ---
with tab2:
    st.subheader("オーナー別通算成績（全期間）")
    if not df_master.empty:
        o_stats = df_master.groupby('owner').agg(
            通算ポイント=('point', 'sum'),
            試合数=('point', 'count')
        ).reset_index()
        # 1-4着のカウント
        for r in range(1, 5):
            o_stats[f'{r}着'] = df_master[df_master['rank'] == r].groupby('owner')['rank'].count().reindex(o_stats['owner'], fill_value=0).values
        
        o_stats['平均pt'] = (o_stats['通算ポイント'] / o_stats['試合数']).round(2)
        # 着順率の計算
        for r in range(1, 5):
            o_stats[f'{r}着率'] = (o_stats[f'{r}着'] / o_stats['試合数'] * 100).round(1).astype(str) + "%"
        
        st.dataframe(o_stats.sort_values('通算ポイント', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.write("データがありません。")

# --- TAB 3: 選手通算 ---
with tab3:
    st.subheader("選手別通算成績（全期間）")
    if not df_master.empty:
        p_stats = df_master.groupby('player').agg(
            通算ポイント=('point', 'sum'),
            試合数=('point', 'count'),
            オーナー=('owner', 'last')
        ).reset_index()
        for r in range(1, 5):
            p_stats[f'{r}着'] = df_master[df_master['rank'] == r].groupby('player')['rank'].count().reindex(p_stats['player'], fill_value=0).values
        
        p_stats['平均pt'] = (p_stats['通算ポイント'] / p_stats['試合数']).round(2)
        for r in range(1, 5):
            p_stats[f'{r}着率'] = (p_stats[f'{r}着'] / p_stats['試合数'] * 100).round(1).astype(str) + "%"
            
        st.dataframe(p_stats.sort_values('通算ポイント', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.write("データがありません。")

# デバッグ用（サイドバーにファイルの状態を出す）
with st.sidebar:
    st.divider()
    st.write(f"読み込みデータ数: {len(df_master)}件")
    if st.checkbox("デバッグ：ファイル一覧を表示"):
        st.write(os.listdir('.'))
