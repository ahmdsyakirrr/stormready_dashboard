"""Persistent incident workflow and controlled before/after depth evidence.

Depth change is an observation, not a flow meter or proof of pump electrical health.
All workflow mutations use authenticated accounts and short SQLite transactions.
"""
import csv
import functools
import hashlib
import io
import json
import math
import secrets
import statistics
from urllib.parse import urlsplit

from flask import Response, jsonify, render_template, request
from werkzeug.security import check_password_hash, generate_password_hash

SENSORS = ('upstream', 'downstream')
DURATION = 15
START_TOLERANCE = 5
MIN_IMPROVEMENT = 5
SESSION_SECONDS = 8 * 60 * 60
COOKIE = 'stormready_workflow_session'


class WorkflowError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def text_value(payload, key, minimum=1, maximum=1000):
    value = payload.get(key)
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum or '\x00' in value:
        raise WorkflowError(f'{key.replace("_", " ").capitalize()} must contain {minimum}–{maximum} characters.')
    return value.strip()


def audit(db, incident_id, actor, action, detail, now, cycle=1):
    db.execute('INSERT INTO incident_events(incident_id,cycle,actor,action,detail,created_at) VALUES(?,?,?,?,?,?)',
               (incident_id, cycle, actor, action, json.dumps(detail), now))


def setup(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS workflow_users (
            id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('operator','supervisor')),
            password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workflow_sessions (
            token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workflow_login_attempts(ip TEXT NOT NULL, tried_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS workflow_cursor(id INTEGER PRIMARY KEY CHECK(id=1),reading_id INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS workflow_alert_state (
            profile_key TEXT NOT NULL, sensor TEXT NOT NULL,
            boot_id TEXT, sampled_at REAL, high_since REAL, active INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(profile_key,sensor)
        );
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id TEXT NOT NULL, profile_key TEXT NOT NULL,
            location TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', cycle INTEGER NOT NULL DEFAULT 1,
            detected_at REAL NOT NULL, detected_reading_id INTEGER NOT NULL,
            detected_level REAL NOT NULL, threshold REAL NOT NULL, clear_threshold REAL NOT NULL,
            assigned_to INTEGER, closed_at REAL, version INTEGER NOT NULL DEFAULT 1
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_open_incident_per_location
            ON incidents(profile_key,location) WHERE status != 'closed';
        CREATE TABLE IF NOT EXISTS incident_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id INTEGER NOT NULL,
            cycle INTEGER NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
            detail TEXT NOT NULL, created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS incident_inspections (
            id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id INTEGER NOT NULL,
            cycle INTEGER NOT NULL, operator_id INTEGER NOT NULL, findings TEXT NOT NULL,
            work_done TEXT NOT NULL, created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS incident_trials (
            id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id INTEGER NOT NULL,
            cycle INTEGER NOT NULL, phase TEXT NOT NULL, operator_id INTEGER NOT NULL,
            profile_key TEXT NOT NULL, location TEXT NOT NULL, conditions TEXT NOT NULL,
            status TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL,
            start_reading_id INTEGER NOT NULL, last_reading_id INTEGER NOT NULL,
            boot_id TEXT NOT NULL, last_sampled_at REAL NOT NULL,
            samples TEXT NOT NULL, result TEXT, reason TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_controlled_trial_running
            ON incident_trials(status) WHERE status='running';
    ''')
    # Historical telemetry is retained, without creating a backlog of old incidents.
    db.execute('INSERT OR IGNORE INTO workflow_cursor VALUES(1, (SELECT COALESCE(MAX(id),0) FROM readings))')
    db.commit()


def threshold(settings, sensor):
    return (settings['high_water_mm'], settings['high_water_clear_mm'], settings['high_water_hold_seconds']) if sensor == 'upstream' else (settings['pond_high_water_mm'], settings['pond_high_water_clear_mm'], settings['pond_high_water_hold_seconds'])


def fresh_pair(db, now, settings):
    row = db.execute('SELECT * FROM readings ORDER BY id DESC LIMIT 1').fetchone()
    if not row or now-row['received_at'] > settings['max_gap_seconds'] or now-row['sampled_at'] > settings['max_gap_seconds']:
        raise WorkflowError('Both sensors need fresh readings. Check the ESP32 connection.')
    if any(row[f'{s}_quality'] != 'good' for s in SENSORS):
        raise WorkflowError('Both sensors need valid readings. Unavailable measurements cannot verify recovery.')
    return row


def finish_trial(db, trial, status, reason, now, result=None):
    changed = db.execute("UPDATE incident_trials SET status=?,reason=?,finished_at=?,result=? WHERE id=? AND status='running'",
                        (status, reason, now, json.dumps(result) if result else None, trial['id'])).rowcount
    if changed:
        user = db.execute('SELECT display_name FROM workflow_users WHERE id=?', (trial['operator_id'],)).fetchone()
        audit(db, trial['incident_id'], user['display_name'] if user else 'System', 'evidence_'+status,
              {'trial_id': trial['id'], 'phase': trial['phase'], 'reason': reason, 'result': result}, now, trial['cycle'])


def tick_trial(db, reading, now, settings, profile):
    trial = db.execute("SELECT * FROM incident_trials WHERE status='running'").fetchone()
    if not trial:
        return
    if trial['profile_key'] != profile:
        finish_trial(db, trial, 'inconclusive', 'Operating profile changed. Stop any manual pump and repeat with a new baseline.', now)
        return
    if not reading or now-reading['received_at'] > settings['max_gap_seconds'] or now-reading['sampled_at'] > settings['max_gap_seconds']:
        finish_trial(db, trial, 'inconclusive', 'Fresh data lost. Stop any manual pump. No recovery conclusion is available.', now)
        return
    if reading['id'] <= trial['last_reading_id']:
        return
    if reading['boot_id'] != trial['boot_id'] or any(reading[f'{s}_quality'] != 'good' for s in SENSORS) or not 0 < reading['sampled_at']-trial['last_sampled_at'] <= settings['max_gap_seconds']:
        finish_trial(db, trial, 'inconclusive', 'A sensor fault, data gap or ESP32 restart interrupted the test. Stop any manual pump.', now)
        return
    if any(reading[f'{s}_mm'] >= settings[f'{s}_max_mm']-5 for s in SENSORS) or (trial['location']=='downstream' and reading['downstream_mm']<=20):
        finish_trial(db, trial, 'inconclusive', 'A test depth guard was reached. Stop any manual pump and inspect the model.', now)
        return
    samples = json.loads(trial['samples'])
    samples.append({k: reading[k] for k in ('id','sampled_at','upstream_mm','downstream_mm')})
    db.execute('UPDATE incident_trials SET samples=?,last_reading_id=?,last_sampled_at=? WHERE id=?',
               (json.dumps(samples),reading['id'],reading['sampled_at'],trial['id']))
    span = samples[-1]['sampled_at']-samples[0]['sampled_at']
    if span < DURATION:
        return
    required = max(5, math.ceil(DURATION/settings['expected_interval_seconds']*.8))
    if len(samples) < required:
        finish_trial(db, trial, 'inconclusive', 'Too few fresh samples for this comparison. Stop any manual pump.', now)
        return
    key = trial['location']+'_mm'
    first, last = samples[:3], samples[-3:]
    start = statistics.median(x[key] for x in first)
    end = statistics.median(x[key] for x in last)
    elapsed = statistics.mean(x['sampled_at'] for x in last)-statistics.mean(x['sampled_at'] for x in first)
    result = {'samples':len(samples),'span_seconds':round(span,3),'start_mm':start,'end_mm':end,
              'drop_mm':round(start-end,3),'rate_mm_per_minute':round((start-end)/elapsed*60,3),
              'start_upstream_mm':samples[0]['upstream_mm'],'start_downstream_mm':samples[0]['downstream_mm']}
    finish_trial(db, trial, 'completed', 'Capture complete. Stop any manual pump. Review the evidence before drawing a conclusion.', now, result)


def sync(db, now, settings, profile):
    cursor = db.execute('SELECT reading_id FROM workflow_cursor WHERE id=1').fetchone()['reading_id']
    rows = db.execute('SELECT * FROM readings WHERE id>? ORDER BY id', (cursor,)).fetchall()
    for row in rows:
        for sensor in SENSORS:
            state = db.execute('SELECT * FROM workflow_alert_state WHERE profile_key=? AND sensor=?', (profile,sensor)).fetchone()
            continuous = state and state['boot_id']==row['boot_id'] and 0 < row['sampled_at']-state['sampled_at'] <= settings['max_gap_seconds']
            since = state['high_since'] if continuous else None
            active = bool(state['active']) if state else False
            high, clear, hold = threshold(settings,sensor)
            if row[sensor+'_quality'] != 'good':
                since = None
            elif row[sensor+'_mm'] < clear:
                since, active = None, False
            elif row[sensor+'_mm'] >= high:
                since = row['sampled_at'] if since is None else since
                if row['sampled_at']-since >= hold:
                    active = True
                    existing = db.execute("SELECT id FROM incidents WHERE profile_key=? AND location=? AND status!='closed'", (profile,sensor)).fetchone()
                    if not existing:
                        result = db.execute('INSERT INTO incidents(asset_id,profile_key,location,detected_at,detected_reading_id,detected_level,threshold,clear_threshold) VALUES(?,?,?,?,?,?,?,?)',
                                            (settings['asset_id'],profile,sensor,row['received_at'],row['id'],row[sensor+'_mm'],high,clear))
                        audit(db,result.lastrowid,'Sensor monitor','detected',{'reading_id':row['id'],'level_mm':row[sensor+'_mm'],'threshold_mm':high},row['received_at'])
            else:
                since = None
            db.execute('INSERT OR REPLACE INTO workflow_alert_state VALUES(?,?,?,?,?,?)', (profile,sensor,row['boot_id'],row['sampled_at'],since,int(active)))
        tick_trial(db,row,row['received_at'],settings,profile)
        cursor = row['id']
    if rows:
        db.execute('UPDATE workflow_cursor SET reading_id=? WHERE id=1',(cursor,))
    latest = db.execute('SELECT * FROM readings ORDER BY id DESC LIMIT 1').fetchone()
    tick_trial(db,latest,now,settings,profile)


def comparison(db, incident, profile):
    empty = {'outcome':'inconclusive','reason':'Capture a before test, record maintenance, then capture an after test under matching conditions.', 'before':None,'after':None}
    trials = db.execute("SELECT * FROM incident_trials WHERE incident_id=? AND cycle=? AND status='completed' ORDER BY id DESC", (incident['id'],incident['cycle'])).fetchall()
    before = next((r for r in trials if r['phase']=='before'),None)
    after = next((r for r in trials if r['phase']=='after'),None)
    if not before or not after:
        return empty
    first,last = json.loads(before['result']),json.loads(after['result'])
    out = dict(empty,before=dict(id=before['id'],**first),after=dict(id=after['id'],**last))
    inspection = db.execute('SELECT * FROM incident_inspections WHERE incident_id=? AND cycle=? ORDER BY id DESC LIMIT 1',(incident['id'],incident['cycle'])).fetchone()
    if before['profile_key'] != profile or after['profile_key'] != profile or incident['profile_key'] != profile:
        out['reason']='The calibration or operating profile changed. These tests cannot verify the current setup.'
    elif before['conditions'] != after['conditions']:
        out['reason']='Setup labels or declared physical conditions differ. Repeat under matching conditions.'
    elif any(abs(first['start_'+s+'_mm']-last['start_'+s+'_mm']) > START_TOLERANCE for s in SENSORS):
        out['reason']=f'Starting depths differ by more than {START_TOLERANCE} mm. Restore both start marks and repeat the after test.'
    elif not inspection or before['started_at'] >= inspection['created_at'] or after['started_at'] < inspection['created_at']:
        out['reason']='The captures must bracket the latest recorded maintenance work.'
    else:
        # Normalize the rate difference to the fixed 15-second observation period.
        improvement = (last['rate_mm_per_minute']-first['rate_mm_per_minute'])*DURATION/60
        out['improvement_mm_per_15s']=round(improvement,3)
        if improvement >= MIN_IMPROVEMENT and last['drop_mm']>0:
            out.update(outcome='improved',reason=f'Greater observed drawdown under declared matching conditions (at least {MIN_IMPROVEMENT} mm improvement per 15 seconds). Supervisor review is still required.')
        else:
            out.update(outcome='not_improved',reason=f'The observed drawdown did not improve by the {MIN_IMPROVEMENT} mm per 15 seconds demonstration criterion. Keep the case open for inspection or retesting.')
    return out


def safe_to_close(db, incident, now, settings, profile):
    try:
        latest = fresh_pair(db,now,settings)
    except WorkflowError as error:
        return False,str(error)
    if incident['profile_key'] != profile:
        return False,'The incident belongs to a different operating profile.'
    clear = threshold(settings,incident['location'])[1]
    if latest[incident['location']+'_mm'] >= clear:
        return False,f'The affected location must remain below its {clear} mm clearing level for five seconds.'
    rows = db.execute('SELECT * FROM readings WHERE sampled_at>=? ORDER BY id',(latest['sampled_at']-5-settings['expected_interval_seconds'],)).fetchall()
    window=[]
    for row in reversed(rows):
        if row['boot_id']!=latest['boot_id'] or any(row[s+'_quality']!='good' for s in SENSORS) or row[incident['location']+'_mm']>=clear:
            break
        if window and window[-1]['sampled_at']-row['sampled_at']>settings['max_gap_seconds']:
            break
        window.append(row)
        if latest['sampled_at']-row['sampled_at']>=5:
            return True,'Fresh readings confirm the affected location stayed below its clearing level for five seconds.'
    return False,'Collect five seconds of fresh valid readings below the affected clearing level before closure.'


def register(app, database, settings, profile):
    """Called once from create_app; no firmware or telemetry contract changes."""
    with app.app_context():
        setup(database())

    def now():
        return app.config['CLOCK']()

    def user():
        token = request.cookies.get(COOKIE,'')
        if not token:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        return database().execute('SELECT u.id,u.username,u.display_name,u.role FROM workflow_sessions s JOIN workflow_users u ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>?',(digest,now())).fetchone()

    def person(row):
        return {k:row[k] for k in ('id','username','display_name','role')} if row else None

    def endpoint(roles=None, mutate=False, public=False):
        def decorate(fn):
            @functools.wraps(fn)
            def wrapped(*args,**kwargs):
                db=database()
                try:
                    if mutate:
                        if not request.is_json:
                            raise WorkflowError('Use application/json.',415)
                        origin=request.headers.get('Origin')
                        if origin and urlsplit(origin).netloc != request.host:
                            raise WorkflowError('Cross-origin workflow changes are not allowed.',403)
                    actor=user()
                    if not public and not actor:
                        raise WorkflowError('Sign in to the incident workspace.',401)
                    if roles and (not actor or actor['role'] not in roles):
                        raise WorkflowError('This action requires a supervisor account.',403)
                    db.execute('BEGIN IMMEDIATE')
                    sync(db,now(),settings,profile)
                    result=fn(db,actor,*args,**kwargs)
                    db.commit()
                    return result
                except WorkflowError as error:
                    db.rollback()
                    return jsonify(error=str(error)),error.status
                except Exception:
                    db.rollback()
                    raise
            return wrapped
        return decorate

    def payload():
        value=request.get_json(silent=True)
        if not isinstance(value,dict):
            raise WorkflowError('Send one JSON object.')
        return value

    def get_incident(db, incident_id):
        item=db.execute('SELECT * FROM incidents WHERE id=?',(incident_id,)).fetchone()
        if not item:
            raise WorkflowError('Incident not found.',404)
        return item

    def editable(db, incident_id, data):
        item=get_incident(db,incident_id)
        if type(data.get('version')) is not int or data['version']!=item['version']:
            raise WorkflowError('This case changed in another session. Refresh its details before submitting again.',409)
        if item['status']=='closed':
            raise WorkflowError('Closed records are retained as read-only evidence.',409)
        return item

    def assigned_operator(item,actor):
        if actor['role']!='operator' or item['assigned_to']!=actor['id']:
            raise WorkflowError('Only the assigned operator can record this work or capture its evidence.',403)

    def public_incident(db,item):
        out={k:item[k] for k in ('id','asset_id','location','status','cycle','detected_at','detected_level','threshold','clear_threshold','assigned_to','closed_at','version')}
        assigned=db.execute('SELECT display_name FROM workflow_users WHERE id=?',(item['assigned_to'],)).fetchone()
        out.update(code=f'SR-{item["id"]:05d}',assigned_name=assigned['display_name'] if assigned else None,current_profile=item['profile_key']==profile)
        return out

    def detail(db,item):
        out=public_incident(db,item)
        out['events']=[dict(r,detail=json.loads(r['detail'])) for r in db.execute('SELECT * FROM incident_events WHERE incident_id=? ORDER BY id DESC',(item['id'],))]
        out['inspections']=[dict(r) for r in db.execute('SELECT i.*,u.display_name AS operator_name FROM incident_inspections i JOIN workflow_users u ON i.operator_id=u.id WHERE incident_id=? ORDER BY i.id DESC',(item['id'],))]
        out['trials']=[]
        for row in db.execute('SELECT * FROM incident_trials WHERE incident_id=? ORDER BY id DESC',(item['id'],)):
            run={k:row[k] for k in ('id','cycle','phase','status','started_at','finished_at','reason','operator_id')}
            run.update(conditions=json.loads(row['conditions']),result=json.loads(row['result']) if row['result'] else None)
            out['trials'].append(run)
        out['comparison']=comparison(db,item,profile)
        clear,reason=safe_to_close(db,item,now(),settings,profile)
        out['closure_check']={'eligible':clear and out['comparison']['outcome']=='improved','reason':reason if not clear else out['comparison']['reason']}
        return out

    @app.after_request
    def workflow_observer(response):
        if request.path=='/api/readings' and response.status_code in (200,201):
            db=database()
            db.execute('BEGIN IMMEDIATE')
            try:
                sync(db,now(),settings,profile)
                db.commit()
            except Exception:
                db.rollback()
                raise
        return response

    @app.get('/incidents')
    def incidents_page():
        return render_template('incidents.html',mode=app.config['MODE'],settings=settings)

    @app.get('/api/workflow/session')
    def workflow_session():
        return jsonify(user=person(user()),setup_required=not database().execute('SELECT 1 FROM workflow_users LIMIT 1').fetchone(),mode=app.config['MODE'])

    @app.post('/api/workflow/setup')
    @endpoint(mutate=True,public=True)
    def workflow_setup(db,_actor):
        if request.remote_addr not in ('127.0.0.1','::1'):
            raise WorkflowError('Create the first accounts from http://127.0.0.1:5050/incidents on the dashboard Mac.',403)
        if db.execute('SELECT 1 FROM workflow_users LIMIT 1').fetchone():
            raise WorkflowError('Accounts already exist. Sign in instead.',409)
        data=payload()
        accounts=[]
        for role in ('supervisor','operator'):
            info=data.get(role)
            if not isinstance(info,dict):
                raise WorkflowError('Provide a supervisor and an operator account.')
            username=text_value(info,'username',3,64).lower()
            if not all(c.isalnum() or c in '._-' for c in username):
                raise WorkflowError('Usernames use letters, numbers, dots, underscores or hyphens.')
            display=text_value(info,'display_name',2,80)
            password=text_value(info,'password',8,128)
            accounts.append((username,display,role,generate_password_hash(password)))
        if accounts[0][0]==accounts[1][0]:
            raise WorkflowError('Use different supervisor and operator usernames.')
        db.executemany('INSERT INTO workflow_users(username,display_name,role,password_hash) VALUES(?,?,?,?)',accounts)
        return jsonify(status='created'),201

    @app.post('/api/workflow/login')
    @endpoint(mutate=True,public=True)
    def workflow_login(db,_actor):
        data=payload()
        username=text_value(data,'username',1,64).lower()
        password=text_value(data,'password',1,128)
        ip=request.remote_addr or 'unknown'
        db.execute('DELETE FROM workflow_login_attempts WHERE tried_at<?',(now()-300,))
        attempts=db.execute('SELECT COUNT(*) FROM workflow_login_attempts WHERE ip=?',(ip,)).fetchone()[0]
        if attempts>=10:
            raise WorkflowError('Too many sign-in attempts. Wait five minutes and retry.',429)
        account=db.execute('SELECT * FROM workflow_users WHERE username=?',(username,)).fetchone()
        if not account or not check_password_hash(account['password_hash'],password):
            db.execute('INSERT INTO workflow_login_attempts VALUES(?,?)',(ip,now()))
            # Persist failed attempts even though the credential check fails.
            db.commit()
            raise WorkflowError('Username or password is incorrect.',401)
        token=secrets.token_urlsafe(32)
        db.execute('DELETE FROM workflow_sessions WHERE expires_at<=?',(now(),))
        db.execute('INSERT INTO workflow_sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),account['id'],now()+SESSION_SECONDS))
        response=jsonify(user=person(account))
        response.set_cookie(COOKIE,token,max_age=SESSION_SECONDS,httponly=True,samesite='Strict',secure=request.is_secure)
        return response

    @app.post('/api/workflow/logout')
    @endpoint(mutate=True)
    def workflow_logout(db,_actor):
        token=request.cookies.get(COOKIE,'')
        db.execute('DELETE FROM workflow_sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
        response=jsonify(status='signed_out');response.delete_cookie(COOKIE)
        return response

    @app.get('/api/workflow/summary')
    @endpoint(public=True)
    def workflow_summary(db,_actor):
        return jsonify(open_count=db.execute("SELECT COUNT(*) FROM incidents WHERE status!='closed'").fetchone()[0])

    @app.get('/api/incidents')
    @endpoint()
    def incident_list(db,actor):
        rows=db.execute('SELECT * FROM incidents ORDER BY CASE WHEN status=\'closed\' THEN 1 ELSE 0 END,id DESC LIMIT 500').fetchall()
        return jsonify(incidents=[public_incident(db,r) for r in rows],operators=[dict(r) for r in db.execute("SELECT id,display_name FROM workflow_users WHERE role='operator' ORDER BY display_name")],user=person(actor),server_time=now(),capture_seconds=DURATION,start_tolerance_mm=START_TOLERANCE,min_improvement_mm=MIN_IMPROVEMENT,active_capture=dict(active) if (active:=db.execute("SELECT id,incident_id,location,started_at FROM incident_trials WHERE status='running'").fetchone()) else None)

    @app.get('/api/incidents/<int:incident_id>')
    @endpoint()
    def incident_detail(db,_actor,incident_id):
        return jsonify(detail(db,get_incident(db,incident_id)))

    @app.post('/api/incidents/<int:incident_id>/assign')
    @endpoint(roles=('supervisor',),mutate=True)
    def assign(db,actor,incident_id):
        data=payload();item=editable(db,incident_id,data)
        if item['status']=='awaiting_review':
            raise WorkflowError('Review this case before changing its assignment.',409)
        if db.execute("SELECT 1 FROM incident_trials WHERE incident_id=? AND status='running'",(incident_id,)).fetchone():
            raise WorkflowError('Cancel the active evidence capture before reassigning.',409)
        operator_id=data.get('operator_id')
        if type(operator_id) is not int:
            raise WorkflowError('Select an operator.')
        operator=db.execute("SELECT id,display_name FROM workflow_users WHERE id=? AND role='operator'",(operator_id,)).fetchone()
        if not operator:
            raise WorkflowError('Select a valid operator account.')
        status='assigned' if item['status']=='open' else item['status']
        db.execute('UPDATE incidents SET assigned_to=?,status=?,version=version+1 WHERE id=?',(operator_id,status,incident_id))
        audit(db,incident_id,actor['display_name'],'assigned',{'operator':operator['display_name']},now(),item['cycle'])
        return jsonify(status=status)

    @app.post('/api/incidents/<int:incident_id>/inspection')
    @endpoint(mutate=True)
    def inspection(db,actor,incident_id):
        data=payload();item=editable(db,incident_id,data);assigned_operator(item,actor)
        if item['status'] not in ('assigned','in_progress'):
            raise WorkflowError('This case is not accepting maintenance records.',409)
        if db.execute("SELECT 1 FROM incident_trials WHERE incident_id=? AND status='running'",(incident_id,)).fetchone():
            raise WorkflowError('Finish or cancel the evidence capture before recording work.',409)
        findings=text_value(data,'findings',10,2000);work=text_value(data,'work_done',10,2000)
        db.execute('INSERT INTO incident_inspections(incident_id,cycle,operator_id,findings,work_done,created_at) VALUES(?,?,?,?,?,?)',(incident_id,item['cycle'],actor['id'],findings,work,now()))
        db.execute("UPDATE incidents SET status='in_progress',version=version+1 WHERE id=?",(incident_id,))
        audit(db,incident_id,actor['display_name'],'inspection_recorded',{'findings':findings,'work_done':work},now(),item['cycle'])
        return jsonify(status='in_progress'),201

    @app.post('/api/incidents/<int:incident_id>/captures')
    @endpoint(mutate=True)
    def capture(db,actor,incident_id):
        data=payload();item=editable(db,incident_id,data);assigned_operator(item,actor)
        if item['status'] not in ('assigned','in_progress'):
            raise WorkflowError('Capture evidence while this case is assigned or in progress.',409)
        if item['profile_key'] != profile:
            raise WorkflowError('Calibration changed since detection. Keep this case open for supervisor assessment.')
        if db.execute("SELECT 1 FROM incident_trials WHERE status='running'").fetchone():
            raise WorkflowError('Another controlled capture is already running. Finish or cancel it first.',409)
        phase=data.get('phase')
        if phase not in ('before','after'):
            raise WorkflowError('Choose before or after maintenance.')
        if data.get('conditions_confirmed') is not True:
            raise WorkflowError('Confirm the controlled physical conditions and continuous supervision.')
        label=text_value(data,'setup_label',3,120)
        latest_inspection=db.execute('SELECT * FROM incident_inspections WHERE incident_id=? AND cycle=? ORDER BY id DESC LIMIT 1',(incident_id,item['cycle'])).fetchone()
        if phase=='before' and latest_inspection:
            raise WorkflowError('A before capture must precede work in this review cycle. Ask the supervisor to keep the case open for a new cycle.')
        if phase=='after':
            if not latest_inspection:
                raise WorkflowError('Record the inspection findings and work before capturing after evidence.')
            if not db.execute("SELECT 1 FROM incident_trials WHERE incident_id=? AND cycle=? AND phase='before' AND status='completed'",(incident_id,item['cycle'])).fetchone():
                raise WorkflowError('A completed before capture is required. A new review cycle is needed if work already happened.')
        reading=fresh_pair(db,now(),settings)
        if any(reading[s+'_mm']>=settings[s+'_max_mm']-5 for s in SENSORS) or reading[item['location']+'_mm']<=20:
            raise WorkflowError('Start below the maximum-depth guards and above 20 mm at the measured location. Keep any pump fully submerged.')
        conditions={'setup_label':label,'method':'upstream_drawdown' if item['location']=='upstream' else 'pond_drawdown','inflow':'none','pump':'off' if item['location']=='upstream' else 'operator_on','gravity_drain':'open' if item['location']=='upstream' else 'closed'}
        samples=[{k:reading[k] for k in ('id','sampled_at','upstream_mm','downstream_mm')}]
        created=db.execute("INSERT INTO incident_trials(incident_id,cycle,phase,operator_id,profile_key,location,conditions,status,started_at,start_reading_id,last_reading_id,boot_id,last_sampled_at,samples,reason) VALUES(?,?,?,?,?,?,?,'running',?,?,?,?,?,?,?)",(incident_id,item['cycle'],phase,actor['id'],profile,item['location'],json.dumps(conditions,sort_keys=True),now(),reading['id'],reading['id'],reading['boot_id'],reading['sampled_at'],json.dumps(samples),'Operator declared controlled conditions. Physical pump operation is manual.'))
        db.execute("UPDATE incidents SET status='in_progress',version=version+1 WHERE id=?",(incident_id,))
        audit(db,incident_id,actor['display_name'],'evidence_started',{'trial_id':created.lastrowid,'phase':phase,'conditions':conditions,'start_reading_id':reading['id']},now(),item['cycle'])
        return jsonify(status='running',capture_id=created.lastrowid),201

    @app.post('/api/incidents/<int:incident_id>/captures/cancel')
    @endpoint(mutate=True)
    def cancel_capture(db,actor,incident_id):
        item=get_incident(db,incident_id)
        if actor['role']!='supervisor':
            assigned_operator(item,actor)
        trial=db.execute("SELECT * FROM incident_trials WHERE incident_id=? AND status='running'",(incident_id,)).fetchone()
        if trial:
            finish_trial(db,trial,'cancelled','Operator cancelled the capture. Stop any manual pump.',now())
        return jsonify(status='cancelled' if trial else 'idle')

    @app.post('/api/incidents/<int:incident_id>/submit')
    @endpoint(mutate=True)
    def submit(db,actor,incident_id):
        data=payload();item=editable(db,incident_id,data);assigned_operator(item,actor)
        if item['status'] not in ('assigned','in_progress'):
            raise WorkflowError('This case cannot be submitted in its current state.',409)
        if not db.execute('SELECT 1 FROM incident_inspections WHERE incident_id=? AND cycle=?',(incident_id,item['cycle'])).fetchone():
            raise WorkflowError('Record inspection findings and work before submitting.')
        if db.execute("SELECT 1 FROM incident_trials WHERE incident_id=? AND status='running'",(incident_id,)).fetchone():
            raise WorkflowError('Finish or cancel the running capture before submitting.')
        db.execute("UPDATE incidents SET status='awaiting_review',version=version+1 WHERE id=?",(incident_id,))
        audit(db,incident_id,actor['display_name'],'submitted_for_review',{'comparison':comparison(db,item,profile)},now(),item['cycle'])
        return jsonify(status='awaiting_review')

    @app.post('/api/incidents/<int:incident_id>/review')
    @endpoint(roles=('supervisor',),mutate=True)
    def review(db,actor,incident_id):
        data=payload();item=editable(db,incident_id,data)
        if item['status']!='awaiting_review':
            raise WorkflowError('The operator must submit this case for review first.',409)
        note=text_value(data,'review_note',10,2000)
        decision=data.get('decision')
        if decision=='close':
            if data.get('evidence_reviewed') is not True:
                raise WorkflowError('Confirm that you reviewed the physical test conditions and evidence.')
            result=comparison(db,item,profile)
            if result['outcome']!='improved':
                raise WorkflowError('Closure blocked: '+result['reason'])
            clear,reason=safe_to_close(db,item,now(),settings,profile)
            if not clear:
                raise WorkflowError('Closure blocked: '+reason)
            db.execute("UPDATE incidents SET status='closed',closed_at=?,version=version+1 WHERE id=?",(now(),incident_id))
            audit(db,incident_id,actor['display_name'],'closed_after_review',{'note':note,'comparison':result,'clearing_evidence':reason},now(),item['cycle'])
            return jsonify(status='closed')
        if decision=='keep_open':
            db.execute("UPDATE incidents SET status='in_progress',cycle=cycle+1,version=version+1 WHERE id=?",(incident_id,))
            audit(db,incident_id,actor['display_name'],'kept_open',{'note':note,'previous_comparison':comparison(db,item,profile),'next_cycle':item['cycle']+1},now(),item['cycle'])
            return jsonify(status='in_progress')
        raise WorkflowError('Choose close or keep_open.')

    @app.get('/api/incidents/<int:incident_id>/export.json')
    @endpoint()
    def export_case(db,_actor,incident_id):
        item=get_incident(db,incident_id)
        record=detail(db,item)
        for trial in record['trials']:
            stored=db.execute('SELECT samples FROM incident_trials WHERE id=?',(trial['id'],)).fetchone()
            trial['samples']=json.loads(stored['samples'])
        return Response(json.dumps(record,indent=2),mimetype='application/json',headers={'Content-Disposition':f'attachment; filename="stormready_SR-{incident_id:05d}.json"'})

    @app.get('/api/incidents/export.csv')
    @endpoint()
    def export_incidents(db,_actor):
        output=io.StringIO(newline='');writer=csv.writer(output)
        fields=('code','asset_id','location','status','cycle','detected_at','detected_level','assigned_name','closed_at')
        writer.writerow(fields)
        for item in db.execute('SELECT * FROM incidents ORDER BY id'):
            values=public_incident(db,item)
            # Prevent spreadsheet software interpreting entered names as formulas.
            writer.writerow("'"+str(values[k]) if isinstance(values[k],str) and values[k].startswith(('=','+','-','@','\t','\r')) else values[k] for k in fields)
        return Response(output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename="stormready_incidents.csv"'})
