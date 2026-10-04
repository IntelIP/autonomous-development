import datetime as dt
import importlib.util
from pathlib import Path
import unittest
import tempfile
import shutil
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('control',Path(__file__).parents[1]/'controller/control.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

class Contract(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        sources=[]
        for name in c.SOURCES:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
            body=('Synthetic acceptance reference: '+name+'\n').encode()
            path.write_bytes(body)
            sources.append({'id':path.stem,'path':name,'owner':'test fixture','revision':'1','sha256':c.digest(body)})
        (self.root/'docs/sources.json').write_text(c.json.dumps({'sources':sources}))

    def test_window_dst_and_cutoff(self):
        for stamp,active in [('2026-09-26T01:59:00+00:00',False),('2026-09-26T02:00:00+00:00',True),('2026-09-26T10:00:00+00:00',False),('2026-12-26T03:00:00+00:00',True)]:
            self.assertEqual(c.window(dt.datetime.fromisoformat(stamp))[0],active)

    def test_lead_cannot_expand_or_overlap(self):
        plan={'assignments':[{'id':key,'path':value,'instructions':'Improve the hero and supporting copy with concrete product detail. Explain the intended operating window, review artifact and human merge decision. Preserve the existing schema.','sourceIds':['product','claims','architecture','design']} for key,value in c.OWNERS.items()]}
        self.assertEqual(c.validate_plan(plan),plan)
        plan['assignments'][0]['path']='../../etc/passwd'
        with self.assertRaises(ValueError):c.validate_plan(plan)

    def test_required_references(self):
        self.assertEqual(len(c.references(self.root)),4)

    def test_packet_staleness_and_approval(self):
        story={'id':'4da1b8be-7b33-5ce2-8f9f-07ab7d43076e','project_id':c.PROJECT,'updated_at':'2026-09-26','title':'Copy improvement','description':'Acceptance: improve the two approved copy surfaces.'}
        with patch.object(c,'git',return_value='a'*40):
            packet=c.compile_packet(story,root=self.root)
            self.assertEqual(packet,c.compile_packet(story,root=self.root))
            with self.assertRaisesRegex(ValueError,'approval'):c.validate_packet(packet,root=self.root,current=story)
            packet['approval']={'owner':'Hudson Aikins','approvedAt':'2026-09-26','packetDigest':c.digest(c.json.dumps(packet,sort_keys=True).encode())}
            c.validate_packet(packet,root=self.root,current=story)
            with self.assertRaisesRegex(ValueError,'Stale issue'):c.validate_packet(packet,root=self.root,current=dict(story,updated_at='newer'))
            packet['limits']={'workers':3}
            with self.assertRaisesRegex(ValueError,'authority'):c.validate_packet(packet,root=self.root,current=story)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);shutil.copytree(self.root/'docs',root/'docs')
            (root/'docs/product.md').write_text('Unapproved replacement')
            with self.assertRaisesRegex(ValueError,'Stale or missing'):c.references(root)

if __name__=='__main__':unittest.main()
