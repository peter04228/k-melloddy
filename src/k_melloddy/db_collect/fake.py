"""Explicit synthetic offline transport. Never used for real collection implicitly."""
import json
import re
from datetime import date, timedelta
from xml.sax.saxutils import escape


class FakeClient:
    def __init__(self, count=12, *, missing=False, fail_fetch_once=False, duplicate=False, same_day=False, offset=0):
        self.count, self.offset = count, offset
        self.missing, self.fail_fetch_once = missing, fail_fetch_once
        self.duplicate, self.same_day = duplicate, same_day
        self.calls = []

    def search(self, query, start=0, size=0, sort='pub_date'):
        self.calls.append(('search', query, start, size))
        dates = re.findall(r'"(\d{4}-\d{2}-\d{2})"\[(?:pdat|edat)\]', query)
        ids = []
        for n in range(1, self.count + 1):
            day = str(date(2020, 1, 1) + timedelta(days=0 if self.same_day else (n - 1) % 365))
            if not dates or dates[0] <= day <= dates[-1]:
                ids.append(str(n + self.offset))
        selected = ids[start:start+size]
        if self.duplicate and len(selected) > 1:
            selected[-1] = selected[0]
        return json.dumps({'esearchresult': {'count': str(len(ids)), 'idlist': selected,
                         'querytranslation': query}}).encode()

    def fetch(self, pmids):
        self.calls.append(('fetch', list(pmids)))
        if self.fail_fetch_once:
            self.fail_fetch_once = False
            raise RuntimeError('Synthetic temporary network failure')
        if self.missing:
            pmids = pmids[:-1]
        articles = []
        for p in pmids:
            abstract = '' if int(p) % 3 == 0 else '<Abstract><AbstractText Label="METHODS">Synthetic, offline fixture.\nNo clinical evidence.</AbstractText><AbstractText Label="RESULTS">Test result.</AbstractText></Abstract>'
            articles.append(f'<PubmedArticle><MedlineCitation><PMID>{p}</PMID><Article><ArticleTitle>SYNTHETIC paper {escape(p)}</ArticleTitle>{abstract}<Language>eng</Language></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1234/test.{p}</ArticleId></ArticleIdList></PubmedData></PubmedArticle>')
        return ('<PubmedArticleSet>' + ''.join(articles) + '</PubmedArticleSet>').encode()
