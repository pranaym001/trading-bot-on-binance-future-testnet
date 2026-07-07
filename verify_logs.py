import json

with open('logs/trading_bot.log', encoding='utf-8') as f:
    lines = [json.loads(l) for l in f if l.strip()]

print(f'Total log entries: {len(lines)}')
print()
print('=== ORDER EVENTS ===')
for l in lines:
    if l.get('event', '').startswith('order'):
        ev  = l['event']
        msg = l['msg'][:70]
        lvl = l['level']
        print(f'  [{lvl}] {ev:25s} | {msg}')

print()
print('=== ERROR / WARNING ===')
for l in lines:
    if l['level'] in ('ERROR', 'WARNING'):
        print(f'  [{l["level"]}] {l["msg"][:80]}')

print()
print('=== orders.log ===')
with open('logs/orders.log', encoding='utf-8') as f:
    orders = [json.loads(l) for l in f if l.strip()]
print(f'Total order log entries: {len(orders)}')
for l in orders:
    print(f'  {l["ts"]}  {l["event"]:25s}  order_id={l.get("order_id","n/a")}')
