"""Stage 2 sequential, evidence-validated screening engine."""
from ..core.contracts import SelectionRequest, ArtifactRef


def select(request: SelectionRequest, *, root=None, policy_dir='config/db_select', organ='Heart', provider=None, collector=None) -> dict:
    """Compatibility facade. policy ArtifactRef refers to common_rules.yaml."""
    if not request or root is None:
        raise ValueError('Selection requires collect_manifest, policy directory and root; use Selector or select CLI')
    from .engine import Selector
    from pathlib import Path
    from ..core.storage import digest
    for name in ['collect_manifest','policy']:
        ref=request[name]
        if ref['schema_version']!='1.0' or digest(Path(ref['path']).read_bytes())!=ref['sha256']:
            raise ValueError('Invalid request reference: '+name)
    if Path(request['policy']['path']).resolve()!=(Path(policy_dir)/'common_rules.yaml').resolve():
        raise ValueError('Policy reference must point to policy_dir/common_rules.yaml')
    engine=Selector(root,policy_dir,organ,provider=provider,collector=collector)
    try:return engine.run(manifest_path=request['collect_manifest']['path'])
    finally:engine.close()
