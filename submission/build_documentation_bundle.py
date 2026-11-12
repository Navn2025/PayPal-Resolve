"""Build a documentation-only PDF library from maintained project sources.

uv run --no-project --with reportlab --with pypdf --with pillow python submission/build_documentation_bundle.py
Requires tmp/pdfs/schema_dictionary.json from a new disposable SQLiteStore.
Use --only-log to refresh history/index after recording final QA. No app settings
or credentials are loaded. Existing user-manual/technical PDFs are preserved.
"""
import argparse
import ast
import hashlib
import html
import json
from pathlib import Path
import re
import shutil

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import BaseDocTemplate, Flowable, Frame, PageBreak, PageTemplate, Paragraph, Preformatted, Spacer, Table, TableStyle
import build_documentation as design

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/pdf/Resolve_Documentation'
QA = ROOT / 'tmp/pdfs/documentation_bundle'
PW, PH = A4
MARGIN = 48
CW = PW - 96
NAVY, BLUE, INK, MUTED, LINE, PALE = design.NAVY, design.BLUE, design.INK, design.MUTED, design.LINE, design.PALE
CHARSET = set(pdfmetrics.getFont('Body').face.charToGlyph)
VALIDATIONS = {}
TRANS = str.maketrans({'\u2010':'-', '\u2011':'-', '\u2012':'-', '\u2013':'-', '\u2014':' - ', '\u2212':'-', '\u2018':"'", '\u2019':"'", '\u201c':'"', '\u201d':'"', '\u00a0':' ', '\u202f':' ', '\u2192':' -> ', '\u2190':' <- ', '\u2194':' <-> ', '\u2264':'<=', '\u2265':'>=', '\u2713':'[check]', '\u2705':'[check]', '\u274c':'[cross]', '\u26a0':'[note]', '\ufe0f':''})

def clean(value):
    return ''.join(c if ord(c) in CHARSET or c in '\n\t' else f'[U+{ord(c):04X}]' for c in str(value).translate(TRANS))

def inline(value):
    text = clean(value)
    text = re.sub(r'!\[([^]]*)\]\(([^)]+)\)', r'Figure: \1 (\2)', text)
    text = re.sub(r'\[([^]]+)\]\(([^)]+)\)', lambda m: m[1] if m[1]==m[2] else f'{m[1]} ({m[2]})', text)
    text = html.escape(text)
    text = re.sub(r'`([^`]+)`', r'<font name="Code" size="8">\1</font>', text)
    return re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)

S = {}
for key, font, size, leading in [('h1','Strong',20,25),('h2','Strong',12.3,16),('h3','Strong',10.5,14),('body','Body',9.3,13.6),('small','Body',8,11.5),('bullet','Body',9.3,13.6),('cell','Body',8,11.2),('headcell','Strong',8,11.2),('quote','Body',9.1,13.5)]:
    heading = key.startswith('h') and key!='headcell'
    S[key] = ParagraphStyle('Library_'+key, fontName=font, fontSize=size, leading=leading, textColor=colors.white if key=='headcell' else NAVY if heading else MUTED if key in ('small','quote') else INK, spaceBefore=12 if heading else 0, spaceAfter=8 if key not in ('cell','headcell') else 0, keepWithNext=heading, splitLongWords=True, leftIndent=11 if key in ('bullet','quote') else 0, firstLineIndent=-10 if key=='bullet' else 0)
S['code'] = ParagraphStyle('Library_code',fontName='Code',fontSize=7.1,leading=10,textColor=NAVY,spaceBefore=5,spaceAfter=9,leftIndent=7)

def p(text, style='body'):
    return Paragraph(inline(text),S[style])

def grid(rows,widths=None):
    n=max(len(r) for r in rows)
    rows=[list(r)+['']*(n-len(r)) for r in rows]
    widths=widths or ([.35,.65] if n==2 else [1/n]*n)
    data=[[p(c,'headcell' if i==0 else 'cell') for c in r] for i,r in enumerate(rows)]
    t=Table(data,colWidths=[CW*f for f in widths],repeatRows=1,hAlign='LEFT',splitInRow=1)
    rules=[('BACKGROUND',(0,0),(-1,0),NAVY),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),('LINEBELOW',(0,1),(-1,-1),.35,LINE)]
    rules += [('BACKGROUND',(0,i),(-1,i),PALE) for i in range(2,len(rows),2)]
    t.setStyle(TableStyle(rules));t.spaceAfter=10
    return t

def code(text):
    lines=[]
    for source in clean(text).expandtabs(4).splitlines():
        line=source
        while pdfmetrics.stringWidth(line,'Code',7.1)>CW-18:
            cut=len(line)
            while cut>1 and pdfmetrics.stringWidth(line[:cut],'Code',7.1)>CW-18: cut-=1
            space=line.rfind(' ',1,cut)
            if space>cut//2: cut=space+1
            lines.append(line[:cut]);line=line[cut:]
        lines.append(line)
    return Preformatted('\n'.join(lines),S['code'])

def markdown(text):
    lines=re.sub(r'<!--[\s\S]*?-->','',text).splitlines();items=[];i=0
    special=re.compile(r'^(#{1,6}\s|```|\||[-*]\s|\d+\.\s|>|!\[|---+$)')
    while i<len(lines):
        line=lines[i].strip()
        if not line: i+=1;continue
        if line.startswith('```'):
            collected=[];i+=1
            while i<len(lines) and not lines[i].strip().startswith('```'): collected.append(lines[i]);i+=1
            items.append(code('\n'.join(collected)))
        elif line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                cells=[x.strip().replace('\\|','|') for x in re.split(r'(?<!\\)\|',lines[i].strip().strip('|'))]
                if not all(re.fullmatch(r'[: -]+',x) for x in cells): rows.append(cells)
                i+=1
            if rows:
                n=len(rows[0]);rows=[r[:n-1]+[' | '.join(r[n-1:])] if len(r)>n else r for r in rows]
                items.append(grid(rows))
            continue
        elif re.match(r'^#{1,6}\s',line):
            depth=len(line.split(' ',1)[0]);items.append(p(line.split(' ',1)[1],'h1' if depth==1 else 'h2' if depth==2 else 'h3'))
        elif re.match(r'^[-*]\s',line): items.append(p('\u2022 '+line[2:],'bullet'))
        elif re.match(r'^\d+\.\s',line): items.append(p(line))
        elif line.startswith('>'): items.append(p(line.lstrip('> '),'quote'))
        elif re.fullmatch(r'---+',line): items.append(Spacer(1,10))
        else:
            para=[line];i+=1
            while i<len(lines) and lines[i].strip() and not special.match(lines[i].strip()): para.append(lines[i].strip());i+=1
            items.append(p(' '.join(para)));continue
        i+=1
    return items

class Cover(Flowable):
    def __init__(self,number,title,subtitle,description):
        super().__init__();self.width=CW;self.height=680
        self.number,self.title,self.subtitle,self.description=number,title,subtitle,description
    def draw(self):
        c=self.canv;c.setFillColor(NAVY);c.rect(0,650,35,5,fill=1,stroke=0)
        c.setFont('Strong',15);c.drawString(0,618,'Resolve.')
        c.setFillColor(MUTED);c.setFont('Body',8.5);c.drawString(0,594,'DOCUMENTATION LIBRARY / '+self.number)
        title=Paragraph(html.escape(self.title),ParagraphStyle('CoverTitle',fontName='Strong',fontSize=31,leading=39,textColor=NAVY))
        _,h=title.wrap(CW-14,180);title.drawOn(c,0,479-h)
        sub=p(self.subtitle,'h2');_,sh=sub.wrap(CW-20,80);sub.drawOn(c,0,432-h-sh)
        desc=p(self.description);_,dh=desc.wrap(CW-45,150);desc.drawOn(c,0,325-dh)
        c.setStrokeColor(LINE);c.setLineWidth(.6);c.line(0,200,CW,200)
        c.setFillColor(MUTED);c.setFont('Strong',8);c.drawString(0,179,'COMPILATION DATE')
        c.setFont('Body',9);c.setFillColor(INK);c.drawString(0,160,'12 November 2026')
        note=p('Source chapters retain their recorded dates and validation scope. Local, simulated and account-backed evidence are distinguished. This volume does not report a new production acceptance run.','small')
        _,nh=note.wrap(CW-15,100);note.drawOn(c,0,78-nh)

class BookDoc(BaseDocTemplate):
    def __init__(self,path,title):
        super().__init__(str(path),pagesize=A4,leftMargin=48,rightMargin=48,topMargin=64,bottomMargin=56,title='Resolve | '+title,author='Resolve',creator='Resolve documentation library')
        self.short_title=title;self.bookmarks=0;self.flow_checks=[]
        frame=Frame(48,56,CW,PH-120,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0,id='content')
        self.addPageTemplates(PageTemplate(id='book',frames=[frame],onPage=self.chrome))
    def chrome(self,c,doc):
        c.saveState()
        if doc.page>1:
            c.setFont('Strong',8);c.setFillColor(NAVY);c.drawString(48,PH-33,'Resolve.')
            c.setFont('Body',7.5);c.setFillColor(MUTED);c.drawRightString(PW-48,PH-33,self.short_title.upper())
            c.setStrokeColor(LINE);c.setLineWidth(.5);c.line(48,PH-43,PW-48,PH-43)
        c.setStrokeColor(LINE);c.setLineWidth(.5);c.line(48,42,PW-48,42)
        c.setFont('Body',7.5);c.setFillColor(MUTED);c.drawString(48,28,'Documentation library | 12 November 2026');c.drawRightString(PW-48,28,f'Page {doc.page}')
        c.restoreState()
    def afterFlowable(self,item):
        if isinstance(item,Paragraph) and item.style.name in ('Library_h1','Library_h2'):
            key=f'section-{self.bookmarks}';self.bookmarks+=1;self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(item.getPlainText(),key,0,closed=False)
        if getattr(self,'frame',None) is not None and not isinstance(item,PageBreak):
            self.flow_checks.append((self.page,round(self.frame._y+item.getSpaceAfter(),2)))

def validate(path):
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if path in VALIDATIONS and VALIDATIONS[path][0]==digest:return dict(VALIDATIONS[path][1])
    reader=PdfReader(path);assert not reader.is_encrypted,path
    texts=[page.extract_text() or '' for page in reader.pages]
    assert all(t.strip() for t in texts),path
    assert not any('\ufffd' in t or '\u25a0' in t for t in texts),path
    assert not any(re.search(r'\[U\+00[2-7][0-9A-F]\]',t) for t in texts),path
    result={'file':path.name,'pages':len(reader.pages),'bytes':path.stat().st_size,'sha256':digest}
    VALIDATIONS[path]=(digest,result)
    return dict(result)

def build(filename,number,title,subtitle,description,items):
    path=OUT/filename;doc=BookDoc(path,title)
    doc.build([Cover(number,title,subtitle,description),PageBreak()]+items)
    if any(y<55.5 for _,y in doc.flow_checks): raise ValueError('Frame overflow: '+filename+' '+repr(sorted(doc.flow_checks,key=lambda x:x[1])[:3]))
    result=validate(path);print(filename,result['pages'],'pages',flush=True)
    return result

def source_chapters(sources):
    items=[p('Reading map','h1'),p('This volume brings together the maintained source documents listed below. Source chapters retain their recorded evidence dates and assumptions. Later corrections in the engineering log take precedence over older snapshots.'),grid([['Chapter','Source in the project']]+[[title,path] for title,path in sources])]
    for title,path in sources:
        items += [PageBreak(),p(title,'h1'),p('Source: '+path,'small')]+markdown((ROOT/path).read_text(encoding='utf-8-sig'))
    return items

def module_inventory():
    rows=[['Module','Declared responsibility / main entry points']]
    for path in sorted((ROOT/'backend/app').glob('*.py')):
        tree=ast.parse(path.read_text(encoding='utf-8-sig'));doc=ast.get_docstring(tree) or ''
        names=[n.name for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and not n.name.startswith('_')]
        rows.append([path.name,doc.splitlines()[0] if doc else 'Entry points: '+', '.join(names[:7])])
    return [p('Implementation map','h1'),p('This module inventory is read from Python source without importing the application or accessing configured services. It is an implementation map, not runtime test coverage.'),grid(rows,[.32,.68]),PageBreak()]

class CoreRelationships(Flowable):
    def __init__(self):
        super().__init__();self.width=CW;self.height=295
    def draw(self):
        c=self.canv
        def box(x,y,w,title,detail):
            c.setFillColor(PALE);c.setStrokeColor(LINE);c.roundRect(x,y,w,45,4,fill=1,stroke=1)
            c.setFillColor(NAVY);c.setFont('Strong',9);c.drawString(x+8,y+28,title)
            c.setFillColor(MUTED);c.setFont('Code',7.5);c.drawString(x+8,y+12,detail)
        box(169,245,160,'merchants','id')
        box(0,155,215,'resolution_cases','id / merchant_id')
        box(284,155,215,'cases','id / merchant_id / capture_id')
        box(0,45,159,'resolution_promises','resolution_id')
        box(171,45,159,'refund_approvals','case_id')
        box(342,45,157,'refund_executions','approval_id')
        c.setStrokeColor(BLUE);c.setLineWidth(.8)
        for x1,y1,x2,y2 in [(249,245,249,225),(107,225,391,225),(107,225,107,200),(391,225,391,200),(107,155,107,90),(391,155,391,118),(250,118,391,118),(250,118,250,90),(330,67,342,67)]:c.line(x1,y1,x2,y2)
        c.setDash(3,2);c.line(215,177,284,177);c.setDash()
        c.setFont('Body',6.7);c.setFillColor(MUTED);c.drawString(221,184,'optional link')
        c.setFont('Body',8);c.drawString(0,18,'Selected foreign-key links; composite ownership keys are simplified here.')

def database_content():
    schema=json.loads((ROOT/'tmp/pdfs/schema_dictionary.json').read_text());tables=schema['tables']
    items=markdown('''# Storage design
Resolve persists tenant-owned operational state separately from the fact that a provider action completed. SQLite is the local default. PostgreSQL uses the shared repository with a dedicated schema and bounded connection pool.

The dictionary was derived from a brand-new disposable SQLiteStore using the current immutable migrations. No existing owner database or hosted storage was opened. It establishes the fresh SQLite schema shape, not PostgreSQL runtime equivalence or production acceptance.

## Transactions and financial identity
SQLite enables foreign keys and uses BEGIN IMMEDIATE for write transactions. PostgreSQL retains repeatable-read/read-only reads and transactional write locking. Financial amount_cents fields use integer minor units. Capture histories, cases and refundable capacity are scoped to the merchant.

Approval and execution are distinct records. Saved provider request identities, optimistic revisions, deduplication constraints and worker leases keep retries within the authorized operation. Application validation enforces several business rules beyond physical foreign keys.
''')
    items.append(grid([['Measurement','Observed result'],['SQLite schema version',str(schema['schema_version'])],['Tables',str(len(tables))],['Columns',str(sum(len(t['columns']) for t in tables))],['Foreign-key rows',str(sum(len(t['foreign_keys']) for t in tables))],['PRAGMA foreign_key_check',schema['foreign_key_check']]]))
    items+=markdown('''## Relationship guide
merchants is the tenant root. Payment cases and resolution cases retain ownership. Promises, evidence, buyer access, commerce snapshots, approvals and execution histories attach to those contexts. Platform, aftercare and assurance records extend staff operations, returns and dispute holds. The table-specific foreign-key lists below are authoritative for physical relationships; not all logical links are foreign keys.

## Migration policy
Numbered migrations are immutable. Corrections belong in a new migration. The SQLite initializer applies investigation_prerequisite.sql at its transitional point. PostgreSQL uses a separate migration sequence; those files are inspected here, not executed.
''')
    items += [PageBreak(),p('Core relational map','h1'),CoreRelationships(),p('Solid lines show selected foreign-key relationships. The dashed line represents the resolution case\'s optional refund-case link. This overview omits supporting tables and simplifies composite keys; the following catalog and dictionary retain the full physical schema.'),PageBreak(),p('Migration catalog','h1')]
    rows=[['Engine','Migration','SHA-256 prefix']]
    for engine,directory in [('SQLite',ROOT/'backend/migrations'),('PostgreSQL',ROOT/'backend/migrations/postgres')]:
        for path in sorted(directory.glob('*.sql')): rows.append([engine,path.name,hashlib.sha256(path.read_bytes()).hexdigest()[:12]])
    items += [grid(rows,[.16,.62,.22]),PageBreak(),p('Table catalog','h1'),grid([['Table','Columns','FK rows']]+[[t['name'],str(len(t['columns'])),str(len(t['foreign_keys']))] for t in tables],[.64,.18,.18]),PageBreak(),p('Data dictionary','h1'),p('Nullability is reported by PRAGMA table_info. SQLite may report notnull=0 for a primary key; primary-key position is listed separately. Stored definitions preserve CHECK/UNIQUE clauses not fully described by the column list. Defaults are schema expressions, not customer values.')]
    for t in tables:
        rows=[['Column','Storage type','Null / key / default']]
        for c in t['columns']:
            flags=['NOT NULL' if c['notnull'] else 'nullable per pragma']
            if c['pk']: flags.append('PK position '+str(c['pk']))
            if c['dflt_value'] is not None: flags.append('default '+str(c['dflt_value']))
            rows.append([c['name'],c['type'] or 'untyped','; '.join(flags)])
        items += [p(t['name'],'h2'),grid(rows,[.35,.19,.46])]
        if t['foreign_keys']:
            items += [p('Foreign keys','h3'),grid([['Local column','Target','Update / delete']]+[[f['from'],f['table']+'.'+str(f['to']),f['on_update']+' / '+f['on_delete']] for f in t['foreign_keys']],[.28,.44,.28])]
        if t['indexes']:
            items.append(p('Indexes and uniqueness','h3'))
            for x in t['indexes']: items.append(p(x['name']+' | '+('UNIQUE' if x['unique'] else 'index')+' | '+', '.join(str(c['name']) for c in x['columns']),'small'))
        items += [p('Stored table definition','h3'),code(t['sql'])]
    return items+[PageBreak()]+source_chapters([('PostgreSQL migration procedure','docs/POSTGRES_MIGRATION.md')])

def schema_label(s):
    if not s:return 'Unspecified schema'
    if '$ref' in s:return s['$ref'].split('/')[-1]
    if 'anyOf' in s:return ' or '.join(schema_label(x) for x in s['anyOf'])
    if 'oneOf' in s:return 'one of: '+', '.join(schema_label(x) for x in s['oneOf'])
    value=s.get('type','object')
    if value=='array':value+=' of '+schema_label(s.get('items',{}))
    if s.get('format'):value+=' ('+s['format']+')'
    if 'enum' in s:value+='; enum: '+', '.join(str(x) for x in s['enum'])
    return value

def limits(s):
    return '; '.join(f'{k}: {json.dumps(s[k],ensure_ascii=False)}' for k in ('minimum','maximum','exclusiveMinimum','exclusiveMaximum','minLength','maxLength','pattern','minItems','maxItems','multipleOf','default') if k in s)

def api_content():
    c=json.loads((ROOT/'postman/contracts/resolve.openapi.json').read_text());schemas=c.get('components',{}).get('schemas',{})
    ops=[(path,method,op,data) for path,data in c['paths'].items() for method,op in data.items() if method in ('get','post','put','patch','delete','head','options')]
    items=[p('Contract scope','h1'),p(f'This reference is generated from the existing FastAPI OpenAPI snapshot: {len(ops)} operations and {len(schemas)} component schemas. It does not call the API. Older test ledgers cover 175 operations; their historical results do not establish fresh coverage of this contract.'),p('Authentication and interpretation','h2'),p('Full merchant keys, browser sessions, source-bound integration grants and private buyer capabilities have different permissions. Read operation security and implementation context before use. Recording an event or receiving HTTP 200 does not independently prove a PayPal refund. Amounts, nullable verification and outcome status must be read together.'),p('Security schemes','h2')]
    for name,scheme in c.get('components',{}).get('securitySchemes',{}).items():items.append(p(name+': '+json.dumps(scheme)))
    items += [p('Endpoint catalog','h1'),grid([['Method','Route','Summary']]+[[method.upper(),path,op.get('summary',op.get('operationId',''))] for path,method,op,_ in ops],[.12,.48,.4]),PageBreak(),p('Operation reference','h1')]
    for path,method,op,common in ops:
        items.append(p(method.upper()+' '+path,'h2'))
        if op.get('summary'):items.append(p(op['summary']))
        if op.get('description'):items+=markdown(op['description'])
        sec=op.get('security',c.get('security'))
        items += [p('Operation ID: '+op.get('operationId','not specified'),'small'),p('OpenAPI security: '+(json.dumps(sec) if sec is not None else 'not declared at this level; inspect route authorization before use'),'small')]
        params=common.get('parameters',[])+op.get('parameters',[])
        if params:items.append(grid([['Parameter','Location / required','Type / constraints']]+[[x.get('name',x.get('$ref','')),x.get('in','')+(' / required' if x.get('required') else ' / optional'),schema_label(x.get('schema',{}))+'; '+limits(x.get('schema',{}))] for x in params],[.3,.25,.45]))
        body=op.get('requestBody')
        if body:
            for media,data in body.get('content',{}).items():items.append(p('Request body: '+media+' | '+schema_label(data.get('schema',{}))+(' | required' if body.get('required') else ' | optional')))
        rows=[['Status','Description','Content / schema']]
        for status,response in op.get('responses',{}).items():
            content='; '.join(media+': '+schema_label(data.get('schema',{})) for media,data in response.get('content',{}).items())
            rows.append([status,response.get('description',''),content or 'No response body declared'])
        items.append(grid(rows,[.13,.27,.6]))
    items += [PageBreak(),p('Component schema dictionary','h1'),p('Required means required by this object schema. Null unions and constraints are retained separately. The machine-readable JSON remains authoritative for exact serialization.')]
    for name,s in sorted(schemas.items()):
        items.append(p(name,'h2'))
        if s.get('description'):items+=markdown(s['description'])
        if s.get('properties'):
            required=set(s.get('required',[]));rows=[['Field','Required / type','Description / constraints']]
            for field,d in s['properties'].items():rows.append([field,('required; ' if field in required else 'optional; ')+schema_label(d),'; '.join(x for x in (d.get('description',''),limits(d)) if x) or 'No additional description declared'])
            items.append(grid(rows,[.24,.35,.41]))
            if 'additionalProperties' in s:items.append(p('additionalProperties: '+json.dumps(s['additionalProperties']),'small'))
        else:
            items.append(p(schema_label(s)))
            if limits(s):items.append(p(limits(s),'small'))
    return items

FILES=[('00_Documentation_Index.pdf','Documentation index'),('01_Technical_Architecture.pdf','Technical architecture'),('02_Implementation_Guide.pdf','Implementation guide'),('03_Database_Design.pdf','Database design'),('04_API_Reference.pdf','API reference'),('05_Installation_and_Deployment.pdf','Installation and deployment'),('06_Illustrated_User_Manual.pdf','Illustrated user manual'),('07_Testing_and_Security.pdf','Testing and security'),('08_Operations_and_Integrations.pdf','Operations and integrations'),('09_Engineering_Log.pdf','Engineering log')]

def build_log():
    text=(ROOT/'docs/ENGINEERING_LOG.md').read_text(encoding='utf-8-sig')
    intro=[p('About this record','h1'),p('This volume contains the complete maintained engineering-log text. Historical entries, corrections and superseding decisions are retained. Reconstructed early history remains explicitly identified. The log explains development decisions; it does not replace runtime audit records, migrations or Git history.'),p('Formatting note','h2'),p('Markdown is typeset for reading. Long code lines may wrap; typographic dashes and arrows are normalized. Unsupported symbols appear as Unicode code-point labels rather than disappearing. These display changes do not rewrite the source log.'),PageBreak()]
    result=build(FILES[9][0],'09','Engineering log','Development decisions and validation history','The full project engineering record: objectives, choices, alternatives, tests, limitations and explicit corrections.',intro+markdown(text))
    extracted='\n'.join(page.extract_text() or '' for page in PdfReader(OUT/FILES[9][0]).pages)
    ids=set(re.findall(r'CHG-\d{3}',text));missing=sorted(x for x in ids if x not in extracted)
    if missing:raise ValueError('Missing change IDs: '+repr(missing))
    result.update(source_change_ids=len(ids),all_change_ids_present=True)
    return result

def build_index():
    rows=[['Document','Pages','File']]
    for filename,title in FILES[1:]:rows.append([title,str(validate(OUT/filename)['pages']),filename])
    items=markdown((ROOT/'SUBMISSION_README.md').read_text())+[PageBreak(),p('Final PDF inventory','h1'),p('The archive includes this index plus the nine volumes below, in the numbered reading order.'),grid(rows,[.36,.12,.52])]
    return build(FILES[0][0],'00','Documentation index','PDF-only submission library','A reading guide to technical architecture, implementation, database design, API, setup, user workflows, testing, operations and engineering history.',items)

def library_architecture():
    # Preserve the original guide and its first thirteen pages; replace the old
    # source-ZIP appendix with references appropriate to this PDF-only library.
    appendix='''# Submission contents and references
This documentation library contains PDFs only. Application source is a separate delivery. The earlier source-package appendix is replaced here so the reading guide matches the current bundle.

## Related volumes
| Volume | Use it for |
| --- | --- |
| 02 Implementation guide | Service/module responsibilities, reconciliation, guarded execution, AI and SDK integration. |
| 03 Database design | Core relational map, every SQLite table/column, constraints, indexes and migration catalog. |
| 04 API reference | All 178 current operations and 251 component schemas from the generated contract. |
| 05 Installation and deployment | Local setup, example settings, identity configuration and hosted readiness. |
| 06 Illustrated user manual | Merchant and buyer procedures, screenshots, practical tutorials and SDK appendix. |
| 07 Testing and security | Historical local, simulated and account-backed results with their limits. |
| 08 Operations and integrations | Staff operations, customer support, provider configuration and Postman tooling. |
| 09 Engineering log | Complete development history, decisions, corrections and actual validation records. |

## Source references
The guide is grounded in README.md, component READMEs, backend/app, immutable migrations, frontend content, the first-party SDK and postman/contracts/resolve.openapi.json in the project repository. The accompanying books render the relevant maintained documentation, including the full engineering log.

## Edition and review sequence
Pages 1-13 retain the 12 November 2026 technical-guide edition. This final page is adapted for the documentation-only library. The original source-submission PDF remains preserved separately. Begin with the overview and illustrated manual, then use the detailed implementation, database and API books. Follow installation instructions against the separately delivered source.

Recorded tests remain historical. The current API operation count differs from the older audit ledger. New database introspection uses disposable SQLite; it is not acceptance of hosted storage. PayPal demonstrations use Sandbox funds, and an AI recommendation never authorizes a financial action.
'''
    tmp=QA/'architecture-library-appendix.pdf'
    doc=design.GuideDoc(str(tmp),pagesize=A4,leftMargin=48,rightMargin=48,topMargin=66,bottomMargin=56,title='Resolve | Library references')
    frame=Frame(48,56,CW,PH-122,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0,id='appendix')
    def footer(canvas,document):
        original=document.page;document.page=14;design.chrome(canvas,document);document.page=original
    doc.addPageTemplates(PageTemplate(id='appendix',frames=[frame],onPage=footer))
    doc.build(design.parse(appendix))
    if len(PdfReader(tmp).pages)!=1:raise ValueError('Architecture appendix overflow')
    original=ROOT/'output/pdf/Resolve_Technical_Documentation.pdf'
    writer=PdfWriter();writer.append(original,pages=(0,13),import_outline=True);writer.append(tmp,import_outline=False)
    writer.add_outline_item('Submission contents and references',13)
    writer.add_metadata({'/Title':'Resolve | Technical architecture','/Author':'Resolve','/Subject':'Technical guide with PDF-library references'})
    with (OUT/FILES[1][0]).open('wb') as stream:writer.write(stream)
    validate(OUT/FILES[1][0])

def setup_content():
    sources=[('Backend setup and configuration','backend/README.md'),('Frontend setup','frontend/README.md'),('Merchant sign-in','docs/MERCHANT_SIGN_IN.md'),('Buyer identity','docs/CUSTOMER_SIGN_IN.md'),('Deployment procedure','docs/deployment/deployment-guide.md'),('Recorded readiness assessment','docs/deployment/production-readiness-report.md')]
    items=source_chapters(sources)
    for title,path in [('Backend configuration template','backend/.env.example'),('AI process configuration template','backend/ai-env.example.ps1'),('Frontend configuration template','frontend/.env.example'),('Deployment blueprint','render.yaml')]:items += [PageBreak(),p(title,'h1'),p('Source: '+path+'. Examples only; no private settings are read.','small'),code((ROOT/path).read_text(encoding='utf-8-sig'))]
    return items

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--only-log',action='store_true');parser.add_argument('--refresh-design',action='store_true');args=parser.parse_args()
    assert clean('Resolve ASCII 0123')=='Resolve ASCII 0123'
    OUT.mkdir(parents=True,exist_ok=True);QA.mkdir(parents=True,exist_ok=True)
    library_architecture()
    if not args.only_log and not args.refresh_design:
        shutil.copy2(ROOT/'docs/user-manual/user-manual.pdf',OUT/FILES[6][0])
        sources=[('Resolution workspace','docs/RESOLUTION_WORKSPACE.md'),('Backend operations','docs/BACKEND_OPERATIONS.md'),('PayPal reconciliation','docs/PAYPAL_RECONCILIATION.md'),('Refund execution','docs/REFUND_EXECUTION.md'),('Aftercare reliability','docs/AFTERCARE_RELIABILITY.md'),('Embedded aftercare','docs/SDK_AFTERCARE.md'),('Automatic investigations','docs/AI_INVESTIGATIONS.md'),('Server-side SDK','sdk/typescript/README.md'),('Checkout integration','examples/checkout-store/README.md')]
        build(FILES[2][0],'02','Implementation guide','Workflow services, state and integrations','A source-level guide to reconciliation, guarded refunds, evidence investigations, aftercare and the server-side SDK.',module_inventory()+source_chapters(sources))
        build(FILES[3][0],'03','Database design','Schema, relationships and data dictionary','Complete SQLite fields, relationships, constraints and migrations, with PostgreSQL migration instructions. Schema inspection uses new disposable storage.',database_content())
        build(FILES[4][0],'04','API reference','Operations and component schemas','A complete readable companion to the generated contract, including routes, parameters, request/response models and field constraints.',api_content())
        build(FILES[5][0],'05','Installation and deployment','Local runtime, identity and hosted preparation','Component setup, safe configuration examples, identity instructions and the deployment blueprint with recorded readiness limits.',setup_content())
        sources=[('Testing report','docs/testing/testing-report.md'),('Integration verification','docs/testing/production-integration-report.md'),('Bug fixes','docs/testing/bug-fix-report.md'),('Performance evidence','docs/testing/performance-report.md'),('Endpoint coverage ledger','docs/testing/endpoint-coverage.md'),('Synthetic extraction evaluation','backend/evals/extraction/README.md')]
        scope=markdown('''# Security and evidence scope
Ownership comes from authenticated access rather than request-body merchant identifiers. Full merchant keys, individual roles, source-bound integration keys and private buyer capabilities have different permissions. Provider secrets remain server-side and saved connection credentials require a persistent encryption key.

Refund execution requires deterministic amount, seller, currency, capture balance, acceptance/condition, dispute and state-bound approval checks. Model output cannot grant financial authority. Prompt limits and validators are bounded controls, not proof against every possible injection.

The chapters below retain historical audit and evaluation records. Application tests were not rerun for this PDF. The old ledger covers 175 operations; the current API reference covers 178. Local passes, controlled simulations and official Sandbox responses establish different scopes. The evaluation README retains the synthetic, AI-authored dataset provenance and unreviewed labels.
''')
        build(FILES[7][0],'07','Testing and security','Recorded evidence, controls and limitations','Historical test and audit records with their environments, security boundaries, coverage gaps and synthetic evaluation provenance.',scope+[PageBreak()]+source_chapters(sources))
        sources=[('Merchant operations','docs/PLATFORM_EXPANSION.md'),('Customer portal','docs/CUSTOMER_PORTAL.md'),('Customer workflow','docs/CUSTOMER_WORKFLOW.md'),('Hosted follow-up','docs/HOSTED_FOLLOWUP.md'),('Commerce integration','docs/COMMERCE_INTEGRATION.md'),('Performance and preview','docs/PERFORMANCE.md'),('Postman contracts and simulations','postman/README.md'),('Application inventory','docs/testing/application-inventory.md'),('Practical merchant and buyer guide','docs/RESOLVE_GUIDE.md')]
        build(FILES[8][0],'08','Operations and integrations','Merchant workflows and provider tooling','Operating procedures, private customer flows, provider configuration, Postman simulation instructions and the retained application inventory.',source_chapters(sources))
    if args.refresh_design:
        build(FILES[3][0],'03','Database design','Schema, relationships and data dictionary','Complete SQLite fields, relationships, constraints and migrations, with PostgreSQL migration instructions. Schema inspection uses new disposable storage.',database_content())
        build(FILES[5][0],'05','Installation and deployment','Local runtime, identity and hosted preparation','Component setup, safe configuration examples, identity instructions and the deployment blueprint with recorded readiness limits.',setup_content())
    log=build_log();build_index()
    results=[validate(OUT/f) for f,_ in FILES];results[9].update({k:v for k,v in log.items() if k not in results[9]})
    assert set(p.name for p in OUT.iterdir() if p.is_file())==set(f for f,_ in FILES)
    result={'documents':results,'pdf_files':len(results),'total_pages':sum(r['pages'] for r in results),'source_files_in_delivery':0}
    (QA/'pdf_validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

if __name__=='__main__':main()
