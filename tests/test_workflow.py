import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.now=1800000000.0
        self.base=self.now
        self.seq=0
        self.settings=app.load_settings()
        self.settings.update(upstream_max_mm=75,downstream_max_mm=80,high_water_mm=50,high_water_clear_mm=40,pond_high_water_mm=60,pond_high_water_clear_mm=50)
        self.db=Path(self.temp.name)/'hardware.sqlite3'
        with patch('app.load_settings',return_value=self.settings):
            self.application=app.create_app('hardware',self.db,lambda:self.now)
        self.application.testing=True
        self.telemetry=self.application.test_client()
        self.supervisor=self.application.test_client()
        self.operator=self.application.test_client()
        self.credentials={
            'supervisor':{'username':'supervisor','display_name':'Supervisor One','password':'supervisor-test-secret'},
            'operator':{'username':'operator','display_name':'Operator One','password':'operator-test-secret'},
        }
        self.assertEqual(self.supervisor.post('/api/workflow/setup',json=self.credentials).status_code,201)
        self.login(self.supervisor,'supervisor');self.login(self.operator,'operator')
        self.op_id=self.operator.get('/api/workflow/session').get_json()['user']['id']

    def tearDown(self):self.temp.cleanup()

    def login(self,client,role):
        response=client.post('/api/workflow/login',json={k:self.credentials[role][k] for k in ('username','password')})
        self.assertEqual(response.status_code,200,response.get_json())

    def send(self,up=60,pond=30,advance=1,**changes):
        self.now+=advance
        data={'schema_version':1,'device_id':self.settings['device_id'],'boot_id':'workflow-test','sequence':self.seq,'uptime_ms':int((self.now-self.base)*1000),'sample_age_ms':0,'source':'esp32','upstream_mm':up,'downstream_mm':pond,'upstream_valid':True,'downstream_valid':True}
        self.seq+=1;data.update(changes)
        response=self.telemetry.post('/api/readings',json=data)
        self.assertEqual(response.status_code,201,response.get_json())

    def cases(self):return self.supervisor.get('/api/incidents').get_json()['incidents']
    def details(self,ident):return self.supervisor.get(f'/api/incidents/{ident}').get_json()
    def create(self,pond=False):
        for _ in range(6):self.send(20 if pond else 60,65 if pond else 30)
        return self.cases()[0]['id']
    def action(self,client,ident,path,**data):
        data.setdefault('version',self.details(ident)['version'])
        return client.post(f'/api/incidents/{ident}/{path}',json=data)
    def assign(self,ident):self.assertEqual(self.action(self.supervisor,ident,'assign',operator_id=self.op_id).status_code,200)
    def trial(self,ident,phase,up_start=60,pond_start=30,up_drop=0,pond_drop=0,setup='Bench setup A'):
        self.send(up_start,pond_start)
        response=self.action(self.operator,ident,'captures',phase=phase,setup_label=setup,conditions_confirmed=True)
        self.assertEqual(response.status_code,201,response.get_json())
        for i in range(1,16):self.send(up_start-up_drop*i/15,pond_start-pond_drop*i/15)
        self.assertEqual(self.details(ident)['trials'][0]['status'],'completed',self.details(ident)['trials'])
    def inspect(self,ident):
        response=self.action(self.operator,ident,'inspection',findings='Obstruction found at the gravity drain.',work_done='Removed the obstruction and checked the tubing.')
        self.assertEqual(response.status_code,201,response.get_json())
    def submit(self,ident):self.assertEqual(self.action(self.operator,ident,'submit').status_code,200)
    def prepared(self,improved=True):
        ident=self.create();self.assign(ident);self.trial(ident,'before');self.inspect(ident);self.trial(ident,'after',up_drop=35 if improved else 0)
        self.submit(ident);return ident

    def test_setup_and_role_permissions(self):
        self.assertEqual(self.application.test_client().get('/api/incidents').status_code,401)
        self.assertEqual(self.supervisor.post('/api/workflow/setup',json=self.credentials).status_code,409)
        ident=self.create()
        self.assertEqual(self.action(self.operator,ident,'assign',operator_id=self.op_id).status_code,403)
        self.assertEqual(self.action(self.operator,ident,'review',decision='close',review_note='Reviewed the physical evidence.').status_code,403)
        self.assertEqual(self.action(self.supervisor,ident,'inspection',findings='Checked the drain properly.',work_done='Cleaned the drainage hose.').status_code,403)

    def test_first_setup_requires_localhost(self):
        target=Path(self.temp.name)/'separate.sqlite3'
        with patch('app.load_settings',return_value=self.settings):other=app.create_app('hardware',target,lambda:self.now).test_client()
        response=other.post('/api/workflow/setup',json=self.credentials,environ_overrides={'REMOTE_ADDR':'10.0.0.7'})
        self.assertEqual(response.status_code,403)
        self.assertTrue(other.get('/api/workflow/session').get_json()['setup_required'])

    def test_wrong_credentials_rate_limit_and_logout(self):
        client=self.application.test_client()
        for _ in range(10):self.assertEqual(client.post('/api/workflow/login',json={'username':'operator','password':'incorrect'}).status_code,401)
        self.assertEqual(client.post('/api/workflow/login',json={'username':'operator','password':'incorrect'}).status_code,429)
        self.assertEqual(self.operator.post('/api/workflow/logout',json={}).status_code,200)
        self.assertEqual(self.operator.get('/api/incidents').status_code,401)

    def test_foreign_origin_mutation_is_blocked(self):
        self.assertEqual(self.operator.post('/api/workflow/logout',json={},headers={'Origin':'https://unrelated.example'}).status_code,403)
        self.assertEqual(self.operator.get('/api/incidents').status_code,200)

    def test_confirmation_deduplication_and_independent_locations(self):
        for _ in range(5):self.send(60,65)
        self.assertEqual(self.cases(),[])
        self.send(60,65)
        self.assertEqual({r['location'] for r in self.cases()},{'upstream','downstream'})
        for _ in range(10):self.send(60,65)
        self.assertEqual(len(self.cases()),2)

    def test_missing_upstream_cannot_hide_pond_incident(self):
        for _ in range(6):self.send(None,65,upstream_valid=False)
        self.assertEqual([r['location'] for r in self.cases()],['downstream'])

    def test_alert_clearing_never_closes_incident(self):
        ident=self.create()
        for _ in range(7):self.send(20,30)
        item=self.details(ident)
        self.assertEqual(item['status'],'open')
        self.assertFalse(item['closure_check']['eligible'])
        self.assertEqual(self.action(self.supervisor,ident,'review',decision='close',review_note='The level has now fallen.').status_code,409)

    def test_assignment_version_conflict_and_input_validation(self):
        ident=self.create();version=self.details(ident)['version'];self.assign(ident)
        self.assertEqual(self.action(self.supervisor,ident,'assign',version=version,operator_id=self.op_id).status_code,409)
        self.assertEqual(self.action(self.operator,ident,'inspection',findings='short',work_done='short').status_code,400)
        self.assertEqual(self.action(self.operator,ident,'captures',phase='before',conditions_confirmed=False,setup_label='Bench A').status_code,400)

    def test_full_before_inspect_after_review_close_and_export(self):
        ident=self.prepared()
        details=self.details(ident)
        self.assertEqual(details['comparison']['outcome'],'improved',details['comparison'])
        self.assertTrue(details['closure_check']['eligible'])
        response=self.action(self.supervisor,ident,'review',decision='close',review_note='Reviewed matching setup, readings and physical inspection.',evidence_reviewed=True)
        self.assertEqual(response.status_code,200,response.get_json())
        details=self.details(ident);self.assertEqual(details['status'],'closed')
        self.assertEqual(details['events'][0]['action'],'closed_after_review')
        exported=self.supervisor.get(f'/api/incidents/{ident}/export.json')
        self.assertEqual(exported.status_code,200)
        self.assertGreaterEqual(len(exported.get_json()['trials'][0]['samples']),16)
        csv=self.supervisor.get('/api/incidents/export.csv');self.assertIn('SR-00001',csv.text)
        self.assertEqual(self.action(self.supervisor,ident,'assign',operator_id=self.op_id).status_code,409)

    def test_supervisor_cannot_close_without_review_confirmation(self):
        ident=self.prepared()
        self.assertEqual(self.action(self.supervisor,ident,'review',decision='close',review_note='Checked readings and maintenance evidence.',evidence_reviewed=False).status_code,400)
        self.assertEqual(self.details(ident)['status'],'awaiting_review')

    def test_no_improvement_keeps_case_open_with_new_cycle(self):
        ident=self.prepared(False)
        self.assertEqual(self.details(ident)['comparison']['outcome'],'not_improved')
        self.assertEqual(self.action(self.supervisor,ident,'review',decision='close',review_note='The pump looks acceptable.',evidence_reviewed=True).status_code,400)
        response=self.action(self.supervisor,ident,'review',decision='keep_open',review_note='No sufficient improvement. Inspect the drain again.')
        self.assertEqual(response.status_code,200)
        details=self.details(ident);self.assertEqual(details['cycle'],2);self.assertEqual(len(details['trials']),2)
        self.assertEqual(details['comparison']['outcome'],'inconclusive')
        self.trial(ident,'before')

    def test_start_levels_and_declared_setup_must_match(self):
        ident=self.create();self.assign(ident);self.trial(ident,'before');self.inspect(ident)
        self.trial(ident,'after',pond_start=36,up_drop=35)
        self.assertEqual(self.details(ident)['comparison']['outcome'],'inconclusive')
        self.assertIn('Starting depths',self.details(ident)['comparison']['reason'])
        self.trial(ident,'after',up_drop=35,setup='Different setup')
        self.assertEqual(self.details(ident)['comparison']['outcome'],'inconclusive')
        self.assertIn('Setup labels',self.details(ident)['comparison']['reason'])

    def test_work_must_separate_before_and_after_captures(self):
        ident=self.create();self.assign(ident)
        self.assertEqual(self.action(self.operator,ident,'captures',phase='after',setup_label='Bench A',conditions_confirmed=True).status_code,400)
        self.inspect(ident)
        self.assertEqual(self.action(self.operator,ident,'captures',phase='before',setup_label='Bench A',conditions_confirmed=True).status_code,400)
        self.submit(ident)
        self.assertEqual(self.details(ident)['comparison']['outcome'],'inconclusive')

    def test_bad_sensor_gap_restart_and_cancel_are_inconclusive(self):
        ident=self.create();self.assign(ident)
        for kind in ['invalid','restart','gap','cancel']:
            self.send(60,30)
            started=self.action(self.operator,ident,'captures',phase='before',setup_label='Bench A',conditions_confirmed=True)
            self.assertEqual(started.status_code,201,started.get_json())
            if kind=='invalid':self.send(None,30,upstream_valid=False)
            elif kind=='restart':self.send(60,30,boot_id='reboot',uptime_ms=0)
            elif kind=='gap':self.now+=4
            else:self.operator.post(f'/api/incidents/{ident}/captures/cancel',json={})
            d=self.details(ident);self.assertEqual(d['trials'][0]['status'],'cancelled' if kind=='cancel' else 'inconclusive')
            # Continue in a fresh device boot after the deliberate restart.
            if kind=='restart':
                self.seq+=1
                self.send(60,30,boot_id='workflow-test-next',uptime_ms=0)
                # Future sends use a new consistent boot until the next test.
                previous_send=self.send
                self.send=lambda *a,**kw:previous_send(*a,**dict({'boot_id':'workflow-test-next'},**kw))

    def test_guard_stops_capture_and_one_capture_at_a_time(self):
        ident=self.create();self.assign(ident)
        self.assertEqual(self.action(self.operator,ident,'captures',phase='before',setup_label='Bench A',conditions_confirmed=True).status_code,201)
        self.assertEqual(self.action(self.operator,ident,'captures',phase='before',setup_label='Bench A',conditions_confirmed=True).status_code,409)
        self.send(71,30)
        self.assertEqual(self.details(ident)['trials'][0]['status'],'inconclusive')

    def test_fresh_safe_readings_are_required_at_closure(self):
        ident=self.prepared();self.now+=4
        self.assertEqual(self.action(self.supervisor,ident,'review',decision='close',review_note='Verified the recorded evidence carefully.',evidence_reviewed=True).status_code,400)
        for _ in range(7):self.send(25,30)
        self.assertEqual(self.action(self.supervisor,ident,'review',decision='close',review_note='Fresh readings and evidence confirm recovery.',evidence_reviewed=True).status_code,200)

    def test_high_current_level_blocks_closure_and_new_alert_reuses_open_case(self):
        ident=self.prepared()
        for _ in range(6):self.send(60,30)
        self.assertEqual(len(self.cases()),1)
        self.assertEqual(self.action(self.supervisor,ident,'review',decision='close',review_note='Checked the comparison and current readings.',evidence_reviewed=True).status_code,400)

    def test_new_confirmed_event_after_closure_creates_new_case(self):
        ident=self.prepared();self.action(self.supervisor,ident,'review',decision='close',review_note='Physical evidence and readings reviewed.',evidence_reviewed=True)
        self.create()
        self.assertEqual(len(self.cases()),2)
        self.assertEqual(sum(r['status']!='closed' for r in self.cases()),1)

    def test_pond_drawdown_workflow(self):
        ident=self.create(pond=True);self.assign(ident)
        self.trial(ident,'before',up_start=20,pond_start=65)
        self.inspect(ident)
        self.trial(ident,'after',up_start=20,pond_start=65,up_drop=-10,pond_drop=30)
        self.submit(ident)
        self.assertEqual(self.details(ident)['comparison']['outcome'],'improved')
        for _ in range(6):self.send(30,35)
        result=self.action(self.supervisor,ident,'review',decision='close',review_note='Pond drawdown and physical inspection reviewed.',evidence_reviewed=True)
        self.assertEqual(result.status_code,200,result.get_json())

    def test_records_and_accounts_survive_restart(self):
        ident=self.prepared()
        with patch('app.load_settings',return_value=self.settings):restarted=app.create_app('hardware',self.db,lambda:self.now).test_client()
        self.login(restarted,'supervisor')
        data=restarted.get(f'/api/incidents/{ident}').get_json()
        self.assertEqual(data['status'],'awaiting_review');self.assertEqual(len(data['trials']),2)
        self.assertEqual(len(data['inspections']),1)
        with sqlite3.connect(self.db) as conn:
            hashes=[r[0] for r in conn.execute('SELECT password_hash FROM workflow_users')]
        self.assertTrue(all('test-secret' not in value for value in hashes))

    def test_calibration_change_invalidates_running_capture(self):
        ident=self.create();self.assign(ident)
        self.action(self.operator,ident,'captures',phase='before',setup_label='Bench A',conditions_confirmed=True)
        changed=dict(self.settings,high_water_mm=51)
        with patch('app.load_settings',return_value=changed):restarted=app.create_app('hardware',self.db,lambda:self.now).test_client()
        self.login(restarted,'supervisor')
        data=restarted.get(f'/api/incidents/{ident}').get_json()
        self.assertEqual(data['trials'][0]['status'],'inconclusive')
        self.assertFalse(data['current_profile'])


if __name__=='__main__':unittest.main(verbosity=2)
