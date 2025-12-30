import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import json
import os

# --- 1. ページ基本設定 ---
st.set_page_config(page_title="M-POG Stats Hub", layout="wide")

# ==========================================
# 2. 設定ファイルの読み込み
# ==========================================
CONFIG_FILE = "draft_configs.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            st.error(f"JSON読み込みエラー: {e}")
            return {}
    return {}

ARCHIVE_CONFIG = load_config()

if not ARCHIVE_CONFIG:
    st.error("設定ファイル draft_configs.json が見つかりません。")
    st.stop()

# サイドバー設定
seasons = sorted(list(ARCHIVE_CONFIG.keys()), reverse=True)
selected_season = st.sidebar.selectbox("表示するシーズンを選択", seasons, index=0)

# 表示モードの切り替え（タブが表示されない場合の保険）
view_mode = st.sidebar.radio("表示切替", ["📊 今期成績", "🏆 オーナー通算", "👤 選手通算"])

conf = ARCHIVE_CONFIG[selected_season]
SEASON_START = str(conf.get("start_date", "20000101"))
SEASON_END = str(conf.get("end_date", "20991231"))
TEAM_CONFIG = conf.get("teams", {})

# 全選手の逆引き辞書
ALL_PLAYER_TO_OWNER = {}
for s_data in ARCHIVE_CONFIG.values():
    for owner_name, team_data in s_data.get('teams', {}).items():
        for p_name in team_data.get('players', []):
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
# 3. データ処理ロジック (エラーを握り潰して停止させない)
# ==========================================

def get_all_data():
    all_rows = []
    
    # CSV読み込み
    for s_name in seasons:
        f_path = f"history_{s_name}.csv"
        if os.path.exists(f_path):
            try:
                # 読み込み
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
                            # 数値変換
                            score = float(str(val).strip())
                            # 日付補完
                            d_val = dates[col]
                            if pd.isna(d_val) or str(d_val).strip() == "":
                                for b in range(col, 0, -1):
                                    if not pd.isna(dates[b]) and str(dates[b]).strip() != "":
                                        d_val = dates[b]
                                        break
                            
                            d_str = pd.to_datetime(d_val).strftime('%Y%m%d')
                            m_num = int(float(str(nums[col])))
                            
                            all_rows.append({
                                "date": d_str, "match_uid": f"{d_str}_{m_num}", "m_label": f"第{m_num}試合",
                                "player": p_name, "point": score, "owner": ALL_PLAYER_TO_OWNER.get(p_name, "不明")
                            })
                        except: continue
            except Exception as e:
                st.sidebar.error(f"ファイル読込失敗({s_name}): {e}")

    if not all_rows: return pd.DataFrame()
    
    res = pd.DataFrame(all_rows).drop_duplicates(subset=['match_uid', 'player'])
    # 着順判定
    res['rank'] = res.groupby('match_uid')['point'].rank(ascending=False, method='min').fillna(4).astype(int)
    return res

# データの取得
df_master = get_all_data()

# デバッグ用情報（サイドバー）
st.sidebar.write(f"📊 読込データ総数: {len(df_master)} 件")

# ==========================================
# 4. 表示セクション
# ==========================================

if view_mode == "📊 今期成績":
    st.header(f"今期スコア ({selected_season})")
    if df_master.empty:
        st.warning("データが読み込まれていません。CSVファイルが正しいか確認してください。")
    else:
        df_cur = df_master[df_master['date'].between(SEASON_START, SEASON_END)]
        if df_cur.empty:
            st.info("この期間のデータはありません。")
        else:
            # 順位表の表示
            pts = df_cur.groupby('player')['point'].sum()
            summary = []
            for o, c in TEAM_CONFIG.items():
                s = sum(pts.get(p, 0) for p in c.get('players', []))
                summary.append({"オーナー": o, "合計": s})
            df_s = pd.DataFrame(summary).sort_values("合計", ascending=False)
            
            st.markdown('<div class="section-label">🏆 総合順位</div>', unsafe_allow_html=True)
            html = '<table class="pog-table"><tr><th>順位</th><th>オーナー</th><th>合計</th></tr>'
            for i, r in enumerate(df_s.itertuples(), 1):
                bg = TEAM_CONFIG.get(r.オーナー, {}).get('bg_color', '#fff')
                html += f'<tr style="background-color:{bg}"><td>{i}</td><td>{r.オーナー}</td><td>{r.合計:+.1f}</td></tr>'
            st.markdown(html + '</table>', unsafe_allow_html=True)

elif view_mode == "🏆 オーナー通算":
    st.header("オーナー通算成績")
    if not df_master.empty:
        o_stats = df_master.groupby('owner').agg(通算pt=('point','sum'), 試合数=('point','count')).reset_index()
        for r in range(1, 5):
            o_stats[f'{r}着'] = df_master[df_master['rank']==r].groupby('owner')['rank'].count().reindex(o_stats['owner'], fill_value=0).values
        o_stats['平均pt'] = (o_stats['通算pt'] / o_stats['試合数']).round(2)
        st.dataframe(o_stats.sort_values('通算pt', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.error("データがありません。")

elif view_mode == "👤 選手通算":
    st.header("選手通算成績")
    if not df_master.empty:
        p_stats = df_master.groupby('player').agg(通算pt=('point','sum'), 試合数=('point','count')).reset_index()
        for r in range(1, 5):
            p_stats[f'{r}着'] = df_master[df_master['rank']==r].groupby('player')['rank'].count().reindex(p_stats['player'], fill_value=0).values
        p_stats['平均pt'] = (p_stats['通算pt'] / p_stats['試合数']).round(2)
        st.dataframe(p_stats.sort_values('通算pt', ascending=False), use_container_width=True, hide_index=True)

# ==========================================
# 5. 管理機能
# ==========================================
if st.sidebar.button('🔄 キャッシュクリア'):
    st.cache_data.clear()
    st.rerun()
