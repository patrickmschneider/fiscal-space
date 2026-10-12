"""Australian source adapters. Each returns a dataset in the shared app schema."""
from importlib import import_module

# group -> (module, function); imported lazily so one broken adapter cannot block the others.
_ADAPTERS={
    'fiscal':('fiscal','fetch_fiscal'),
    'composition':('composition','fetch_composition'),
    'forecast':('fiscal','fetch_forecast'),
    'debt':('aofm','fetch_debt'),
    'curve':('rba','fetch_curve'),
    'outlook':('outlook','fetch_outlook'),
    'reliefs':('teis','fetch_reliefs'),
}

def _lazy(module,name):
    def run(fetcher):return getattr(import_module(f'.{module}',__name__),name)(fetcher)
    return run

ADAPTERS={group:_lazy(*target) for group,target in _ADAPTERS.items()}
