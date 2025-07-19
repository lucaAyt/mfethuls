from mfethuls.instruments.base import Instrument


class GenericInstrument(Instrument):
    def __init__(self, model, name, parser, characterizer=None):
        super().__init__(model, name)
        self.parser = parser
        self.characterizer = characterizer

    def parse_data(self, dict_path_to_files):
        parsed = self.parser.parse(dict_path_to_files)
        if self.characterizer:
            parsed = self.characterizer.characterize(parsed)
        return parsed
