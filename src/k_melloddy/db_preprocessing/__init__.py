"""Stage 4 interface only."""
from ..core.contracts import PreprocessingRequest, ArtifactRef


def preprocess(request: PreprocessingRequest) -> ArtifactRef:
    raise NotImplementedError('DB_Preprocessing is a contract only; versioned transformations and provenance required')
