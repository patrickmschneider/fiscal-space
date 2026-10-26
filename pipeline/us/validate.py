"""Publication checks for United States datasets; one function per group, owned by each adapter module."""
from importlib import import_module

_VALIDATORS={
    'fiscal':('fiscal','validate_fiscal'),
    'composition':('composition','validate_composition'),
    'forecast':('fiscal','validate_forecast'),
    'debt':('debt','validate_debt'),
    'curve':('curve','validate_curve'),
    'outlook':('outlook','validate_outlook'),
    'reliefs':('reliefs','validate_reliefs'),
}

def validate_us(group,data):
    module,name=_VALIDATORS[group]
    getattr(import_module(f'pipeline.us.{module}'),name)(data)
