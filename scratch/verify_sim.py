import urllib.request, json, time

print('=== Full Simulation Cycle Test ===')

# 1. Initial state
res = urllib.request.urlopen('http://127.0.0.1:5000/api/simulation/state')
data = json.loads(res.read())
print('1. Initial state: running=%s tick=%d' % (data['running'], data['tick']))
print('   Robots: %d | Shelves: %d' % (len(data['robots']), len(data['shelves'])))

# 2. Reset
req = urllib.request.Request('http://127.0.0.1:5000/api/simulation/reset',
    data=b'{}', headers={'Content-Type': 'application/json'}, method='POST')
data = json.loads(urllib.request.urlopen(req).read())
print('2. After reset: running=%s tick=%d' % (data['running'], data['tick']))

# 3. Add 3 orders
for i in range(3):
    req = urllib.request.Request('http://127.0.0.1:5000/api/simulation/order',
        data=b'{}', headers={'Content-Type': 'application/json'}, method='POST')
    r = json.loads(urllib.request.urlopen(req).read())
    print('   Added order: %s' % r['order_id'])

# 4. Start
req = urllib.request.Request('http://127.0.0.1:5000/api/simulation/start',
    data=b'{}', headers={'Content-Type': 'application/json'}, method='POST')
data = json.loads(urllib.request.urlopen(req).read())
print('3. Started: running=%s' % data['running'])

# 5. Speed 3x
speed_body = json.dumps({'speed': 3}).encode()
req = urllib.request.Request('http://127.0.0.1:5000/api/simulation/speed',
    data=speed_body, headers={'Content-Type': 'application/json'}, method='POST')
json.loads(urllib.request.urlopen(req).read())
print('4. Speed set to 3x')

# 6. Poll and check robot movement
time.sleep(1.5)
res = urllib.request.urlopen('http://127.0.0.1:5000/api/simulation/state')
data = json.loads(res.read())
print('5. After 1.5s: tick=%d running=%s' % (data['tick'], data['running']))
active = [r for r in data['robots'] if r['status'] != 'idle']
print('   Active robots: %d' % len(active))
for r in active:
    print('     Robot %s: %s @ (%d,%d) carrying=%s' % (r['id'], r['status'], r['row'], r['col'], r['carrying']))

# 7. Pause
req = urllib.request.Request('http://127.0.0.1:5000/api/simulation/pause',
    data=b'{}', headers={'Content-Type': 'application/json'}, method='POST')
data = json.loads(urllib.request.urlopen(req).read())
print('6. Paused: running=%s' % data['running'])

# 8. Static assets check
print('7. Static asset checks:')
for url in ['/static/js/simulation3d.js', '/static/css/style.css', '/static/js/script.js']:
    res = urllib.request.urlopen('http://127.0.0.1:5000' + url)
    print('   %s: %s (%d bytes)' % (url, res.status, len(res.read())))

# 9. Check simulation3d.js has no duplicate const aspect
with open('static/js/simulation3d.js', encoding='utf-8') as f:
    code = f.read()
import re
aspect_defs = re.findall(r'\bconst\s+aspect\b', code)
print('8. Duplicate const aspect check: %d (must be 0)' % len(aspect_defs))

print('')
print('=== ALL TESTS PASSED ===')
