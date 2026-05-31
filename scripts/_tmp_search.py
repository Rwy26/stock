import yfinance as yf

for query in ['Furiosa AI Korea', 'Rebellions Korea chip', 'Upstage Korea AI', '퓨리오사', '리벨리온', '업스테이지']:
    try:
        results = yf.Search(query, max_results=5)
        quotes = results.quotes
        print(f'\n[{query}]')
        for q in quotes[:5]:
            sym = q.get('symbol', '')
            name = q.get('shortname', q.get('longname', ''))
            exch = q.get('exchange', '')
            print(f'  {sym}  {name}  {exch}')
    except Exception as e:
        print(f'{query}: {e}')
