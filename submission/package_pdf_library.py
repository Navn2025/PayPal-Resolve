"""Create the PDF-only documentation ZIP after document rendering and review.

python submission/package_pdf_library.py
No source files, Markdown, data files or generation scripts enter the archive.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
LIBRARY=ROOT/'output/pdf/Resolve_Documentation'
OUT=ROOT/'Resolve_Documentation_PDFs_Only.zip'
EXPECTED={
 '00_Documentation_Index.pdf','01_Technical_Architecture.pdf',
 '02_Implementation_Guide.pdf','03_Database_Design.pdf','04_API_Reference.pdf',
 '05_Installation_and_Deployment.pdf','06_Illustrated_User_Manual.pdf',
 '07_Testing_and_Security.pdf','08_Operations_and_Integrations.pdf','09_Engineering_Log.pdf',
}

def main():
    global OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default=OUT.name)
    args=parser.parse_args();OUT=ROOT/args.output
    if not OUT.resolve().is_relative_to(ROOT.resolve()):raise ValueError('Output must remain inside the repository')
    OUT.parent.mkdir(parents=True,exist_ok=True)
    selected={p.name:p for p in LIBRARY.iterdir() if p.is_file()}
    if set(selected)!=EXPECTED:raise ValueError('Unexpected or missing library files')
    if OUT.exists():raise FileExistsError('Existing PDF archive preserved; choose a new output filename')
    hashes={}
    with zipfile.ZipFile(OUT,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,path in sorted(selected.items()):
            if path.is_symlink() or path.suffix.lower()!='.pdf':raise ValueError('Only regular PDFs are permitted')
            data=path.read_bytes()
            if not data.startswith(b'%PDF-'):raise ValueError('Invalid PDF header: '+name)
            hashes[name]=hashlib.sha256(data).hexdigest();archive.writestr(name,data)
    with zipfile.ZipFile(OUT) as archive:
        if len(archive.infolist())!=10 or set(archive.namelist())!=EXPECTED:raise ValueError('Archive membership mismatch')
        if archive.testzip() is not None:raise ValueError('ZIP CRC failure')
        for item in archive.infolist():
            if '/' in item.filename or '\\' in item.filename or not item.filename.endswith('.pdf'):raise ValueError('Unexpected ZIP member')
            if hashlib.sha256(archive.read(item)).hexdigest()!=hashes[item.filename]:raise ValueError('Archive byte mismatch')
    if OUT.stat().st_size>=35_000_000:raise ValueError('Archive exceeds submission limit')
    result={'archive':str(OUT),'pdf_files':10,'source_files':0,'bytes':OUT.stat().st_size,'sha256':hashlib.sha256(OUT.read_bytes()).hexdigest(),'crc':'passed','file_hashes':hashes}
    qa=ROOT/'tmp/pdfs/documentation_bundle';qa.mkdir(parents=True,exist_ok=True)
    (qa/'archive_validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
