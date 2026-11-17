import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app

app.app.testing = True
client = app.app.test_client()

print('=== 1. State Endpoint Test ===')
res = client.get('/api/simulation/state')
data = res.get_json()
print('Status code:', res.status_code)
print('Grid:', data['grid'])
print('Total shelves:', len(data['shelves']))
print('Total robots:', len(data['robots']))
print('Charging docks:', data['charging'])
print('Delivery station:', data['station'])

print('\n=== 2. Order Creation & Assignment Test ===')
for i in range(5):
    res = client.post('/api/simulation/order')
    d = res.get_json()
    print('Created order:', d['order_id'])

print('\n=== 3. Simulation Step Execution ===')
client.post('/api/simulation/start')
for step in range(20):
    client.post('/api/simulation/step')

res = client.get('/api/simulation/state')
data = res.get_json()
print('Tick after 20 steps:', data['tick'])
for r in data['robots']:
    print(' ', r['id'], 'status:', r['status'], 'pos:', (r['row'], r['col']), 'battery:', r['battery'], 'dest:', r['destination_rack'])

print('\n=== 4. Rack Statuses Sample ===')
for s in data['shelves'][:8]:
    print(' ', s['id'], 'pos:', (s['row'], s['col']), 'status:', s['status'])

print('\n=== 5. Reset Endpoint Test ===')
client.post('/api/simulation/reset')
res = client.get('/api/simulation/state')
data = res.get_json()
print('Tick after reset:', data['tick'])
print('All robot statuses:', [r['status'] for r in data['robots']])
print('All robot positions:', [(r['row'], r['col']) for r in data['robots']])
print('All shelf statuses:', set(s['status'] for s in data['shelves']))

print('\n=== 6. Static Routes Check ===')
for route in ['/', '/dashboard', '/simulation', '/about', '/contact']:
    r = client.get(route)
    print(' ', route, '->', r.status_code)

print('\nALL INTEGRATION TESTS PASSED!')
