import streamlit as st
import pandas as pd
import json
import os
import re

# --- 1. 画面初期化 ---
st.set_page_config(page_title="M-POG Debug Mode", layout="wide")
st.title("🛠 M-POG システム復旧・デバッグ画面")

# ==========================================
# 2. 設定読み込み (エラーならここで止まるはず)
# ==========================================
CONFIG_FILE = "draft_configs.json"

@st.cache_data
def load_config_safe():
    if not os.path.exists(CONFIG_FILE):
        return None, "draft_configs.json が見つかりません。"
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"JSON読み込み失敗: {e}"

ARCHIVE_CONFIG, config_error = load_config_safe()

if config_error:
    st.error(config_error)
    st.stop()

# ==========================================
# 3. データ解析関数 (1行ずつチェック)
# ==========================================
def ultra_safe_load():
    all_data = []
    seasons = sorted(list(ARCHIVE_CONFIG.keys()), reverse=True)
    
    # オーナー対応表
    player_map = {}
    for s in ARCHIVE_CONFIG.values():
        for owner, team in s.get('teams', {}).items():
            for p in team.get('players', []):
                player_map[p] = owner

    for s_name in seasons:
        path = f"history_{s_name}.csv"
        if not os.path.exists(path):
            continue
            
        try:
            # エンコーディングを変えて試行
            try: df = pd.read_csv(path, header=None, encoding='cp932')
            except: df = pd.read_csv(path, header=None, encoding='utf-8')
            
            if len(df) < 3: continue
            
            dates = df.iloc[0].tolist()
            nums = df.iloc[1].tolist()
            
            for i in range(2, len(df)):
                p_name = str(df.iloc[i, 0]).strip()
                if not p_name or p_name == "nan": continue
                
                for col in range(1, len(df.columns)):
                    val = str(df.iloc[i, col]).strip()
                    if not val or val == "nan" or val == "": continue
                    
                    try:
                        # 数値クレンジング（▲をマイナスに、空白を削除）
                        clean_val = val.replace('▲', '-').replace(' ', '').replace('pts', '')
                        score = float(clean_val)
                        
                        # 日付特定
                        d_raw = dates[col]
                        if pd.isna(d_raw) or str(d_raw) == "":
                            # 前の列から補完
                            for b in range(col, 0, -1):
                                if not pd.isna(dates[b]) and str(dates[b]) != "":
                                    d_raw = dates[b]
                                    break
                        
                        d_str = pd.to_datetime(d_raw).strftime('%Y%m%d')
                        m_num = int(float(str(nums[col])))
                        
                        all_data.append({
                            "season": s_name,
                            "date": d_str,
                            "match_uid": f"{d_str}_{m_num}",
                            "player": p_name,
                            "point": score,
                            "owner": player_map.get(p_name, "不明")
                        })
                    except:
                        continue # 数値化できない列は無視
        except Exception as e:
            st.warning(f"ファイル {path} の解析中にスキップが発生しました: {e}")

    return pd.DataFrame(all_data)

# データの取得
df_master = ultra_safe_load()

# ==========================================
# 4. メイン画面 (サイドバーを使わず直接配置)
# ==========================================

# サイドバーが消える対策として、メイン画面上部にラジオボタンを配置
st.write("---")
view_mode = st.radio(
    "📊 表示する内容を選択してください",
    ["今期成績", "オーナー通算", "選手通算"],
    horizontal=True
)
st.write("---")

if df_master.empty:
    st.error("❌ データが読み込めていません。CSVファイルがプログラムと同じフォルダにあるか確認してください。")
    st.info(f"現在のフォルダにあるファイル: {os.listdir('.')}")
else:
    # 着順判定
    df_master['rank'] = df_master.groupby('match_uid')['point'].rank(ascending=False, method='min').astype(int)

    if view_mode == "今期成績":
        # 最新のシーズンを取得
        latest_s = sorted(df_master['season'].unique(), reverse=True)[0]
        st.header(f"今期スコア ({latest_s})")
        df_cur = df_master[df_master['season'] == latest_s]
        
        # 簡易ランキング
        res = df_cur.groupby('owner')['point'].sum().sort_values(ascending=False).reset_index()
        st.table(res)

    elif view_mode == "オーナー通算":
        st.header("🏆 オーナー通算成績")
        o_stats = df_master.groupby('owner').agg(
            通算pt=('point', 'sum'),
            試合数=('point', 'count')
        ).reset_index()
        
        for r in range(1, 5):
            o_stats[f'{r}着'] = df_master[df_master['rank'] == r].groupby('owner')['rank'].count().reindex(o_stats['owner'], fill_value=0).values
        
        o_stats['平均pt'] = (o_stats['通算pt'] / o_stats['試合数']).round(2)
        for r in range(1, 5):
            o_stats[f'{r}着率'] = (o_stats[f'{r}着'] / o_stats['試合数'] * 100).round(1).map(lambda x: f"{x}%")
            
        st.dataframe(o_stats.sort_values('通算pt', ascending=False), use_container_width=True)

    elif view_mode == "選手通算":
        st.header("👤 選手通算成績")
        p_stats = df_master.groupby('player').agg(
            通算pt=('point', 'sum'),
            試合数=('point', 'count'),
            最終所属=('owner', 'last')
        ).reset_index()
        
        for r in range(1, 5):
            p_stats[f'{r}着'] = df_master[df_master['rank'] == r].groupby('player')['rank'].count().reindex(p_stats['player'], fill_value=0).values
        
        p_stats['平均pt'] = (p_stats['通算pt'] / p_stats['試合数']).round(2)
        st.dataframe(p_stats.sort_values('通算pt', ascending=False), use_container_width=True)

# 最後にデバッグ情報をサイドバーへ
with st.sidebar:
    st.subheader("Debug Info")
    st.write(f"Total Records: {len(df_master)}")
    if not df_master.empty:
        st.write("Seasons found:", df_master['season'].unique())
