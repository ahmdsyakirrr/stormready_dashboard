"""Independent pond alerts and evidence-based, operator-started refill checks."""
import json
import math
import statistics


def configure(settings):
    defaults = {
        'pond_high_water_mm': round(settings['downstream_max_mm'] * .75, 2),
        'pond_high_water_clear_mm': round(settings['downstream_max_mm'] * .625, 2),
        'pond_high_water_hold_seconds': 5,
        'refill_start_mm': 20, 'refill_target_mm': 40,
        'refill_pond_start_mm': min(45, settings.get('pond_high_water_clear_mm', settings['downstream_max_mm']*.625)-5),
        'refill_start_tolerance_mm': 5, 'refill_timeout_seconds': 30,
        'refill_slow_factor': 1.5,
    }
    for key, value in defaults.items():
        settings.setdefault(key, value)
    for key in defaults:
        value = settings[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'config.json: {key} must be positive and finite')
    if not 0 < settings['pond_high_water_clear_mm'] < settings['pond_high_water_mm'] < settings['downstream_max_mm']:
        raise ValueError('Pond clear level < pond high-water level < pond maximum is required')
    if settings['refill_slow_factor'] <= 1:
        raise ValueError('refill_slow_factor must be greater than 1')
    return settings


def setup(connection):
    connection.executescript('''
        CREATE TABLE IF NOT EXISTS pond_monitor_state (
            id INTEGER PRIMARY KEY CHECK(id=1), profile_key TEXT NOT NULL,
            boot_id TEXT NOT NULL, previous_sampled_at REAL NOT NULL,
            high_since REAL, active INTEGER NOT NULL, last_confirmed_at REAL
        );
        CREATE TABLE IF NOT EXISTS refill_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, profile_key TEXT NOT NULL,
            phase TEXT NOT NULL, status TEXT NOT NULL, started_at REAL NOT NULL,
            finished_at REAL, boot_id TEXT NOT NULL, last_sampled_at REAL NOT NULL,
            start_up REAL NOT NULL, start_pond REAL NOT NULL, end_up REAL, end_pond REAL,
            elapsed REAL, baseline_seconds REAL, reason TEXT NOT NULL, target_hits INTEGER NOT NULL DEFAULT 0
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_refill_running ON refill_runs(status) WHERE status='running';
    ''')


def update_pond(connection, reading, sampled_at, settings, profile):
    state = connection.execute('SELECT * FROM pond_monitor_state WHERE id=1').fetchone()
    same = state is not None and state['profile_key'] == profile
    continuous = same and state['boot_id'] == reading['boot_id'] and 0 <= sampled_at - state['previous_sampled_at'] <= settings['max_gap_seconds']
    since = state['high_since'] if continuous else None
    # Keep a confirmed episode until a fresh valid sample clears it, even
    # across a sensor fault, communication gap or device restart.
    active = bool(state['active']) if same else False
    confirmed = state['last_confirmed_at'] if same else None
    if reading['downstream_quality'] != 'good':
        since = None
    elif reading['downstream_mm'] >= settings['pond_high_water_mm']:
        since = sampled_at if since is None else since
        if sampled_at - since >= settings['pond_high_water_hold_seconds']:
            active, confirmed = True, sampled_at
    elif reading['downstream_mm'] < settings['pond_high_water_clear_mm']:
        since, active = None, False
    else:
        since = None
    connection.execute('INSERT OR REPLACE INTO pond_monitor_state VALUES (1,?,?,?,?,?,?)', (profile, reading['boot_id'], sampled_at, since, int(active), confirmed))


def pond_status(connection, latest, connection_state, settings, profile):
    state = connection.execute('SELECT * FROM pond_monitor_state WHERE id=1').fetchone()
    matches = state is not None and state['profile_key'] == profile
    if latest is None or connection_state != 'online' or latest['downstream_quality'] != 'good' or not matches:
        water = 'unknown'
    elif state['active']:
        water = 'high_water'
    elif latest['downstream_mm'] >= settings['pond_high_water_mm']:
        water = 'confirming'
    else:
        water = 'below_threshold'
    return {'water_state': water, 'confirmation_seconds': round(max(0, latest['sampled_at'] - state['high_since']), 1) if latest and matches and state['high_since'] is not None else 0, 'last_confirmed_high_at': state['last_confirmed_at'] if matches else None}


def baseline(connection, profile):
    rows = connection.execute("SELECT elapsed FROM refill_runs WHERE profile_key=? AND phase='baseline' AND status='completed' ORDER BY id DESC LIMIT 3", (profile,)).fetchall()
    values = [row['elapsed'] for row in rows]
    return values, statistics.median(values) if len(values) == 3 else None


def finish(connection, run, status, reason, now, reading=None):
    connection.execute('UPDATE refill_runs SET status=?, reason=?, finished_at=?, elapsed=?, end_up=?, end_pond=? WHERE id=? AND status=\'running\'', (status, reason, now, max(0, now-run['started_at']), reading['upstream_mm'] if reading else None, reading['downstream_mm'] if reading else None, run['id']))


def tick_refill(connection, reading, now, settings, profile):
    run = connection.execute("SELECT * FROM refill_runs WHERE status='running'").fetchone()
    if not run:
        return
    if run['profile_key'] != profile:
        finish(connection, run, 'inconclusive', 'Operating profile changed. STOP the manual pump and repeat under the same conditions.', now)
        return
    if reading is None or now-reading['received_at'] > settings['max_gap_seconds']:
        finish(connection, run, 'inconclusive', 'Fresh data lost. STOP the manual pump. This is not evidence of pump failure.', now)
        return
    if reading['upstream_quality'] != 'good' or reading['downstream_quality'] != 'good' or reading['boot_id'] != run['boot_id'] or reading['sampled_at'] - run['last_sampled_at'] > settings['max_gap_seconds']:
        finish(connection, run, 'inconclusive', 'Sensor quality, continuity or device boot changed. STOP the manual pump; inspect readings before retesting.', now, reading)
        return
    up, pond = reading['upstream_mm'], reading['downstream_mm']
    if up >= settings['upstream_max_mm']-10 or pond <= 15:
        finish(connection, run, 'inconclusive', 'Test guard reached. STOP the manual pump; keep water below maximum and the pump fully submerged.', now, reading)
        return
    elapsed = now-run['started_at']
    if pond > run['start_pond']+10:
        finish(connection, run, 'inconclusive', 'Pond rose during a declared isolated refill. STOP pump and inspect inflow, drain isolation and sensor mounting.', now, reading)
        return
    if elapsed > settings['refill_timeout_seconds']:
        finish(connection, run, 'unusual' if run['phase']=='check' else 'inconclusive', 'Refill target was not reached before the test time limit. STOP the manual pump; inspect pump, power, tubing and test conditions.', now, reading)
        return
    if reading['sampled_at'] > run['last_sampled_at']:
        hits = run['target_hits']+1 if up >= settings['refill_target_mm'] else 0
        connection.execute('UPDATE refill_runs SET target_hits=?, last_sampled_at=? WHERE id=?', (hits, reading['sampled_at'], run['id']))
        if hits >= 2:
            unusual = run['phase']=='check' and elapsed > run['baseline_seconds']*settings['refill_slow_factor']
            finish(connection, run, 'unusual' if unusual else 'completed', 'STOP the manual pump now. ' + ('Refill was slower than the comparable baseline; inspect pump, power and tubing.' if unusual else 'Refill target reached. This is level-based test evidence, not confirmation of pump electrical health.'), now, reading)
            return
    if run['phase']=='check' and elapsed > run['baseline_seconds']*settings['refill_slow_factor']:
        finish(connection, run, 'unusual', f"Refill target not reached within {settings['refill_slow_factor']}× the comparable baseline time. STOP the manual pump and inspect pump, power, tubing and conditions.", now, reading)


def start_refill(connection, payload, now, settings, profile):
    if not isinstance(payload, dict) or payload.get('phase') not in ('baseline','check') or payload.get('conditions_confirmed') is not True:
        raise ValueError('Choose baseline/check and confirm drain closed, no other inflow, pump submerged and manual supervision.')
    if connection.execute("SELECT 1 FROM refill_runs WHERE status='running'").fetchone():
        raise ValueError('A refill test is already running.')
    latest = connection.execute('SELECT * FROM readings ORDER BY id DESC LIMIT 1').fetchone()
    if not latest or now-latest['received_at'] > settings['max_gap_seconds'] or latest['upstream_quality']!='good' or latest['downstream_quality']!='good':
        raise ValueError('Both sensors must have fresh valid readings before starting.')
    if not settings['refill_start_mm']+2*settings['refill_start_tolerance_mm'] < settings['refill_target_mm'] < settings['upstream_max_mm']-10:
        raise ValueError('Refill test marks do not fit safely within the configured upstream depth.')
    if abs(latest['upstream_mm']-settings['refill_start_mm']) > settings['refill_start_tolerance_mm'] or abs(latest['downstream_mm']-settings['refill_pond_start_mm']) > settings['refill_start_tolerance_mm']:
        raise ValueError(f"Start near upstream {settings['refill_start_mm']} mm and pond {settings['refill_pond_start_mm']} mm (±{settings['refill_start_tolerance_mm']} mm).")
    values, seconds = baseline(connection, profile)
    if payload['phase']=='check' and seconds is None:
        raise ValueError('Save three successful baseline trials under the same setup before checking performance.')
    if seconds is not None and max(values)-min(values) > .5*seconds:
        if payload['phase']=='check':
            raise ValueError('Baseline trials vary too much. Record three consistent baseline trials first.')
    cursor = connection.execute("INSERT INTO refill_runs (profile_key,phase,status,started_at,boot_id,last_sampled_at,start_up,start_pond,baseline_seconds,reason) VALUES (?,?,'running',?,?,?,?,?,?,?)", (profile,payload['phase'],now,latest['boot_id'],latest['sampled_at'],latest['upstream_mm'],latest['downstream_mm'],seconds,'Operator declared pump ON; not electrically verified. Supervise and stop pump at completion.'))
    return cursor.lastrowid


def refill_snapshot(connection, now, settings, profile):
    latest = connection.execute('SELECT * FROM readings ORDER BY id DESC LIMIT 1').fetchone()
    tick_refill(connection, latest, now, settings, profile)
    connection.commit()
    values, seconds = baseline(connection, profile)
    rows = [dict(row) for row in connection.execute('SELECT * FROM refill_runs ORDER BY id DESC LIMIT 10')]
    for row in rows:
        row.pop('profile_key',None)
    return {'runs':rows,'baseline_count':len(values),'baseline_seconds':seconds,'baseline_consistent': bool(seconds is not None and max(values)-min(values)<=.5*seconds),'settings':{k:settings[k] for k in ('refill_start_mm','refill_target_mm','refill_pond_start_mm','refill_start_tolerance_mm','refill_timeout_seconds','refill_slow_factor')}}
