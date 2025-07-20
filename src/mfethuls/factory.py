from mfethuls.parsers import get_parser
from mfethuls.instruments.generic import GenericInstrument
from mfethuls.characterizers.dsc import DSCProfiling


def create_instrument(type_, name, model, characterizer=None):
    parser = get_parser(type_, model)
    return GenericInstrument(type_, name, model, parser, characterizer)


def create_characterizer(type_, config):
    if type_ == 'dsc' and config.get('type') == 'dsc_profiling':
        return DSCProfiling(config.get('name_program_temperature', 'Tr [°C]'), config.get('sensitivity', 0.1))
