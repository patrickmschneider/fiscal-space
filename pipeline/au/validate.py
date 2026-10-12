"""Publication checks for Australian datasets; one function per group, owned by each adapter module."""
from importlib import import_module

_VALIDATORS={
    'fiscal':('fiscal','validate_fiscal'),
    'composition':('composition','validate_composition'),
    'forecast':('fiscal','validate_forecast'),
    'debt':('aofm','validate_debt'),
    'curve':('rba','validate_curve'),
    'outlook':('outlook','validate_outlook'),
    'reliefs':('teis','validate_reliefs'),
}

def validate_au(group,data):
    module,name=_VALIDATORS[group]
    getattr(import_module(f'pipeline.au.{module}'),name)(data)
