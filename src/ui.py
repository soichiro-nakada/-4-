import streamlit as st
import numpy as np
import plotly.express as px  # 追加
from .constants import ACCOUNT_TYPE_MAP, TYPE_ORDER, DYNAMIC_ACCOUNTS, PAGE_CONFIG
from .data_loader import *


# ダッシュボードを作成する関数
def create_dashboard(df, df_tb):
    st.header('Dash Board')

    # --- データの準備 ---
    # 試算表データから、分類ごとのデータを抽出
    df_clean = df_tb.reset_index()
    
    # 損益と資産のデータを抽出
    df_pl = df_clean[df_clean['分類'].isin(['費用', '収益'])]
    df_assets = df_clean[df_clean['分類'] == '資産']
    
    # KPI計算
    total_revenue = df_clean[df_clean['分類'] == '収益']['残高'].sum()
    total_expense = df_clean[df_clean['分類'] == '費用']['残高'].sum()
    net_income = total_revenue - total_expense
    total_assets = df_assets['残高'].sum()

    # 負債合計 (分類が「負債」のものの合計)
    df_liabilities = df_clean[df_clean['分類'] == '負債']
    total_liabilities = df_liabilities['残高'].sum()
    
    # 純資産 (資産 - 負債) ※これが真の資産
    net_assets = total_assets - total_liabilities

    # --- A. KPIメトリクス（最上段） ---
    st.subheader('✅ Summary')
    col1, col2, col3, col4 = st.columns(4)
    col1.metric('純資産総額', chr(165) + f'{net_assets:,.0f}')
    col2.metric('資産総額', chr(165) + f'{total_assets:,.0f}')
    col3.metric('当期純利益', chr(165) + f'{net_income:,.0f}', delta_color='normal')
    col4.metric('費用合計', chr(165) + f'{total_expense:,.0f}', delta_color='inverse') # 費用は増えると赤字(inverse)

    st.subheader('📈 純資産の推移')

    df_trend = calculate_daily_trends(df)
    
    if not df_trend.empty:
        # 1. 折れ線グラフとして描画 (px.line)
        #    ※描画順序が重要です。一番大きい「資産」を最初に描くことで、
        #    後ろに隠れてしまうのを防ぎます（リストの先頭が最背面になります）
        fig_trend = px.line(
            df_trend, 
            x='日付', 
            y=['資産', '純資産', '負債'], # 大きい順（資産）を先に書くのがコツ
            title='資産・負債・純資産の推移',
            color_discrete_map={
                # 原色(青・緑・赤)を明るくしたカラーコード
                '資産': '#6699FF',   # 薄いブルー (CornflowerBlue系)
                '純資産': '#66FF99', # 薄いグリーン (SpringGreenを淡くした感じ)
                '負債': '#FF9999'    # 薄いレッド (Salmon/LightCoral系)
            }
        )
        
        # 2. 塗りつぶし設定を追加 (ここがポイント！)
        #    fill='tozeroy': 0のラインまで色を塗る設定
        fig_trend.update_traces(fill='tozeroy', opacity=0.6)
        
        # (オプション) レイアウト調整
        fig_trend.update_layout(
            xaxis_title='日付',
            yaxis_title='金額 (円)',
            hovermode='x unified',
            yaxis=dict(
                # tickformat=',.0f' : カンマ区切りで整数表示 (例: 3,000,000)
                # tickprefix='¥'    : 数字の前に円マークをつける
                tickformat=',.0f', 
                tickprefix=chr(165)
            ),
            xaxis=dict(
                # tickformat='%Y/%m/%d' : 2025/01/01 の形式で表示
                tickformat='%Y/%m/%d'
            )
        )

        # ホバー（マウスオーバー）時のフォーマットも合わせる
        fig_trend.update_traces(
            hovertemplate='%{y:,.0f} 円' # ホバー時に「3,000,000 円」と表示
        )
        
        st.plotly_chart(fig_trend, use_container_width=True)
    else:
        st.info('推移を表示するためのデータが不足しています')

    st.divider()

    # --- B. 円グラフ（中段） ---
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader('費用の内訳')
        # 1. 費用データを抽出して、残高の降順（大きい順）にソートする
        df_expense_pie = df_clean[df_clean['分類'] == '費用'].sort_values(by='残高', ascending=False)
        if not df_expense_pie.empty:
            fig_exp = px.pie(
                df_expense_pie, 
                values='残高', 
                names='勘定科目',
                hole=0.4, # ドーナツ型にする
            )
            fig_exp.update_traces(
                sort=False,           # Plotlyの自動ソートを無効化（DataFrameの順序を守らせる）
                direction='clockwise',# 時計回りに並べる
                rotation=0,          # 12時の位置（90度）から開始する
                textinfo='label+percent'
            )
            fig_exp.update_layout(showlegend=False) # 凡例を消してスッキリさせる
            fig_exp.update_traces(textinfo='label+percent') # ラベルと％を表示
            st.plotly_chart(fig_exp, use_container_width=True)
        else:
            st.info('費用データがありません')

    with col_right:
        st.subheader('資産ポートフォリオ')

        df_assets = df_assets.sort_values(by='残高', ascending=False)
        
        if not df_assets.empty:
            fig_asset = px.pie(
                df_assets, 
                values='残高', 
                names='勘定科目',
                hole=0.4,
            )
            fig_asset.update_traces(
                sort=False,           # Plotlyの自動ソートを無効化（DataFrameの順序を守らせる）
                direction='clockwise',# 時計回りに並べる
                rotation=0,          # 12時の位置（90度）から開始する
                textinfo='label+percent'
            )
            fig_asset.update_layout(showlegend=False)
            fig_asset.update_traces(textinfo='label+percent')
            st.plotly_chart(fig_asset, use_container_width=True)
        else:
            st.info('資産データがありません')

    # --- C. 日次推移グラフ（下段） ---
    st.subheader('日次収支の推移')
    
    # 元の仕訳データ(df)を使って、日ごとの集計を行う必要があります
    # 1. 仕訳データに「分類」をマッピングする
    #    (借方・貸方それぞれにマッピングして、費用と収益だけ抜き出す処理)
    
    # 簡易的に借方(費用)の発生日ベースで集計します
    df_daily = df.copy()
    # 日付、摘要欄を埋める
    df_daily['日付'] = df_daily['日付'].ffill()
    df_daily['摘要'] = df_daily['摘要'].ffill()
    # 借方科目の分類をマッピング
    df_daily['借方分類'] = df_daily['勘定科目(借方)'].map(ACCOUNT_TYPE_MAP)
    
    # 費用データのみ抽出
    df_expenses_daily = df_daily[df_daily['借方分類'] == '費用'].copy()
    
    if not df_expenses_daily.empty:
        # 日付と科目で集計
        daily_agg = df_expenses_daily.groupby(['日付', '勘定科目(借方)'])['借方金額'].sum().reset_index()
        
        # 積み上げ棒グラフ
        fig_bar = px.bar(
            daily_agg,
            x='日付',
            y='借方金額',
            color='勘定科目(借方)', # 科目ごとに色分け
            title='日別の費用発生状況'
        )
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info('日次の費用データがありません')

# 総勘定元帳を表示する関数
def display_general_ledger(df):
    df_ledger = create_general_ledger(df)
    account_list = sorted(df_ledger['勘定科目'].unique())
    selected_account = st.selectbox('表示する勘定科目を選択', account_list, key='selected_account')

    if selected_account:
        # 表示したい勘定科目のデータを取り出す
        df_target = df_ledger[df_ledger['勘定科目'] == selected_account].copy()
        df_target = df_target.sort_values(['日付', '取引ID'])

        # 表示用の「借方金額」「貸方金額」列を作る
        # (自分自身の金額を、区分に応じて左右に振り分ける)
        df_target['借方金額'] = np.where(df_target['区分'] == '借方', df_target['金額'], 0)
        df_target['貸方金額'] = np.where(df_target['区分'] == '貸方', df_target['金額'], 0)

        # 残高計算 (借方 - 貸方 の累積)
        df_target['累積残高'] = (df_target['借方金額'] - df_target['貸方金額']).cumsum()

        # 「借/貸」列の作成
        # プラスなら借方残高、マイナスなら貸方残高
        df_target['借/貸'] = df_target['累積残高'].apply(
            lambda x: '借' if x > 0 else ('貸' if x < 0 else '-')
        )

        # 表示用残高は絶対値にする
        df_target['残高'] = df_target['累積残高'].abs()

        # 表示する列を整理
        display_cols = ['日付', '摘要', '相手勘定科目', '借方金額', '貸方金額', '借/貸', '残高']

        st.dataframe(
            df_target[display_cols].style.format(
                {
                    '日付': '{:%Y-%m-%d}',
                    '借方金額': chr(165) + '{:,.0f}',  # カンマ付き、小数点なし
                    '貸方金額': chr(165) + '{:,.0f}',
                    '残高': chr(165) + '{:,.0f}'
                }
            ),
            hide_index=True
        )

# 決算書を表示する関数
def display_finalcial_statements(df):
    # ここで試算表を表示し、戻り値を受け取る
        df_tb = create_trial_balance(df)
        st.divider()
        df_pl, df_bs = create_financial_statements(df_tb)

        st.markdown('### 貸借対照表 (B/S)')

        # 分類ごとの合計を計算
        assets = df_bs[df_bs['分類'] == '資産']['残高'].sum()
        liabilities = df_bs[df_bs['分類'] == '負債']['残高'].sum()
        equity = df_bs[df_bs['分類'] == '純資産']['残高'].sum()

        # 左右（資産 vs 負債+純資産）に分けて表示するためのレイアウト
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown('#### 資産の部')
            st.dataframe(
                df_bs[df_bs['分類'] == '資産'][['勘定科目', '残高']].style.format({'残高': '¥{:,.0f}'}),
                hide_index=True,
                use_container_width=True
            )

        with col2:
            st.markdown('#### 負債・純資産の部')
            # 負債
            st.caption('負債')
            st.dataframe(
                df_bs[df_bs['分類'] == '負債'][['勘定科目', '残高']].style.format({'残高': '¥{:,.0f}'}),
                hide_index=True,
                use_container_width=True
            )
            # 純資産
            st.caption('純資産')
            st.dataframe(
                df_bs[df_bs['分類'] == '純資産'][['勘定科目', '残高']].style.format({'残高': '¥{:,.0f}'}),
                hide_index=True,
                use_container_width=True
            )
        
        # 2段目: 合計金額の表示エリア（ここを分けることで位置が揃います）
        st.divider() # 区切り線を入れるとより見やすいです
        col_bs_total1, col_bs_total2 = st.columns(2)
    
        with col_bs_total1:
            st.metric('資産合計', f'¥{assets:,.0f}')
    
        with col_bs_total2:
            st.metric('負債・純資産合計', f'¥{liabilities + equity:,.0f}')
        
        st.divider()

        st.markdown('### 損益計算書 (P/L)')
    
        # 1. 収益と費用にデータを分ける
        df_revenue = df_pl[df_pl['分類'] == '収益'].copy()
        df_expense = df_pl[df_pl['分類'] == '費用'].copy()

        # 2. 合計を計算
        total_revenue = df_revenue['残高'].sum()
        total_expense = df_expense['残高'].sum()
        net_income = total_revenue - total_expense

        # 3. 左右に並べて表示
        col_pl1, col_pl2 = st.columns(2)

        # 左右を一致させるための「バランス金額（大きい方の金額）」
        matching_total = max(total_revenue, total_expense)

        with col_pl1:
            st.markdown('#### 費用の部 (Expense)')
            st.dataframe(
                df_expense[['勘定科目', '残高']].style.format({'残高': '¥{:,.0f}'}),
                hide_index=True,
                use_container_width=True
            )

        with col_pl2:
            
            st.markdown('#### 収益の部 (Revenue)')
            st.dataframe(
                df_revenue[['勘定科目', '残高']].style.format({'残高': '¥{:,.0f}'}),
                hide_index=True,
                use_container_width=True
            )
        
        # 2段目: 合計金額の表示エリア
        st.divider()
        col_pl_total1, col_pl_total2 = st.columns(2)

        with col_pl_total1:
            # A. まず「費用合計」を表示
            st.metric('費用合計', chr(165) + f'{total_expense:,.0f}')
            
            # B. 黒字（利益）の場合、ここに「当期純利益」を足してバランスさせる
            if net_income >= 0:
                st.metric(
                    label='当期純利益',
                    value=chr(165) + f'{net_income:,.0f}',
                    delta=f'{net_income:,.0f}'
                )
                st.balloons() # (オプション) 黒字なら風船を飛ばす
                st.divider()
                # 最終合計
                st.metric('合計 (費用 + 純利益)', f'¥{matching_total:,.0f}')
            
            # 赤字の場合は、費用合計がそのまま最終合計と一致する
            elif net_income < 0:
                pass
            
        with col_pl_total2:
            # A. まず「収益合計」を表示
            st.metric('収益合計', f'¥{total_revenue:,.0f}')
            
            # B. 赤字（損失）の場合、ここに「当期純損失」を足してバランスさせる
            if net_income < 0:
                loss = abs(net_income)
                st.metric(
                    label='当期純損失', 
                    value=chr(165) + f'{loss:,.0f}',
                    delta=f'{-loss:,.0f}'
                )
                st.divider()
                # 最終合計
                st.metric('合計 (収益 + 純損失)', f'¥{matching_total:,.0f}')
            
            # 黒字の場合は、収益合計がそのまま最終合計と一致する
            elif net_income >= 0:
                # 見た目を揃えるための空行などを入れてもいいですが、ここではシンプルに
                pass
