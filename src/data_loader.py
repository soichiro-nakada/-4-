import pandas as pd
from .constants import ACCOUNT_TYPE_MAP, TYPE_ORDER, DYNAMIC_ACCOUNTS



# Step. 1 データを読み込む。(事前に仕訳帳のフォーマットでデータを用意する)
def read_data(filename):
    df_journal = pd.read_excel(filename)

    df_journal['日付'] = pd.to_datetime(
        df_journal['日付'], 
        unit='D', 
        origin='1899-12-30', 
        errors='coerce' 
    )

    # Step 2. 読み込んだDataFrameを取引ごとにIDを振る（仕訳毎に分ける）
    df_journal = _add_trans_id(df_journal)

    return df_journal

# Step. 2 読み込んだDataFrameを取引ごとにIDを振る（仕訳毎に分ける）
def _add_trans_id(df_journal):
    # 1. 「新しい取引の開始行」を見つける
    #    ルール: 「日付」が入っている OR 「摘要」が入っている行は、新しい取引の先頭とみなす
    #    (notna() は「空欄ではない」という意味です)
    is_new_transaction = df_journal['日付'].notna() | df_journal['摘要'].notna()

    # 2. 開始行にフラグ(1)を立てて、累積和(cumsum)をとることでIDを作る
    #    例: [1, 0, 0, 1, 0] -> cumsum -> [1, 1, 1, 2, 2]
    df_journal['取引ID'] = is_new_transaction.astype(int).cumsum()

    return df_journal

# Step. 3 総勘定元帳を作成する。
def create_general_ledger(df_journal):
    # 0. 日付、摘要欄を加工
    df_journal_ffill = df_journal.copy()
    df_journal_ffill['日付'] = df_journal_ffill['日付'].ffill()
    df_journal_ffill['摘要'] = df_journal_ffill['摘要'].ffill()

    # 1. 仕訳帳から元帳（横型→縦型)へ変換
    df_ledger = make_ledger_data(df_journal_ffill)

    # 2. 取引IDごとに、借方・貸方にどんな科目があるか辞書を作る
    debit_map = df_ledger[df_ledger['区分'] == '借方'].groupby('取引ID')['勘定科目'].apply(list).to_dict()
    credit_map = df_ledger[df_ledger['区分'] == '貸方'].groupby('取引ID')['勘定科目'].apply(list).to_dict()

    # 3. 相手勘定科目を取り出すメソッド
    def get_partner(row):
        tid = row['取引ID']
        side = row['区分']
        partners = []
        
        # 自分が借方なら、貸方の科目が相手
        if side == '借方':
            partners = credit_map.get(tid, [])
        # 自分が貸方なら、借方の科目が相手
        else:
            partners = debit_map.get(tid, [])
            
        if len(partners) == 0:
            return '-'
        elif len(partners) == 1:
            return partners[0]
        else:
            return '諸口' # 相手が複数ある場合は「諸口」
    # 4. 相手勘定科目を追加
    df_ledger['相手勘定科目'] = df_ledger.apply(get_partner, axis=1)

    return df_ledger

# 仕訳帳から元帳（横型→縦型)へ変換 
def make_ledger_data(df):
    '''仕訳帳(横持ち)を元帳データ(縦持ち)に変換する関数'''
    
    # 1. 借方側のデータを抽出
    df_debit = df[['日付', '取引ID', '摘要', '勘定科目(借方)', '借方金額']].copy()
    df_debit.columns = ['日付', '取引ID', '摘要', '勘定科目', '金額']
    df_debit['区分'] = '借方'
    
    # 2. 貸方側のデータを抽出
    df_credit = df[['日付', '取引ID', '摘要', '勘定科目(貸方)', '貸方金額']].copy()
    df_credit.columns = ['日付', '取引ID', '摘要', '勘定科目', '金額']
    df_credit['区分'] = '貸方'
    
    # 3. 結合して、科目が入っていない行（相手側だけの行）を削除
    df_ledger = pd.concat([df_debit, df_credit], ignore_index=True)
    df_ledger = df_ledger.dropna(subset=['勘定科目'])
    
    return df_ledger

# Step 4. 試算表を作成する
def create_trial_balance(df):
    # 0. 中間の決算を消す。
    df_normalized = remove_intermediate_carry_forwards(df)

    # 1. 元帳のデータを作成
    df_ledger = make_ledger_data(df_normalized)

    # 2. 科目ごとに借方合計・貸方合計を集計
    tb = df_ledger.pivot_table(
        index='勘定科目', 
        columns='区分', 
        values='金額', 
        aggfunc='sum', 
        fill_value=0
    )

    # カラムが存在しない場合のケア（借方しかない、貸方しかないデータへの対応）
    if '借方' not in tb.columns: tb['借方'] = 0
    if '貸方' not in tb.columns: tb['貸方'] = 0

    # 3. マスタデータを結合して「分類」をつける
    #    mapを使って辞書から分類を引き当てます
    tb['分類'] = tb.index.map(ACCOUNT_TYPE_MAP)

    # マスタにない科目は「不明」とする
    tb['分類'] = tb['分類'].fillna('不明')

    # 4. 残高の計算
    tb['差引'] = tb['借方'] - tb['貸方']

    # 現金過不足など、収益・費用が確定していない項目の分類分け
    _tb_dynamic_account_type(tb)

    # 借方残高なのか貸方残高なのか判定
    tb['借/貸'] = tb['差引'].apply(
        lambda x: '借' if x > 0 else ('貸' if x < 0 else '-')
    )

    tb['残高'] = tb['差引'].abs()

    # 並び替え
    tb['SortKey'] = tb['分類'].map(TYPE_ORDER)
    
    # マスタにない分類（'不明'など）は一番後ろ(99)にする
    tb['SortKey'] = tb['SortKey'].fillna(99)
    
    # B. SortKey(分類順) -> 勘定科目(あいうえお順) の優先度で並び替える
    tb = tb.sort_values(by=['SortKey', '勘定科目'])

    return tb

# 現金過不足等、費用・収益の分類が不明の科目を判定
def _tb_dynamic_account_type(tb):
    for account in DYNAMIC_ACCOUNTS:
        if account in tb.index:
            balance = tb.at[account, '差引']
            if balance > 0:
                tb.at[account, '分類'] = '費用'  # 損
            elif balance < 0:
                tb.at[account, '分類'] = '収益'  # 益

# Step 5. 決算書(B/S、P/L)を作成する
def create_financial_statements(tb):
    # 1. 必要な列だけ抽出して整理
    #    試算表(tb)には '借方', '貸方', '差引', '残高' などがありますが、
    #    ここからは '残高'(絶対値) と '分類' さえあればOKです。
    #    ただし、計算用に '差引'(プラスマイナス付き) も使います。
    
    df_clean = tb.reset_index()[['分類', '勘定科目', '残高', '差引', 'SortKey']].copy()

    # 2. 損益計算書(P/L)の作成
    # 収益と費用のみ抽出
    df_pl = df_clean[df_clean['分類'].isin(['収益', '費用'])].copy()
    
    # 利益の計算 (収益合計 - 費用合計)
    total_revenue = df_pl[df_pl['分類'] == '収益']['残高'].sum()
    total_expense = df_pl[df_pl['分類'] == '費用']['残高'].sum()
    pl_net_balance = df_pl['差引'].sum()
    net_income = -pl_net_balance

    # 3. 貸借対照表(B/S)の作成
    # 資産、負債、純資産のみ抽出
    df_bs = df_clean[df_clean['分類'].isin(['資産', '負債', '純資産'])].copy()

    # 当期純利益を「繰越利益剰余金」に合算する処理
    target_account = '繰越利益剰余金'
    
    # 繰越利益剰余金がすでにあるか確認
    mask = df_bs['勘定科目'] == target_account
    
    if mask.any():
        # ある場合: その行の「差引」に、P/Lのバランス（pl_net_balance）を足し込む
        # ※ pl_net_balanceは利益ならマイナス（貸方）なので、そのまま足せば貸方が増えます
        df_bs.loc[mask, '差引'] += pl_net_balance
    else:
        # ない場合: 新しく行を作成して追加
        new_row = pd.DataFrame({
            '分類': ['純資産'],
            '勘定科目': [target_account],
            '差引': [pl_net_balance], # 利益ならマイナスが入る
            'SortKey': [3]
        })
        # concatで結合（concatは空のDataFrameを除外して結合するのでwarning対策になります）
        if not new_row.empty:
             df_bs = pd.concat([df_bs, new_row], ignore_index=True)
    
    df_bs['残高'] = df_bs['差引'].abs()
    
    # 分類ごとの合計を計算
    assets = df_bs[df_bs['分類'] == '資産']['残高'].sum()
    liabilities = df_bs[df_bs['分類'] == '負債']['残高'].sum()
    equity = df_bs[df_bs['分類'] == '純資産']['残高'].sum()
    
    # 並び替え
    df_bs = df_bs.sort_values(by=['SortKey', '勘定科目'])

    return df_pl, df_bs

# 取引IDを参照することで、期間内の仕訳表を抜き出す
def extract_period_data(df, start_date, end_date):
    '''
    指定期間に含まれる取引を、複合仕訳(日付なし行)も含めて丸ごと抽出する
    '''
    # 1. 判定用に一時的に日付を埋めたシリーズを作る（元のdfは汚さない）
    temp_dates = df['日付'].ffill()
    
    # 2. 期間内に該当する行を探す
    mask_in_period = (temp_dates >= start_date) & (temp_dates <= end_date)
    
    # 3. 期間内に登場した「取引ID」をリストアップする
    #    (該当する行にあるIDを重複なしで取得)
    target_ids = df.loc[mask_in_period, '取引ID'].unique()
    
    # 4. そのIDを持つ行をすべて抽出する
    #    (これで、日付が空欄の行も ID が一致するので抽出されます)
    df_period = df[df['取引ID'].isin(target_ids)].copy()
    
    return df_period

# 「データ内の最初の日付以外にある繰越仕訳」 を削除して返す関数
def remove_intermediate_carry_forwards(df):
    '''
    複数の会計期間を含むデータから、途中の繰越仕訳（開始残高など）を除去し、
    一つの連続した会計期間のデータのように加工する。
    '''
    df_clean = df.copy()

    # 日付、摘要の欄を埋める
    df_clean['日付'] = df_clean['日付'].ffill()
    df_clean['摘要'] = df_clean['摘要'].ffill()

    # 開始日付の洗濯
    start_date = df_clean['日付'].min()
    # 2. 除去対象とするキーワード
    keywords = ['開始残高', '前年繰越', '前月繰越', '前期繰越', '繰越']
    pattern = '|'.join(keywords)

    # 3. フィルタリング条件の作成
    # 条件A: 摘要にキーワードが含まれている
    mask_keyword = df_clean['摘要'].astype(str).str.contains(pattern, na=False)

    # 条件B: 日付が「真の開始日」より後である
    mask_after_start = df_clean['日付'] > start_date

    # 削除対象 = 条件A かつ 条件B
    mask_to_drop = mask_keyword & mask_after_start

    # 4. 削除対象以外の行を抽出
    df_result = df_clean[~mask_to_drop].reset_index(drop=True)

    return df_result

# 資産・負債・純資産の日時データを作成する。
def calculate_daily_trends(df):
    '''
    資産・負債・純資産の日次推移データを計算する
    (会計期間をまたぐ際の二重計上を防ぐロジック入り)
    '''
    # 日付、摘要の空欄は埋めておく
    df_copy = df.copy()
    df_copy['日付'] = df_copy['日付'].ffill()
    df_copy['摘要'] = df_copy['摘要'].ffill()

    # 1. データのクリーニング（中間繰越の除去）
    df_clean = remove_intermediate_carry_forwards(df_copy)

    # 2. 縦持ちデータへの変換 (全期間)
    df_ledger = make_ledger_data(df_clean)

    # 3. 分類を付与
    df_ledger['分類'] = df_ledger['勘定科目'].map(ACCOUNT_TYPE_MAP).fillna('不明')

    # 4. 資産・負債データのみ抽出
    df_bs_items = df_ledger[df_ledger['分類'].isin(['資産', '負債'])].copy()

    # 5. 金額の符号調整
    #    資産はプラス、負債はマイナスとして扱う
    #    借方(区分=借方)にある資産はプラス、貸方にある資産はマイナス
    #    貸方(区分=貸方)にある負債はマイナス、借方にある負債はプラス(返済)
    
    def calculate_amount(row):
        amt = row['金額']
        kind = row['分類']
        side = row['区分']
        
        if kind == '資産':
            # 資産は 借方がプラス、貸方がマイナス
            return amt if side == '借方' else -amt
        elif kind == '負債':
            # 負債は 貸方がプラス(借金増)、借方がマイナス(返済)として扱い
            # グラフ表示用に「負債残高」というプラスの値にする
            return amt if side == '貸方' else -amt
        return 0

    df_bs_items['変動額'] = df_bs_items.apply(calculate_amount, axis=1)

    # 6. ピボットテーブルで「資産」と「負債」の日次変動を集計
    #    columns='分類' にすることで、資産列と負債列に分かれます
    daily_changes = df_bs_items.pivot_table(
        index='日付', 
        columns='分類', 
        values='変動額', 
        aggfunc='sum', 
        fill_value=0
    )

    # 列が存在しない場合のケア
    if '資産' not in daily_changes.columns: daily_changes['資産'] = 0
    if '負債' not in daily_changes.columns: daily_changes['負債'] = 0

    # 7. 累積和 (Cumsum) で残高にする
    daily_balances = daily_changes.cumsum()
    
    # 8. 純資産列を追加 (資産 - 負債)
    daily_balances['純資産'] = daily_balances['資産'] - daily_balances['負債']
    
    # 整形して返す
    return daily_balances.reset_index()

# New!! 月ごとのキャッシュフローを計算する。
def calculate_monthly_cashflow(df):
    # 1. 日付、摘要の空欄は埋めておく
    df_copy = df.copy()
    df_copy['日付'] = df_copy['日付'].ffill()
    df_copy['摘要'] = df_copy['摘要'].ffill()
    
    # 2. 必要なデータ（収益・費用）のみ抽出
    #    make_ledger_dataを使わずに元データから集計します（処理を軽くするため）
    #    ただし、分類が必要なのでマッピングします
    
    # 借方・貸方の科目に分類をマッピング
    df_copy['借方分類'] = df_copy['勘定科目(借方)'].map(ACCOUNT_TYPE_MAP).fillna('不明')
    df_copy['貸方分類'] = df_copy['勘定科目(貸方)'].map(ACCOUNT_TYPE_MAP).fillna('不明')

    # 月カラム作成
    df_copy['月'] = df_copy['日付'].dt.strftime('%Y-%m')

    # 3. 集計
    # --- 集計ロジック ---
    # 収入 (Income): 
    # 3-1 収益の発生
    income_credit = df_copy[df_copy['貸方分類'] == '収益'].groupby('月')['貸方金額'].sum()
    # 3-2 収益の取消
    income_debit  = df_copy[df_copy['借方分類'] == '収益'].groupby('月')['借方金額'].sum()

    # 3-3. 収益合計 = 貸方 - 借方
    net_income = income_credit.sub(income_debit, fill_value=0)

    # 支出 (Expense): 
    # 3-4 費用の発生
    expense_debit = df_copy[df_copy['借方分類'] == '費用'].groupby('月')['借方金額'].sum()
    # 3-5 費用の取消
    expense_credit = df_copy[df_copy['貸方分類'] == '費用'].groupby('月')['貸方金額'].sum()

    #3-6.  費用合計 = 借方 - 貸方
    net_expense = expense_debit.sub(expense_credit, fill_value=0)

    # 4. データ統合
    df_cf = pd.DataFrame({
        '収入': net_income,
        '支出': net_expense
    }).fillna(0)

    # 5. 収支 (Net Cash Flow) = 収入 - 支出
    df_cf['収支'] = df_cf['収入'] - df_cf['支出']
    
    # index(月)を列に戻す
    df_cf = df_cf.reset_index()

    # 6. 年間累積収支の計算 ---
    # '月' (YYYY-MM) から '年' (YYYY) を抽出
    df_cf['年'] = df_cf['月'].str[:4]
    
    # 年ごとにグループ化して、収支を累積和 (cumsum) する
    df_cf['年間累積収支'] = df_cf.groupby('年')['収支'].cumsum()
    
    # 月順にソート（念のため）
    df_cf = df_cf.sort_values('月')

    return df_cf
