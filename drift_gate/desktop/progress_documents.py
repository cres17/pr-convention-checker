"""Active document bindings and explicitly retained, inactive provenance."""

MAX_ACTIVE_DOCUMENTS = 10
MAX_ARCHIVED_DOCUMENTS = 120


def archived_documents(payload: dict) -> set[str]:
    docs = payload.get('documents')
    archived = payload.get('archived_documents', [])
    if (not isinstance(docs, dict) or not docs
            or not all(isinstance(path, str) and isinstance(digest, str) for path, digest in docs.items())
            or not isinstance(archived, list) or not all(isinstance(path, str) for path in archived)
            or len(set(archived)) != len(archived) or not set(archived).issubset(docs)
            or len(archived) > MAX_ARCHIVED_DOCUMENTS
            or len(docs) - len(archived) > MAX_ACTIVE_DOCUMENTS):
        raise ValueError('문서 목록을 확인해 주세요. 연결 문서 10개·보관 문서 120개까지 가능합니다.')
    return set(archived)
