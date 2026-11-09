"""Import a reviewer-captured public supplementary POST response, without refetching it."""
import base64
import copy
import io
import json
import shutil
import subprocess
import threading
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from ..core.storage import digest


class SupplementaryForms(HTMLParser):
    def __init__(self):
        super().__init__(); self.forms=[]; self.current=None

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='form':self.current=dict(attrs, labels=[], fields=[])
        if tag=='input' and self.current is not None:
            self.current['fields'].append((attrs.get('type',''),attrs.get('name','')))

    def handle_data(self, data):
        if self.current is not None:self.current['labels'].append(data)

    def handle_endtag(self, tag):
        if tag=='form' and self.current is not None:
            self.forms.append(self.current);self.current=None


def checked_bytes(record, limit=8*1024*1024):
    raw=base64.b64decode(record.get('body_sample_b64',''),validate=True)
    if (not raw or len(raw)>limit or len(raw)!=record.get('bytes_observed')
            or digest(raw)!=record.get('payload_sha256') or record.get('complete_body') is not True
            or record.get('http_status')!=200):
        raise ValueError('Incomplete or changed public form response')
    return raw


def append_form_materials(root, paper, bundle, refs):
    """Only an explicit same-paper receipt bound to an observed public form is accepted."""
    result=copy.deepcopy(bundle)
    if len(refs)>3:raise ValueError('Form capture limit')
    for ref in refs:
        path=(root/ref['path']).resolve()
        if not path.is_relative_to(root.resolve()):raise ValueError('Form capture outside run')
        raw=path.read_bytes()
        if digest(raw)!=ref['sha256']:raise ValueError('Form capture changed')
        capture=json.loads(raw)
        if (capture['paper_id']!=paper['paper_id'] or capture['pmid']!=paper['pmid']
                or not capture.get('reviewer_note')):raise ValueError('Unbound form capture')
        parent=next(e for e in bundle['records'] if e['evidence_id']==capture['source_evidence_id'])
        if (parent.get('kind')!='fulltext' or parent.get('status')!='accessible'
                or parent.get('identity_match') is not True
                or parent.get('payload_sha256')!=capture['source_sha256']):
            raise ValueError('Public supplementary form needs verified article provenance')
        parser=SupplementaryForms();parser.feed(checked_bytes(parent).decode('utf-8'))
        e=copy.deepcopy(capture['record']);url=e['url'];origin=urlsplit(parent['final_url'])
        matching=[f for f in parser.forms if f.get('method','').upper()=='POST'
                  and ' '.join(' '.join(f['labels']).split()).casefold()=='supplementary'
                  and urljoin(parent['final_url'],f.get('action',''))==url
                  and f['fields'] and all(t=='hidden' for t,n in f['fields'])]
        target=urlsplit(url)
        if (len(matching)!=1 or target.scheme!='https' or target.netloc!=origin.netloc
                or target.username or target.password or target.query or target.fragment
                or e.get('final_url')!=url or e.get('request_method')!='POST'
                or e.get('kind')!='file' or e.get('status')!='accessible'
                or e.get('level')!='response_sample'):
            raise ValueError('Not an observed same-origin supplementary POST response')
        checked_bytes(e)
        e.update(form_source_evidence_id=parent['evidence_id'],capture_file=dict(ref),
                 request_performed=True,identity_match=True,columns=[])
        if not any(old['evidence_id']==e['evidence_id'] for old in result['records']):result['records'].append(e)
        members=capture.get('pdf_members',[])
        if len(members)>3:raise ValueError('Archive member limit')
        for member in members:
            name=member['name']
            if (not isinstance(name,str) or not name.lower().endswith('.pdf') or name.startswith('-')
                    or Path(name).is_absolute() or '..' in name.replace('\\','/').split('/')):
                raise ValueError('Unsafe archive member')
            archive=(root/member['archive_path']).resolve()
            if (not archive.is_relative_to(root.resolve()) or archive.stat().st_size>8*1024*1024
                    or digest(archive.read_bytes())!=e['payload_sha256']):
                raise ValueError('Archive does not match actual form response')
            tar=shutil.which('tar')
            if not tar:raise ValueError('RAR inspection requires a RAR-capable bsdtar')
            # Stream one observed member to stdout; never extract paths or execute archive contents.
            process=subprocess.Popen([tar,'-xOf',str(archive),name],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            timer=threading.Timer(15,process.kill);timer.daemon=True;timer.start()
            try:
                extracted=process.stdout.read(8*1024*1024+1)
                if len(extracted)>8*1024*1024:process.kill()
                if process.wait(timeout=5)!=0:raise ValueError('Archive member extraction failed')
            finally:
                timer.cancel()
                if process.poll() is None:process.kill();process.wait()
                process.stdout.close()
            if len(extracted)>8*1024*1024 or digest(extracted)!=member['sha256']:
                raise ValueError('Archive member changed or oversized')
            from pypdf import PdfReader
            reader=PdfReader(io.BytesIO(extracted))
            if reader.is_encrypted or not 1<=len(reader.pages)<=64:raise ValueError('Unsupported supplementary PDF')
            text='\n'.join(p.extract_text() or '' for p in reader.pages)
            if len(text)>250000:raise ValueError('Supplementary text limit')
            child=copy.deepcopy(e)
            child.update(evidence_id='form-pdf-'+digest((e['evidence_id']+name).encode())[:24],
                         parent_evidence_id=e['evidence_id'],archive_member=name,
                         format='application/pdf',bytes_observed=len(extracted),payload_sha256=digest(extracted),
                         body_sample_b64=base64.b64encode(extracted).decode(),text=text,document_text=text,
                         pdf_page_count=len(reader.pages),pdf_text_extracted=True,request_performed=False,
                         transport='public_form_archive_member',downloaded_full_dataset=False)
            if not any(old['evidence_id']==child['evidence_id'] for old in result['records']):result['records'].append(child)
    return result
