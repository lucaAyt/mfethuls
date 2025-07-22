from mfethuls.instruments.base import Instrument


class GenericInstrument(Instrument):
    def __init__(self, type_, name, model, parser, characterizer=None, data_root_path=None):
        super().__init__(type_, name, model, data_root_path)
        self.parser = parser
        self.characterizer = characterizer

    def __str__(self):
        return f"<Instrument: {self.name} ({self.type_}, {self.model}, {self.data_root_path})>"

    def __repr__(self):
        char = f", characterizer={self.characterizer.__class__.__name__}" if self.characterizer else ""
        return (f"GenericInstrument(name='{self.name}', type='{self.type_}', model='{self.model}', "
                f"parser={self.parser.__class__.__name__}{char}, data_root_path='{self.data_root_path}')")

    def parse_data(self, dict_data_paths):
        parsed = self.parser.parse(dict_data_paths)
        if self.characterizer:
            parsed = self.characterizer.characterize(parsed)
        return parsed
