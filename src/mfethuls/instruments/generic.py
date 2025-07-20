from mfethuls.instruments.base import Instrument


class GenericInstrument(Instrument):
    def __init__(self, type_, name, model, parser, characterizer=None):
        super().__init__(type_, name, model)
        self.parser = parser
        self.characterizer = characterizer

    def __str__(self):
        return f"<Instrument: {self.name} ({self.type_}, {self.model})>"

    def __repr__(self):
        char = f", characterizer={self.characterizer.__class__.__name__}" if self.characterizer else ""
        return (f"GenericInstrument(name='{self.name}', type='{self.type_}', model='{self.model}', "
                f"parser={self.parser.__class__.__name__}{char})")

    def parse_data(self, dict_path_to_files):
        parsed = self.parser.parse(dict_path_to_files)
        if self.characterizer:
            parsed = self.characterizer.characterize(parsed)
        return parsed
