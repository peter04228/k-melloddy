"""No implicit paid/external inference. Providers are explicitly configured plugins."""
from typing import Protocol
import importlib
import copy


class LLMProvider(Protocol):
    name: str
    model: str
    def propose(self, phase: str, paper: dict, policy: dict, evidence: dict, previous: dict | None) -> dict: ...


class UnconfiguredProvider:
    name='unconfigured'
    model='none'
    def propose(self,*args,**kwargs):
        raise RuntimeError('LLM provider is not configured. No review was performed.')


def load_provider(spec):
    if spec in {'unconfigured','codex','openai','local'}:
        raise ValueError(f'Provider {spec!r} is not connected. Configure python:module:factory implementing LLMProvider.')
    if not spec.startswith('python:') or len(spec.split(':'))!=3:
        raise ValueError('Provider must be python:module:factory')
    _,module,factory=spec.split(':')
    try:
        provider=getattr(importlib.import_module(module),factory)()
    except (ImportError,AttributeError) as exc:
        raise ValueError('Configured provider module/factory is unavailable') from None
    if not all(hasattr(provider,k) for k in ['name','model','propose']):
        raise ValueError('Provider does not implement LLMProvider')
    return provider


class FixtureProvider:
    name='offline-fixture'
    model='synthetic-v1'
    def __init__(self, scenarios):
        self.scenarios=scenarios
        self.calls=[]
    def propose(self,phase,paper,policy,evidence,previous=None):
        self.calls.append((paper['paper_id'],phase))
        scenario=self.scenarios[paper['pmid']]
        if phase=='tiab':
            return copy.deepcopy(scenario['tiab'])
        key='revalidated' if previous else 'final'
        result=scenario.get(key,scenario['final'])
        if isinstance(result,Exception):
            raise result
        return copy.deepcopy(result)
