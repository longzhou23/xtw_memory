import unittest
from research_memory.store import Store
class CrmwTests(unittest.TestCase):
 def test_real_fifo_multi_and_direct_remaining(self):
  s=Store(':memory:');self.addCleanup(s.close)
  s.create_episode('s','A','A',lifecycle='episode',capacity=1)
  def e(i):return {'id':str(i),'speaker':'p','time':f'2026-10-05T10:0{i}:00+00:00','text':str(i)}
  s.advance_episode('s','A',e(0))
  def r(i):return {'localRecordId':str(i),'subjectRefs':['p'],'text':str(i),'kind':'pending_reference','directSourceEventIds':[str(i)],'usedMemoryIds':[],'supersedes':[]}
  x=s.advance_episode('s','A',e(1),draft={'records':[r(0),r(1)]})
  self.assertEqual(len(x['records']),2)
  self.assertEqual(x['records'][1]['directSourceEventIds'],['1'])
  self.assertEqual(len(s.episode_state('s','A')['history']),2)
 def test_empty_real_checkpoint(self):
  s=Store(':memory:');self.addCleanup(s.close);s.create_episode('s','A','A',lifecycle='episode',capacity=1)
  for i in range(2):
   result=s.advance_episode('s','A',{'id':str(i),'speaker':'p','time':f'2026-10-05T10:0{i}:00+00:00','text':'hi'},draft={'records':[]})
  self.assertEqual(result['records'],[])

class EvidenceTests(unittest.TestCase):
 def setUp(self):
  self.s=Store(':memory:');self.addCleanup(self.s.close)
  self.s.create_episode('s','A','A',lifecycle='episode',capacity=1)
 def e(self,i,**extra):return {'id':str(i),'speaker':'p','time':f'2026-10-05T10:0{i}:00+00:00','text':str(i),**extra}
 def r(self,i,used=(),kind='supported_statement'):
  return {'records':[{'localRecordId':'r','kind':kind,'subjectRefs':['p'],'text':str(i),'directSourceEventIds':[str(i)],'usedMemoryIds':list(used),'supersedes':[]}]}
 def setup_history(self):
  self.s.advance_episode('s','A',self.e(0))
  first=self.s.advance_episode('s','A',self.e(1),draft=self.r(0))['records'][0]['id']
  second=self.s.advance_episode('s','A',self.e(2),draft=self.r(1,[first]))['records'][0]
  return first,second
 def final(self,used=(),kind='supported_statement'):
  state=self.s.episode_state('s','A');ev=[{'eventId':str(i),'quote':str(i)} for i in range(3)]
  return {'write':{'entities':[{'key':'p','type':'PERSON','label':'p','speakerId':'p','evidence':ev[:1]}],
   'memories':[{'key':'m','kind':'EPISODIC','recordKind':kind,'text':'evidence','subject':'p','evidence':ev,'usedMemoryIds':list(used),'supersedes':[]}],
   'associations':[],'skipped':[]},'temporaryDecisions':[{'memoryId':m['id'],'action':'USED' if m['id'] in used else 'ARCHIVE','reason':'fixture'} for m in state['history']]}
 def test_per_record_inheritance_and_final_atomic_formation(self):
  import json
  first,second=self.setup_history()
  self.assertEqual(second['directSourceEventIds'],['1'])
  self.assertEqual(second['inheritedSourceEventIds'],['0'])
  self.s.close_episode('s','A');out=self.s.consolidate('s','A',draft=self.final([second['id']]))
  node=self.s.visible_nodes('s',[out['mapping']['m']])[out['mapping']['m']]
  self.assertEqual(node['provenance']['inheritedSourceEventIds'],['0','1'])
  self.assertEqual([tuple(x) for x in self.s.db.execute('SELECT source,target FROM episode_final_formed_with')],[(out['mapping']['m'],second['id'])])
  self.assertEqual(self.s.consolidate('s','A')['writeId'],out['writeId'])
 def test_source_mutation_during_real_call_is_rejected(self):
  from research_memory.contracts import Invalid
  self.s.advance_episode('s','A',self.e(0));test=self
  class Model:
   name='fixed'
   def generate(self,*args):
    test.s.db.execute("UPDATE events SET text='changed' WHERE id='0'");test.s.db.commit()
    return test.r(0),{}
  with self.assertRaisesRegex(Invalid,'来源版本'):self.s.advance_episode('s','A',self.e(1),model=Model())
  self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM episode_temporary').fetchone()[0],0)
 def test_unread_direct_and_supersede_without_use_rejected(self):
  from research_memory.contracts import Invalid
  first,second=self.setup_history();draft=self.r(2);draft['records'][0]['directSourceEventIds']=['0']
  with self.assertRaisesRegex(Invalid,'可读'):self.s.advance_episode('s','A',self.e(3),draft=draft)
  draft=self.r(2);draft['records'][0]['supersedes']=[first]
  with self.assertRaisesRegex(Invalid,'supersedes'):self.s.advance_episode('s','A',self.e(3),draft=draft)
 def test_unresolved_final_not_fact_recall(self):
  first,second=self.setup_history();self.s.close_episode('s','A')
  out=self.s.consolidate('s','A',draft=self.final([second['id']],kind='pending_reference'))
  self.assertNotIn(out['mapping']['m'],self.s.visible_nodes('s',[out['mapping']['m']]))
  self.assertEqual(self.s.db.execute('SELECT stage FROM nodes WHERE id=?',(out['mapping']['m'],)).fetchone()[0],'UNRESOLVED')
 def test_final_source_failure_rolls_back_everything_then_retry(self):
  import sqlite3
  first,second=self.setup_history();self.s.close_episode('s','A')
  self.s.db.execute("CREATE TEMP TRIGGER reject_sources BEFORE INSERT ON episode_final_sources BEGIN SELECT RAISE(ABORT,'source failure'); END")
  with self.assertRaisesRegex(sqlite3.IntegrityError,'source failure'):self.s.consolidate('s','A',draft=self.final([second['id']]))
  for table in ('nodes','episode_final_sources','episode_final_formed_with'):
   self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)
  self.s.db.execute('DROP TRIGGER reject_sources')
  self.assertEqual(self.s.consolidate('s','A',draft=self.final([second['id']]))['memoriesCreated'],1)
 def test_metadata_roundtrip(self):
  self.s.advance_episode('s','A',self.e(0,displayName='same label',role='assistant',media='unreadable',replyTo='missing'))
  draft=self.r(0);out=self.s.advance_episode('s','A',self.e(1),draft=draft)
  import json
  payload=json.loads(self.s.db.execute('SELECT input FROM writes WHERE id=?',(out['writeId'],)).fetchone()[0])['payload']['sourceEvents'][0]
  self.assertEqual((payload['displayName'],payload['role'],payload['media'],payload['replyTo']),('same label','assistant','unreadable','missing'))
 def test_unknown_old_database_unchanged(self):
  import tempfile,sqlite3
  from pathlib import Path
  from research_memory.contracts import Invalid
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'old.db';db=sqlite3.connect(path);db.execute('CREATE TABLE private(value TEXT)');db.commit();db.close();before=path.read_bytes()
   with self.assertRaisesRegex(Invalid,'未知'):Store(path)
   self.assertEqual(path.read_bytes(),before)
 def test_global_working_and_pending_input_bound(self):
  from research_memory.contracts import Invalid
  s=Store(':memory:',limits={'global_working_bytes':600,'per_input_bytes':180000,'per_output_bytes':64000});self.addCleanup(s.close)
  s.create_episode('s','A','A',lifecycle='episode',capacity=1);s.create_episode('s','B','B',lifecycle='episode',capacity=6)
  s.advance_episode('s','A',self.e(0))
  with self.assertRaisesRegex(Invalid,'global_working'):s.advance_episode('s','A',self.e(1),draft=self.r(0))
  self.assertEqual(s.db.execute('SELECT COUNT(*) FROM writes').fetchone()[0],0)
  with self.assertRaisesRegex(Invalid,'global_working'):s.advance_episode('s','B',self.e(2,text='x'*500))
