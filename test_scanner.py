import requests, json

# Try various possible column names for Taiwan stocks
test_cases = [
    # Basic columns
    ['description'],
    ['description', 'price'],
    ['description', 'market_cap'],
    ['description', 'turnover'],
    ['description', 'beta'],
    ['description', 'volume'],
    # Potential columns for Taiwan
    ['description', 'price', 'market_cap_quote'],  # market_cap_quote might be the full name
    ['description', 'turnover_1d'],  # daily turnover
    ['description', 'sma_200'],  # 200-day SMA
    ['description', 'beta_1y'],  # 1-year beta
    ['description', 'pe_ratio'],  # P/E ratio
    ['description', 'pb_ratio'],  # P/B ratio
]

for columns in test_cases:
    print(f"\nTrying columns: {columns}")
    try:
        r = requests.post('https://scanner.tradingview.com/taiwan/scan', 
            json={'columns': columns, 'limit': 2, 'sort_by': 'market_cap', 'sort_order': 'desc'}, 
            timeout=10)
        if r.status_code == 200:
            data = r.json().get('data', [])
            if data:
                print(f"  Success! First item symbol: {data[0]['s']}")
                print(f"  d array: {data[0]['d']}")
                # Show column values - d[0] should be symbol name if description is first
                for i, col in enumerate(columns):
                    if i < len(data[0]['d']):
                        val = data[0]['d'][i]
                        print(f"    {col}: {val} (type: {type(val).__name__})")
                # Also print without filtering
                print(f"  Full d: {data[0]['d']}")
                break
        else:
            print(f"  HTTP {r.status_code}: {r.text[:150]}")
    except Exception as e:
        print(f"  Error: {e}")