"""Law text, context, and illustration associations must survive HTML import."""

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "data/source_catalog/import_law19_html.py"
SPEC = importlib.util.spec_from_file_location("law19_import", MODULE_PATH)
law19 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = law19
SPEC.loader.exec_module(law19)


def paragraph(number, text, sanction=None):
    marker = f'<span class="law-item-level-1">{number}</span>'
    if not number.startswith("19."):
        marker = f'<span class="law-number-level-1">{number}.</span>'
    cls = ' class="law-item-level-2"' if not number.startswith("19.") else ""
    printed = '' if sanction is None else f'<span class="law-sanction"><span class="sanction-label">Sanction: </span><span class="sanction-description">{sanction}</span></span>'
    return f'<p{cls}>{marker} {text} {printed}</p>'


def modal(number, *video_ids):
    videos = ''.join(f'<video data-video-id="{video_id}" data-account="6068525061001" data-player="2BhxkP0So"></video>' for video_id in video_ids)
    return f'<p><div class="brightcode-multi-video-modal-container"><div class="modal fade" id="law-model-law-text-{number}"><h5>Videos</h5>{videos}</div></div></p>'


def wrap(content):
    return '<html><script>throw new Error("must never run");</script><nav><p><span class="law-item-level-1">19.99</span>Ignore outside content.</p></nav><div class="page-law-number-page">'+content+'</div></html>'


class Law19ImportTests(unittest.TestCase):
    def test_associates_subclauses_and_new_major_without_carrying_letter(self):
        text = wrap(
            '<h3>Dangerous play</h3>'+paragraph('19.37', 'Dangerous play includes:')+
            paragraph('c', 'Lifting an opponent.', 'Penalty.')+modal(944, '6205220441001')+
            '<!-- unrelated layout --><aside>Extra content.</aside>'+
            paragraph('d', 'Intentionally collapsing a scrum.', 'Penalty.')+modal(945, '6205216273001', '6205211529001')+
            paragraph('19.38', 'Restricted practices:')+modal(946, '6205211910001')
        )
        catalog = law19.extract_catalog(text)
        self.assertEqual([row['clause_id'] for row in catalog['videos']], ['19.37(c)', '19.37(d)', '19.37(d)', '19.38'])
        self.assertEqual(catalog['videos'][0]['modal_id'], 'law-model-law-text-944')
        self.assertEqual(catalog['videos'][1]['modal_id'], 'law-model-law-text-945')
        self.assertFalse(any(row['clause_id']=='19.99' for row in catalog['clauses']))
        self.assertEqual(catalog['warnings'], [])

    def test_heading_break_leaves_orphan_unassigned(self):
        text = wrap(paragraph('19.11','Crouch conditions.')+modal(1,'111')+'<h3>New section</h3>'+modal(2,'222')+paragraph('19.12','Bind conditions.')+modal(3,'333'))
        catalog = law19.extract_catalog(text)
        self.assertEqual([row['clause_id'] for row in catalog['videos']], ['19.11', None, '19.12'])
        self.assertEqual(catalog['videos'][1]['association_status'], 'unassigned')
        self.assertEqual(len(catalog['warnings']), 1)

    def test_reset_parent_condition_and_exception_sanction_preserved(self):
        parent = 'When there is no infringement, the referee will stop play and reset the scrum if:'
        exception = 'The ball is unintentionally kicked out of the tunnel. Exception: If the ball is repeatedly kicked out, the referee must treat this as intentional.'
        catalog = law19.extract_catalog(wrap('<h3>Resetting a scrum</h3>'+paragraph('19.34',parent)+paragraph('b','The scrum collapses or breaks up.')+modal(2,'111')+paragraph('e',exception,'Penalty.')))
        rows = {row['clause_id']:row for row in catalog['clauses']}
        self.assertEqual(rows['19.34(b)']['inherited_parent_context'],parent)
        self.assertIsNone(rows['19.34(b)']['printed_explicit_sanction'])
        self.assertEqual(rows['19.34(e)']['printed_explicit_sanction'],'Penalty.')
        self.assertEqual(rows['19.34(e)']['sanction_scope'],'conditional_exception_only')
        self.assertIn('unintentionally',rows['19.34(e)']['raw_paragraph_text'])
        self.assertIn('repeatedly kicked out',rows['19.34(e)']['sanction_qualification_quote'])
        self.assertTrue(rows['19.34(e)']['raw_paragraph_text'].endswith('Sanction: Penalty.'))
        self.assertIsNone(rows['19.34(e)']['automatic_infringement_label'])

    def test_global_law_trial_scoped_to_wrapped_subclause(self):
        text = wrap(paragraph('19.30','Once play begins:')+'<div class="alert alert-primary"><h6>GLOBAL LAW TRIAL</h6>'+paragraph('a','Takes up a position near the scrum.','Penalty.')+'</div>'+paragraph('b','Permanently retires.','Penalty.')+paragraph('c','Retires at least five metres.','Penalty.'))
        rows = {row['clause_id']:row for row in law19.extract_catalog(text)['clauses']}
        self.assertTrue(rows['19.30(a)']['global_law_trial'])
        for key in ['19.30','19.30(b)','19.30(c)']:
            self.assertFalse(rows[key]['global_law_trial'], key)

    def test_reference_video_url_is_constructed_and_not_ground_truth(self):
        row = law19.extract_catalog(wrap(paragraph('19.10','The referee calls “crouch”.')+modal(874,'6205008379001')))['videos'][0]
        self.assertEqual(row['constructed_player_url'],'https://players.brightcove.net/6068525061001/2BhxkP0So_default/index.html?videoId=6205008379001')
        self.assertEqual(row['role'],'official_rule_reference')
        self.assertFalse(row['playback_verified'])
        self.assertIsNone(row['video_file'])
        self.assertEqual(row['camera_view'],'unknown')
        self.assertIsNone(row['automatic_infringement_label'])

    def test_rejects_duplicate_clause_ids(self):
        with self.assertRaises(law19.LawImportError):
            law19.extract_catalog(wrap(paragraph('19.11','First.')+paragraph('19.11','Second.')))

    def test_rejects_duplicate_video_reference(self):
        with self.assertRaises(law19.LawImportError):
            law19.extract_catalog(wrap(paragraph('19.11','First.')+modal(1,'111','111')))

    def test_rejects_untrusted_provider_ids(self):
        for name,invalid in [('data-account','https://other.example'),('data-player','../../escape'),('data-video-id','111?extra=value')]:
            with self.subTest(name=name):
                html = wrap(paragraph('19.11','First.')+modal(1,'111'))
                expected={'data-account':'6068525061001','data-player':'2BhxkP0So','data-video-id':'111'}[name]
                html=html.replace(f'{name}="{expected}"',f'{name}="{invalid}"')
                with self.assertRaises(law19.LawImportError):
                    law19.extract_catalog(html)

    def test_import_provenance_and_csv_are_local_and_edition_unknown(self):
        text=wrap(paragraph('19.37','Dangerous play includes:')+paragraph('d','Intentionally collapsing a scrum.','Penalty.')+modal(945,'6205216273001'))
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);source=base/'source.html';source.write_text(text,encoding='utf-8');output=base/'catalog'
            report=law19.import_source(source,output)
            self.assertEqual(report['videos'],1)
            self.assertEqual(report['clauses'],2)
            provenance=json.loads((output/'source_provenance.json').read_text())
            self.assertEqual(provenance['source_sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(provenance['acquisition_method'],'user_supplied_html')
            self.assertEqual(provenance['declared_source_url'],law19.DECLARED_SOURCE_URL)
            self.assertFalse(provenance['independently_fetched'])
            self.assertFalse(provenance['script_execution'])
            self.assertIsNone(provenance['edition_date'])
            self.assertFalse(provenance['historical_applicability_verified'])
            self.assertIn('19.1 restart table',provenance['catalog_scope'])
            self.assertFalse(provenance['assets_downloaded'])
            self.assertFalse(provenance['asset_content_inspected'])
            self.assertFalse(provenance['external_law_contents_included'])
            document=json.loads((output/'law19_document.json').read_text())
            self.assertEqual(document['source_provenance'],provenance)
            self.assertEqual(document['clauses'],json.loads((output/'law19_clauses.json').read_text())['clauses'])
            self.assertEqual(len(document['reference_videos']),1)
            with (output/'law19_reference_videos.csv').open(newline='') as handle:
                rows=list(csv.DictReader(handle))
            self.assertEqual(rows[0]['playback_verified'],'false')
            self.assertEqual(rows[0]['video_file'],'')
            self.assertEqual(rows[0]['clause_id'],'19.37(d)')

    def test_restart_table_keeps_headers_every_cell_links_and_spans(self):
        text=wrap('<h3>Principle</h3>'+paragraph('19.1','Restart table follows:')+
            '<table><thead><tr><th><p>Infringement / stoppage</p></th><th>Location of scrum</th><th>Who throws in</th></tr></thead>'+
            '<tbody><tr><td><p>A <strong>knock forward</strong>.</p><p>Second qualification.</p></td><td>At <a href="/laws-of-the-game/laws-by-number/3-team/#players" title="Team">law 3.15</a>.</td><td>The non-offending team.</td></tr>'+
            '<tr><td rowspan="2">Reset scrum – no infringement.</td><td>Original location.</td><td>Original team.</td></tr>'+
            '<tr><td colspan="2">The referee awards a scrum for another reason.</td></tr></tbody></table>')
        doc=law19.extract_catalog(text)['document']
        table=doc['tables'][0]
        self.assertEqual(table['context_clause_id'],'19.1')
        self.assertEqual(len(table['rows']),4)
        self.assertEqual([cell['text'] for cell in table['header_rows'][0]['cells']],['Infringement / stoppage','Location of scrum','Who throws in'])
        self.assertEqual([row['item_id'] for row in table['body_rows']],['restart_01','restart_02','restart_03'])
        cells=table['body_rows'][0]['cells']
        self.assertEqual(cells[0]['text'],'A knock forward. Second qualification.')
        self.assertEqual(cells[1]['text'],'At law 3.15.')
        self.assertEqual(cells[1]['links'][0]['href'],'/laws-of-the-game/laws-by-number/3-team/#players')
        self.assertEqual(cells[1]['links'][0]['resolved_url'],'https://passport.world.rugby/laws-of-the-game/laws-by-number/3-team/#players')
        self.assertEqual(table['body_rows'][1]['cells'][0]['rowspan'],2)
        self.assertEqual(table['body_rows'][2]['cells'][0]['colspan'],2)
        link=next(ref for ref in doc['cross_references'] if ref['kind']=='hyperlink')
        self.assertEqual(link['context_item_id'],'restart_01')
        self.assertEqual(link['targets'][0]['target'],'3.15')
        self.assertIn('Infringement / stoppage\tLocation of scrum\tWho throws in',doc['visible_body_text'])
        self.assertIn('A knock forward. Second qualification.\tAt law 3.15.\tThe non-offending team.',doc['visible_body_text'])
        self.assertEqual(doc['non_numbered_paragraphs'],[])

    def test_principle_section_hierarchy_title_and_snapshot_exclude_page_furniture(self):
        content='<h3>Principle</h3><p class="lead"></p><p>Restart play with a contest for possession.</p>'+paragraph('19.1','The restart rules follow.')+'<h3>Offside</h3>'+paragraph('19.30','Once play begins:')+'<div class="alert"><h6>GLOBAL LAW TRIAL</h6>'+paragraph('a','A qualified trial rule.')+'</div>'+modal(1,'111')
        text='<html><header><h1>Site title</h1><img src="/logo.svg" alt="Header logo"></header><div id="course-content-area"><h1>19 Scrum</h1>'+wrap(content)+'<footer>Privacy policy and footer links.<img src="/footer.svg"></footer></div></html>'
        doc=law19.extract_catalog(text)['document']
        self.assertEqual(doc['title'],'19 Scrum')
        self.assertEqual(doc['principle']['item_id'],'principle')
        self.assertEqual(doc['principle']['paragraphs'],['Restart play with a contest for possession.'])
        self.assertEqual([item['heading'] for item in doc['sections']],['Principle','Offside'])
        self.assertEqual([item['level'] for item in doc['headings']],[3,3,6])
        self.assertEqual(doc['headings'][-1]['parent_section_id'],doc['sections'][-1]['section_id'])
        self.assertIn('clause:19.30(a)',doc['sections'][-1]['block_ids'])
        self.assertIn('GLOBAL LAW TRIAL',doc['visible_body_text'])
        for absent in ['Privacy policy','Site title','Ignore outside content','must never run','Videos','logo.svg']:
            self.assertNotIn(absent,doc['visible_body_text'])
        self.assertEqual(doc['images'],[])

    def test_images_keep_literal_caption_reference_and_conservative_section_context(self):
        text=wrap(paragraph('19.1','Earlier restart rule.')+'<h3>Forming a scrum</h3>'+
            '<p><img src="/media/formation.png?width=500&amp;height=462" alt="" width="500" height="462"></p>'+
            '<p class="image-figure"><strong>Scrum formation (subject to 19.7)</strong></p>'+
            paragraph('19.2','Form without delay.')+'<h3>Throw</h3>'+paragraph('19.15','Requirements:')+paragraph('g','No spin.')+
            '<div><img src="https://resources.world.rugby/throw.jpg" alt="Diagram supplied by source"></div><p class="image-figure">Throw-in at the scrum</p>')
        doc=law19.extract_catalog(text)['document']
        first,second=doc['images']
        self.assertEqual([image['item_id'] for image in doc['images']],['diagram_01','diagram_02'])
        self.assertIsNone(first['context_clause_id'])
        self.assertEqual(first['section'],'Forming a scrum')
        self.assertEqual(first['context_association'],'section_only')
        self.assertEqual(first['caption'],'Scrum formation (subject to 19.7)')
        self.assertEqual(first['caption_clause_references'],['19.7'])
        self.assertEqual(first['resolved_src'],'https://passport.world.rugby/media/formation.png?width=500&height=462')
        self.assertEqual(first['alt'],'')
        self.assertEqual(first['width'],'500')
        self.assertEqual(second['context_clause_id'],'19.15(g)')
        self.assertEqual(second['context_association'],'preceding_clause_in_same_section')
        self.assertEqual(second['caption'],'Throw-in at the scrum')
        self.assertEqual(second['alt'],'Diagram supplied by source')
        for image in doc['images']:
            self.assertIsNone(image['semantic_clause_assignment'])
            self.assertFalse(image['downloaded'])
            self.assertFalse(image['content_inspected'])

    def test_image_caption_does_not_jump_across_rule_or_section(self):
        text=wrap('<h3>Forming</h3><img src="/first.png" alt="">'+paragraph('19.2','An intervening legal rule.')+'<p class="image-figure">A later unmatched caption.</p>'+
            '<img src="/second.png"><h3>Engagement</h3><p class="image-figure">A caption after a section break.</p>'+paragraph('19.10','Crouch.'))
        doc=law19.extract_catalog(text)['document']
        self.assertTrue(all(image['caption'] is None for image in doc['images']))
        self.assertTrue(all(caption['association_status']=='unassigned' for caption in doc['image_captions']))
        self.assertEqual(doc['image_captions'][0]['image_ids'],[])
        self.assertIn('A later unmatched caption.',doc['visible_body_text'])

    def test_all_explicit_cross_references_and_variation_authority_are_retained(self):
        text=wrap('<h3>Forming a scrum</h3>'+paragraph('19.5','Formation (subject to 19.7d).')+
            paragraph('19.6','A reduction is permitted (see also <a href="/laws-of-the-game/laws-by-number/3-team/" title="3 Team">law 3.15</a>).')+
            '<h3>Scrum law variations</h3>'+paragraph('19.39','A union may implement the under-19 scrum law variations at defined levels of the game within its jurisdiction.'))
        doc=law19.extract_catalog(text)['document']
        refs=doc['cross_references']
        self.assertEqual(len(refs),3)
        self.assertEqual(refs[0]['text'],'19.7d')
        self.assertEqual(refs[0]['target'],'19.7(d)')
        self.assertEqual(refs[1]['context_clause_id'],'19.6')
        self.assertEqual(refs[1]['targets'][0]['target'],'3.15')
        self.assertEqual(refs[2]['target'],'under_19_scrum_law_variations')
        self.assertEqual(refs[2]['context_clause_id'],'19.39')
        self.assertIsNone(refs[2]['resolved_url'])
        self.assertFalse(doc['variation_authority']['external_rules_included'])
        self.assertIsNone(doc['variation_authority']['linked_variation_url'])
        self.assertEqual(doc['variation_authority']['text'],doc['clauses'][-1]['law_text'])
        self.assertTrue(all(not ref['external_content_included'] for ref in refs))

    def test_snapshot_and_catalog_ignore_footer_even_if_nested_in_content(self):
        text=wrap(paragraph('19.1','Real law body.')+'<footer>Private footer text.'+paragraph('19.99','Not a law.')+'<img src="/footer.svg"></footer><script>secretScriptText</script>')
        catalog=law19.extract_catalog(text)
        self.assertEqual([clause['clause_id'] for clause in catalog['clauses']],['19.1'])
        self.assertEqual(catalog['document']['visible_body_text'],'19.1 Real law body.')
        self.assertEqual(catalog['document']['images'],[])

    def test_refuses_existing_output_and_preserves_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);output=base/'existing';output.mkdir();marker=output/'work.txt';marker.write_text('keep')
            with self.assertRaises(law19.LawImportError):
                law19.import_source(base/'not-even-read.html',output)
            self.assertEqual(marker.read_text(),'keep')
            self.assertEqual(list(output.iterdir()),[marker])


if __name__ == '__main__':
    unittest.main()
