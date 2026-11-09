"""Stage 3 interface only."""
from ..core.contracts import DownloadRequest, ArtifactRef


def download(request: DownloadRequest) -> ArtifactRef:
    raise NotImplementedError('DB_Download is a contract only; access/license and immutable file verification required')
