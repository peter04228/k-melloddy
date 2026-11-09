import xml.etree.ElementTree as ET
from .config import FIELDS


def text(node):
    return ''.join(node.itertext()) if node is not None else ''


def structure(node):
    """Preserve repeated children, attributes and mixed-content markup."""
    return {'tag': node.tag, 'attributes': node.attrib, 'text': node.text,
            'tail': node.tail, 'children': [structure(n) for n in node]}


def parse_metadata(data, requested_fields):
    if b'<!ENTITY' in data.upper():
        raise ValueError('XML entities are not permitted')
    root = ET.fromstring(data)
    if root.tag != 'PubmedArticleSet' or root.find('.//ERROR') is not None:
        raise ValueError('Invalid EFetch XML root/error')
    records = []
    for item in root:
        if item.tag not in {'PubmedArticle', 'PubmedBookArticle'}:
            raise ValueError('Unsupported EFetch record: ' + item.tag)
        citation = item.find('MedlineCitation') if item.tag == 'PubmedArticle' else item.find('BookDocument')
        if citation is None:
            raise ValueError('Missing citation')
        pmid = text(citation.find('PMID'))
        if not pmid.isdecimal() or int(pmid) <= 0:
            raise ValueError('Missing/invalid metadata PMID')
        article = citation.find('Article') if item.tag == 'PubmedArticle' else citation
        if article is None:
            raise ValueError('Missing Article')
        identifier_path = 'PubmedData/ArticleIdList/ArticleId' if item.tag == 'PubmedArticle' else 'PubmedBookData/ArticleIdList/ArticleId'
        identifiers = {n.get('IdType'): text(n) for n in item.findall(identifier_path)}
        for n in article.findall('ELocationID'):
            identifiers.setdefault(n.get('EIdType'), text(n))
        abstract_nodes = article.findall('./Abstract/AbstractText') + citation.findall('./OtherAbstract/AbstractText')
        sections = [{'label': n.get('Label'), 'category': n.get('NlmCategory'), 'text': text(n)} for n in abstract_nodes]
        abstract = '\n'.join((s['label'] + ': ' if s['label'] else '') + s['text'] for s in sections)
        values = {
            'PMID': pmid, 'Title': text(article.find('ArticleTitle')),
            'Abstract': abstract, 'DOI': identifiers.get('doi', ''), 'PMCID': identifiers.get('pmc', ''),
            'PII': identifiers.get('pii', ''),
            'Keywords': [structure(n) for n in citation.findall('KeywordList')],
            'MeSH': [structure(n) for n in citation.findall('MeshHeadingList/MeshHeading')],
            'Authors': [structure(n) for n in article.findall('AuthorList/Author')],
            'Journal': text(article.find('Journal/Title')),
            'Publication Date': [structure(n) for n in article.findall('Journal/JournalIssue/PubDate') + article.findall('ArticleDate')],
            'Publication Type': [structure(n) for n in article.findall('PublicationTypeList/PublicationType')],
            'Language': [text(n) for n in article.findall('Language')],
            'Volume/Issue/Pages': {'volume': text(article.find('Journal/JournalIssue/Volume')),
                                   'issue': text(article.find('Journal/JournalIssue/Issue')),
                                   'pages': text(article.find('Pagination'))},
            'Affiliation': [text(n) for n in article.findall('.//Affiliation')],
            'Grant': [structure(n) for n in article.findall('GrantList/Grant')],
            'PubMed URL': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',
            'Full Text': [],
        }
        mandatory = {'PMID', 'Title', 'Abstract', 'DOI', 'PMCID'}
        states = {k: ('not_requested' if k not in requested_fields and k not in mandatory
                      else 'available' if values[k] and (k != 'Volume/Issue/Pages' or any(values[k].values()))
                      else 'missing_in_source') for k in FIELDS}
        # ELink is a separate service and has not been called.
        states['Full Text'] = 'not_requested'
        records.append(dict(pmid=pmid, values=values, field_states=states, abstract_sections=sections,
                            abstract_state='available' if abstract else 'abstract_absent',
                            fetch_state='available', full_text_note='Separate ELink lookup not implemented'))
    return records
