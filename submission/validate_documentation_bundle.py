"""Render every library PDF with Poppler and inspect all text-page bounds.

uv run --no-project --with pymupdf --with pillow python submission/validate_documentation_bundle.py
Writes only ignored tmp/pdfs review images and JSON. Overview sheets are for
human/agent visual inspection; geometry checks alone do not establish readability.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess

import pymupdf as fitz
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'output/pdf/Resolve_Documentation'
QA=ROOT/'tmp/pdfs/documentation_bundle'

def inspect(path):
    folder=QA/path.stem;folder.mkdir(parents=True,exist_ok=True)
    command=['pdftoppm','-scale-to','700','-png',str(path),str(folder/'page')]
    subprocess.run(command,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    doc=fitz.open(path);outside=[];ascii_escapes=[]
    for i,page in enumerate(doc):
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines',[]):
                for span in line['spans']:
                    x0,y0,x1,y1=span['bbox']
                    if x0 < -0.5 or y0 < -0.5 or x1 > page.rect.width+0.5 or y1 > page.rect.height+0.5:
                        outside.append({'page':i+1,'bounds':[x0,y0,x1,y1]})
        if '[U+0041]' in page.get_text() or '[U+0020]' in page.get_text():ascii_escapes.append(i+1)
    images=sorted(folder.glob('page-*.png'))
    if len(images)!=len(doc):raise ValueError('Rendered page count mismatch: '+path.name)
    if outside or ascii_escapes:raise ValueError(json.dumps({'file':path.name,'outside':outside[:5],'ascii_escapes':ascii_escapes[:5]}))
    picks=sorted(set([0,1,min(2,len(images)-1),len(images)//2,max(0,len(images)-2),len(images)-1]))
    cellw,cellh=520,750
    sheet=Image.new('RGB',(cellw*3,cellh*2),'#dce2e9');draw=ImageDraw.Draw(sheet)
    for j,i in enumerate(picks):
        image=Image.open(images[i]).convert('RGB');image.thumbnail((cellw-20,cellh-35))
        x=(j%3)*cellw+10;y=(j//3)*cellh+25
        sheet.paste(image,(x,y));draw.text((x,y-18),f'{path.stem} / page {i+1}',fill='black')
    overview=QA/(path.stem+'_overview.jpg');sheet.save(overview,quality=91)
    print(path.name,len(doc),'pages rendered; bounds passed',flush=True)
    return {'file':path.name,'pages_rendered':len(doc),'text_outside_page':0,'overview':str(overview),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--content-only',action='store_true')
    parser.add_argument('--files',nargs='*')
    args=parser.parse_args()
    files=sorted(SOURCE.glob('*.pdf'))
    if len(files)!=10:raise ValueError('Expected ten documents')
    verify_contents()
    if args.content_only:return
    if args.files:
        files=[p for p in files if p.name in args.files]
        if len(files)!=len(args.files):raise ValueError('Unknown requested document')
    with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(inspect,files))
    if args.files:
        previous=json.loads((QA/'render_validation.json').read_text())['documents']
        by_name={r['file']:r for r in previous};by_name.update({r['file']:r for r in results})
        results=[by_name[p.name] for p in sorted(SOURCE.glob('*.pdf'))]
        for row in results:
            if hashlib.sha256((SOURCE/row['file']).read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Stale render validation: '+row['file'])
    result={'documents':results,'all_pages_rendered':sum(x['pages_rendered'] for x in results),'bounds':'passed'}
    (QA/'render_validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'all_pages_rendered':result['all_pages_rendered'],'documents':len(results),'bounds':'passed'}))

def verify_contents():
    def text(name):
        with fitz.open(SOURCE/name) as doc:return '\n'.join(p.get_text() for p in doc)
    def packed(value):return re.sub(r'\s+','',value)
    c=json.loads((ROOT/'postman/contracts/resolve.openapi.json').read_text())
    api=packed(text('04_API_Reference.pdf'))
    operations=[op['operationId'] for group in c['paths'].values() for method,op in group.items() if method in ('get','post','put','patch','delete','head','options')]
    assert all(packed(x) in api for x in operations)
    assert all(packed(x) in api for x in c['components']['schemas'])
    schema=json.loads((ROOT/'tmp/pdfs/schema_dictionary.json').read_text())
    database=packed(text('03_Database_Design.pdf'))
    assert all(packed(t['sql']) in database for t in schema['tables'])
    source=(ROOT/'docs/ENGINEERING_LOG.md').read_text(encoding='utf-8')
    source=re.sub(r'<!--[\s\S]*?-->','',source)
    expected=Counter(re.findall(r'CHG-\d{3}',source))
    observed=Counter(re.findall(r'CHG-\d{3}',text('09_Engineering_Log.pdf')))
    assert all(observed[k]>=v for k,v in expected.items()),{k:(v,observed[k]) for k,v in expected.items() if observed[k]<v}
    assert (SOURCE/'06_Illustrated_User_Manual.pdf').read_bytes()==(ROOT/'docs/user-manual/user-manual.pdf').read_bytes()
    assert 'Isolated workspace using sample records' not in text('05_Installation_and_Deployment.pdf')
    with fitz.open(SOURCE/'01_Technical_Architecture.pdf') as edited,fitz.open(ROOT/'output/pdf/Resolve_Technical_Documentation.pdf') as original:
        assert all(edited[i].get_text()==original[i].get_text() for i in range(13))
        assert 'PDFs only' in edited[13].get_text()
    result={'api_operations':len(operations),'schemas':len(c['components']['schemas']),'stored_table_definitions':len(schema['tables']),'engineering_change_ids':len(expected),'visible_log_id_occurrences_preserved':True,'original_manual_unchanged':True,'first_13_technical_pages_unchanged':True,'retired_demo_copy_corrected':True}
    (QA/'content_validation.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)

if __name__=='__main__':main()
