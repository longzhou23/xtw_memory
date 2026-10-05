"""Opaque durable IDs must never consume the model's option budget."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'router_deploy'))
from xtw_router.frozen import FrozenTwoJudgeCPU
import tests.test_frozen_router as fixtures

class AliasTests(unittest.TestCase):
    def setUp(self):self.fixture=fixtures.FrozenTests()
    def model(self):return self.fixture.model(.75)
    def test_renaming_storage_ids_does_not_change_any_encoded_text(self):
        p=self.fixture.payload();a=self.model();a.route(p);inputs_a=copy.deepcopy(a.inputs[0]['formatted_inputs'])
        changed=copy.deepcopy(p)
        for i,candidate in enumerate(changed['candidates']):candidate['episode_id']='opaque-'+str(i)+'-'+'f'*150
        b=self.model();result=b.route(changed)
        self.assertEqual(inputs_a,b.inputs[0]['formatted_inputs'])
        self.assertEqual(result['episode_id'],changed['candidates'][1]['episode_id'])
    def test_short_local_keys_only_in_ranking_question(self):
        model=self.model();model.route(self.fixture.payload())
        question=model.inputs[0]['formatted_inputs'][1]['question']
        self.assertEqual(list(question['crit']),['C1','C2'])
