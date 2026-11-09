from typing import TypedDict, Literal, NotRequired


class ArtifactRef(TypedDict):
    path: str
    sha256: str
    run_id: str
    schema_version: str


class SelectionRequest(TypedDict):
    collect_manifest: ArtifactRef
    policy: ArtifactRef
    # Deprecated compatibility fields, ignored by the sequential engine.
    tiab_batch_size: NotRequired[Literal[300]]
    fulltext_batch_size: NotRequired[Literal[50]]


class DownloadRequest(TypedDict):
    verified_dataset_manifest: ArtifactRef
    access_policy: ArtifactRef


class PreprocessingRequest(TypedDict):
    raw_files_manifest: ArtifactRef
    transformation_policy: ArtifactRef
