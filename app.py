import streamlit as st
import pandas as pd
import json
import os
import re
import plotly.express as px
import requests
from bs4 import BeautifulSoup
import io
import datetime

# --- 1. ページ基本設定 ---
st.set_page_config(page_title="M-POG Archives & Stats", layout="wide")

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

# 全選手のオーナー逆引き辞書 ＆ 色情報の収集
ALL_PLAYER_TO_OWNER = {}
OWNER_COLOR_MAP = {} 
if ARCHIVE_CONFIG:
    for s_data in ARCHIVE_CONFIG.values():
        for owner_name, team_data in s_data.get('teams', {}).items():
            if 'bg_color' in team_data:
                OWNER_COLOR_MAP[owner_name] = team_data['bg_color']
            for p_name in team_data.get('players', []):
                ALL_PLAYER_TO_OWNER[p_name] = owner_name

# サイドバー：シーズン選択（今期成績タブの表示切り替え用）
seasons = sorted(list(ARCHIVE_CONFIG.keys()), reverse=True) if ARCHIVE_CONFIG else ["No Data"]
selected_season = st.sidebar.selectbox("表示するシーズンを選択", seasons, index=0)

# ==========================================
# 3. データ処理（全期間・全シーズンを対象）
# ==========================================

@st.cache_data(ttl=1800)
def fetch_web_history_all_seasons():
    """全シーズンのWebデータを取得（通算成績用）"""
    url = "https://m-league.jp/games/"
    headers = {"User-Agent": "Mozilla/5.0"}
    history = []
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 設定ファイルから全期間の最小・最大日付を特定
        all_starts = [str(c.get("start_date", "99999999")) for c in ARCHIVE_CONFIG.values()]
        all_ends = [str(c.get("end_date", "00000000")) for c in ARCHIVE_CONFIG.values()]
        global_start = min(all_starts) if all_starts else "20000101"
        global_end = max(all_ends) if all_ends else "20991231"

        counter = {}
        for container in soup.find_all(class_="c-modal2"):
            mid = container.get('id', '')
            date_match = re.search(r'(\d{8})', mid)
            if not date_match: continue
            date_str = date_match.group(1)
            # 全期間のいずれかに該当すれば取得
            if not (global_start <= date_str <= global_end): continue
            
            # どのシーズンに属するか判定
            match_season = "Unknown"
            for s_name, s_conf in ARCHIVE_CONFIG.items():
                if str(s_conf.get("start_date", "")) <= date_str <= str(s_conf.get("end_date", "")):
                    match_season = s_name
                    break

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
                                "season": match_season, "date": date_str, "match_uid": f"{date_str}_{m_num}", 
                                "m_label": f"第{m_num}試合", "player": name, "point": float(p_val), 
                                "owner": ALL_PLAYER_TO_OWNER.get(name, "不明")
                            })
        return pd.DataFrame(history)
    except: return pd.DataFrame()

def get_master_data():
    all_rows = []
    # 1. 過去の全CSVファイルを読み込む
    csv_files = [f for f in os.listdir('.') if f.startswith('history_') and f.endswith('.csv')]
    for f_path in csv_files:
        try:
            try: df = pd.read_csv(f_path, encoding='cp932')
            except: df = pd.read_csv(f_path, encoding='utf-8')
            # 既に整形済みのCSV（前回までのダウンロード機能で作成したもの）か判定
            if 'match_uid' in df.columns:
                all_rows.extend(df.to_dict('records'))
            else:
                # 生の古い形式のCSV読み込み（互換性維持）
                try: df_raw = pd.read_csv(f_path, header=None, encoding='cp932')
                except: df_raw = pd.read_csv(f_path, header=None, encoding='utf-8')
                if len(df_raw) < 3: continue
                dates, nums = df_raw.iloc[0].tolist(), df_raw.iloc[1].tolist()
                s_name = f_path.replace("history_","").replace(".csv","")
                for i in range(2, len(df_raw)):
                    p_name = str(df_raw.iloc[i, 0]).strip()
                    if not p_name or p_name == "nan": continue
                    for col in range(1, len(df_raw.columns)):
                        val = df_raw.iloc[col] if i >= len(df_raw) else df_raw.iloc[i, col]
                        if pd.isna(val) or str(val).strip() == "": continue
                        # ...既存の読み込み処理... (簡略化のため下記に合流)
        except: continue
    
    # 2. Webから全データを取得して合算
    df_web = fetch_web_history_all_seasons()
    df_all = pd.concat([pd.DataFrame(all_rows), df_web]).drop_duplicates(subset=['match_uid', 'player']) if not (pd.DataFrame(all_rows).empty and df_web.empty) else pd.DataFrame()
    
    if not df_all.empty:
        # 正確な順位を全データに対して再計算
        df_all['rank'] = df_all.groupby('match_uid')['point'].rank(ascending=False, method='min').fillna(4).astype(int)
    return df_all

df_master = get_master_data()

# ==========================================
# 4. サイドバー管理
# ==========================================
with st.sidebar:
    st.divider()
    st.markdown("### 🛠 データ管理")
    if st.button('🔄 データを最新に更新'):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.caption(f"Total Records: {len(df_master)} matches")

# ==========================================
# 5. メインタブ表示
# ==========================================
tab1, tab2, tab3 = st.tabs(["📊 今期成績", "🏆 オーナー通算", "👤 選手通算"])

with tab1:
    if df_master.empty:
        st.warning("データがありません。")
    else:
        # 今期成績タブのみ、選択されたシーズンでフィルタ
        df_cur = df_master[df_master['season'] == selected_season]
        if df_cur.empty:
            st.info(f"シーズン {selected_season} のデータはありません。")
        else:
            col1, col2 = st.columns([1, 1.2])
            pts_cur = df_cur.groupby('player')['point'].sum()
            with col1:
                st.markdown('<div class="section-label">🏆 総合順位</div>', unsafe_allow_html=True)
                summary = []
                cur_teams = ARCHIVE_CONFIG.get(selected_season, {}).get('teams', {})
                for o, c in cur_teams.items():
                    s = sum(pts_cur.get(p, 0) for p in c.get('players', []))
                    summary.append({"オーナー": o, "合計": s})
                df_s = pd.DataFrame(summary).sort_values("合計", ascending=False)
                html = '<table width="100%" style="border-collapse:collapse; font-size:0.9rem;">'
                html += '<tr style="background:#444; color:white;"><th>順位</th><th>オーナー</th><th>合計</th></tr>'
                for i, r in enumerate(df_s.itertuples(), 1):
                    bg = cur_teams.get(r.オーナー, {}).get('bg_color', '#fff')
                    html += f'<tr style="background-color:{bg}; border-bottom:1px solid #ddd;"><td style="padding:8px; text-align:center;">{i}</td><td style="padding:8px; text-align:center;">{r.オーナー}</td><td style="padding:8px; text-align:center;">{r.合計:+.1f}</td></tr>'
                st.markdown(html + '</table>', unsafe_allow_html=True)

            with col2:
                ld = df_cur['date'].max()
                st.markdown(f'<div class="section-label">🀄 最新結果 ({ld[4:6]}/{ld[6:]})</div>', unsafe_allow_html=True)
                df_l = df_cur[df_cur['date'] == ld]
                for uid in sorted(df_l['match_uid'].unique()):
                    df_m = df_l[df_l['match_uid'] == uid].sort_values("point", ascending=False)
                    st.write(f"**{df_m['m_label'].iloc[0]}**")
                    html = '<table width="100%" style="border-collapse:collapse; font-size:0.85rem;">'
                    html += '<tr style="background:#666; color:white;"><th>選手</th><th>オーナー</th><th>ポイント</th></tr>'
                    for row in df_m.itertuples():
                        bg = cur_teams.get(row.owner, {'bg_color':'#eee'})['bg_color']
                        html += f'<tr style="background-color:{bg}; border-bottom:1px solid #ddd;"><td style="padding:6px; text-align:center;">{row.player}</td><td style="padding:6px; text-align:center;">{row.owner}</td><td style="padding:6px; text-align:center;">{row.point:+.1f}</td></tr>'
                    st.markdown(html + '</table>', unsafe_allow_html=True)
            
            st.markdown('<div class="section-label">📈 ポイント推移</div>', unsafe_allow_html=True)
            match_pts = df_cur.groupby(['match_uid', 'owner'])['point'].sum().unstack().fillna(0)
            sorted_uids = sorted(match_pts.index, key=lambda x: (x.split('_')[0], int(x.split('_')[1])))
            daily_cum = match_pts.reindex(sorted_uids).cumsum().reset_index()
            daily_cum['label'] = daily_cum['match_uid'].apply(lambda x: f"{x[4:6]}/{x[6:8]}-{x[9:]}")
            df_plot = daily_cum.melt(id_vars=['match_uid', 'label'], var_name='オーナー', value_name='累計pt')
            fig = px.line(df_plot, x='label', y='累計pt', color='オーナー', 
                           color_discrete_map={k: v['color'] for k, v in cur_teams.items()}, markers=True)
            st.plotly_chart(fig, use_container_width=True)

# 通算成績データ作成（df_master全体を使用）
def get_stats_df(df, group_key):
    stats = df.groupby(group_key).agg(通算pt=('point','sum'), 試合数=('point','count')).reset_index()
    for r in range(1, 5):
        counts = df[df['rank']==r].groupby(group_key)['rank'].count().reindex(stats[group_key], fill_value=0).values
        stats[f'{r}着'] = counts
        stats[f'{r}着(%)'] = (counts / stats['試合数'] * 100).round(1)
    
    stats['平均pt'] = (stats['通算pt'] / stats['試合数']).round(2)
    cols = [group_key, '通算pt', '試合数', '平均pt', '1着', '1着(%)', '2着', '2着(%)', '3着', '3着(%)', '4着', '4着(%)']
    return stats[cols].sort_values('通算pt', ascending=False)

COL_CONFIG = {
    "通算pt": st.column_config.NumberColumn("通算pt", format="%.1f"),
    "平均pt": st.column_config.NumberColumn("平均pt", format="%.2f"),
    "1着(%)": st.column_config.NumberColumn("1着率", format="%.1f%%"),
    "2着(%)": st.column_config.NumberColumn("2着率", format="%.1f%%"),
    "3着(%)": st.column_config.NumberColumn("3着率", format="%.1f%%"),
    "4着(%)": st.column_config.NumberColumn("4着率", format="%.1f%%"),
}

with tab2:
    st.markdown('<div class="section-label">🏅 オーナー別通算成績 (全シーズン合算)</div>', unsafe_allow_html=True)
    if not df_master.empty:
        df_owner = get_stats_df(df_master[df_master['owner'] != "不明"], 'owner').set_index('owner')
        def style_full_row(row):
            color = OWNER_COLOR_MAP.get(row.name, "#ffffff")
            return [f'background-color: {color}; color: black; font-weight: bold'] * len(row)
        
        st.dataframe(df_owner.style.apply(style_full_row, axis=1), use_container_width=True, column_config=COL_CONFIG)

with tab3:
    st.markdown('<div class="section-label">👤 選手別通算成績 (全シーズン合算)</div>', unsafe_allow_html=True)
    if not df_master.empty:
        df_player = get_stats_df(df_master, 'player').set_index('player')
        st.dataframe(df_player, use_container_width=True, column_config=COL_CONFIG)
